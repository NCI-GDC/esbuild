# -*- coding: utf-8 -*-
"""
esbuild.graph.common.builder
----------------------------------

Defines :class:`GraphIndexBuilder` for use building the primary GDC
graph index.

"""

from cdisutils.log import get_logger
from collections import defaultdict
from copy import copy, deepcopy
from datadog import statsd
from gdcdatamodel import models as md
from psqlgraph import Node, Edge
from sqlalchemy.orm import joinedload

import itertools
import logging
import networkx as nx
import random
import re
import json
from uuid import uuid4

from esbuild.graph.common.mappings import (
    ESMapper,
    ONE_TO_MANY,
    ONE_TO_ONE,
)

from progressbar import (
    ProgressBar,
    Percentage,
    Bar,
    ETA,
)

log = get_logger("graph_index")
log.setLevel(level=logging.INFO)


class GraphIndexBuilder(object):

    """This class handles all of the JSON production for the GDC
    portal. Currently, the entire postgresql database is cached to
    memory.  To save space, edge labels are only maintained if we need
    to distinguish between two different types of edges between a
    single pair of node types.

    Currently, the entire batch of JSON documents is produced at once
    for reasons that follow. There are two topmost denormalization
    functions that are called, denormalize_cases() and
    denormalize_projects(). The former produces all of the
    case, file, and annotations documents. The latter produces
    the project summaries.

    The case denormalization takes the case tree from
    gdcdatamodel and, starting at a case, walks recursively to
    all possible children.  Each child's properties are added to the
    case document at the appropriate level depending on the
    correlation (one to one=singleton, or one to many=list).  The leaf
    node for most paths from case are files, which have a
    special denormalization.

    When a file is gathered from walking the case path, a deep
    copy is both added to the cases file list returned for
    later collection.  Denormalizing a case produces a list of
    files and annotations. Each file is upserted into a persisting
    list of files.  If after denormalizing case 1 who produced
    file A, the upsert involves adding to A the list if not present.
    If we have already gotten file A from another case, it
    means that the file came from multiple cases and we have to
    update file A to also reference case 1.

    In order to make decrease the processing time, there are a lot of
    caching initiatives.  The paths from cases to files are
    cached. The set of files using each data type and experimental
    strategy are cached.  There is also a caching scheme for
    remembering which nodes are walked through a lot and remembering
    which neighbors they have with a given label.

    NOTE: An attempt was made to do this whole thing in parallel,
    however the memory footprint grew to large.  The best method for
    doing this is to use the main process as a workload distributer,
    and have child processes denormalizing cases.  This way,
    the main thread can upsert files on an outbound queue from child
    processes.

    - Josh (jsmiller@uchicago.edu)

    TODOS:
      - figure out a way to parallelize without excess copies

    ===============
    Transformations
    ===============

    In order to update features in the index without propagating
    renames, re-nestings, flattenings etc through the datamodel, the
    denormalization process will reformat the data in (but not limited
    to) the following ways:

    * flattening:
        Some nodes are flattened into properties.  These are typically
        nodes like ``tag`` that only have a ``name`` property. See
        ``self.flatten`` for a complete list.

    * hidden_properties:
        Some nodes should have properties hidden, e.g.
        ``annotation.creator``. In addition, ``project_id`` will be
        hidden on all nodes.

    * s/data_type/data_category/g:
        data_type is renamed data_category, viz.
        https://jira.opensciencedatacloud.org/browse/PGDC-1472

    * s/data_subtype/data_type/g:
        data_subtype is renamed data_type, viz.
        https://jira.opensciencedatacloud.org/browse/PGDC-1472

    * s/related_files/metadata_files/g
        related_files is renamed metadata_files, viz.
        https://jira.opensciencedatacloud.org/browse/PGDC-1838

    """

    data_file_categories = ['data_file', 'metadata_file']
    data_file_indexd_fields = ['acl', 'file_size', 'file_name', 'file_state', 'md5sum']

    mapper = None

    # This defines the possible ways to get from case to indexed
    # files. Should be an iterable of iterables, i.e.
    # [['file'], ['sample', 'aliquot', 'file']]
    case_to_file_paths = None

    # in addition, project_id will be hidden on all nodes
    # {node.label: {set of property keys}}
    hidden_properties = {
        'annotation': {
            'creator',
        }
    }
    # Set of properties to add to hidden_properties for all nodes
    hidden_properties_for_all = {
        'batch_id', 'file_state',
    }

    for node_type in md.Node.get_subclasses():
        hidden_properties.setdefault(node_type.label, set())
        hidden_properties[node_type.label].update(hidden_properties_for_all)

    # Filter nodes out if their properties are a superset of any of
    # the dictionaries listed here by label
    unindexed_by_property = {
        # "label": [{"key1": "value1", "key2": "value2"}]
    }

    INDEXD_URL_TYPE = u'cleversafe'

    required_attrs = [
        'mapper',
        'case_to_file_paths',
        'file_labels',
    ]

    supplement_regexes = [
        re.compile(regex) for regex in [
            'nationwidechildrens.org_biospecimen.([a-zA-Z0-9-]+).xml',
            'nationwidechildrens.org_control.([a-zA-Z0-9-]+).xml',
            'genome.wustl.edu_biospecimen.([a-zA-Z0-9-]+).xml',
            'genome.wustl.edu_control.([a-zA-Z0-9-]+).xml',
            'nationwidechildrens.org_clinical.([a-zA-Z0-9-]+).xml',
            'genome.wustl.edu_clinical.([a-zA-Z0-9-]+).xml',
        ]
    ]

    def __init__(self, psqlgraph_driver, indexd_client, **kwargs):
        """Walks the graph to produce elasticsearch json documents.

        """
        self.indexd = indexd_client
        self.file_metadata = {}  # Cache of file metadata from indexd
        self.skipped_nodes = {}  # Cache of skipped nodes and reason for skipping
        # Set all optional arguments as attributes:
        # NOTE: Selective caching only works when all the non-project nodes
        # that are expected to be picked up are populated with project_id
        # As of Jan 2018, this is true only for newest active projects
        optional_arguments = [
            'build_projects',
            'build_awg',
            'selective_caching',
        ]
        for argname in optional_arguments:
            setattr(self, argname, kwargs.get(argname))

        # Populate self.build_projects
        if self.build_projects is not None:
            if len(self.build_projects) == 0:
                self.build_projects = [('TARGET', 'RT'), ('TCGA', 'MESO')]
            else:
                self.build_projects = [
                    tuple(p.split('-', 1)) for p in self.build_projects
                ]

        # Verify required attributes are set
        for required_attr in self.required_attrs:
            if getattr(self, required_attr) is None:
                raise NotImplementedError(
                    '{} must set {}'
                    .format(self.__class__.__name__, required_attr)
                )

        if self.build_projects:
            log.info('Running partial build')
            log.info('Projects: {}'.format(self.build_projects))
        else:
            log.info('Running full build')

        # Load mapper tree representations
        self.ptree_mapping = {
            'case': self.mapper.get_case_tree().to_dict()
        }
        self.ftree_mapping = {
            'file': self.mapper.get_file_tree().to_dict()
        }
        self.atree_mapping = {
            'annotation': self.mapper.get_annotation_tree().to_dict()
        }

        # Get the actual case mapping to validate against
        self.case_es_mapping = self.mapper.get_case_es_mapping()

        self.g = psqlgraph_driver
        self.G = nx.Graph()

        self.leaf_nodes = ['center', 'tissue_source_site']
        self.experimental_strategies = {}
        self.data_categories = {}
        self.popular_nodes = {}
        self.cases = None
        self.projects = None
        self.relevant_nodes = None
        self.annotations = None
        self.annotation_entities = None
        self.entity_cases = None

        # Different from ``self.data_categories`` in that it's a
        # replacement for a hardcoded dict of data_type, data_subtype
        # relationships.  This is populated by
        # ``self._cache_existing_data_types()``
        self.existing_data_types = {}

        # Suppress entities with redaction annotation if
        # entity.annotation.category not in this list
        self.redacted_but_not_suppressed = ['Subject withdrew consent']

        # Omit entities from these projects
        self.omitted_projects = {
            ('TCGA', 'CNTL'),
            ('TCGA', 'MISC'),
            ('TCGA', 'TEST'),
            ('TCGA', 'DEV1'),
            ('TCGA', 'DEV2'),
            ('TCGA', 'DEV3'),
            ('TCGA', 'FPPP'),
            ('GDC', 'INTERNAL'),
            ('UAT08', 'BROAD-BCR'),
            ('TARGET', 'AML-IF'),
        }

        # The body of these nested documents will be flattened into
        # the parent document using the given key's value
        self.flatten = {
            'tag': 'name',
            'platform': 'name',
            'data_format': 'name',
            'data_subtype': 'name',
            'experimental_strategy': 'name',
            'data_level': 'name',
        }

        # The edges below will maintain labels in the in memory graph,
        # all others will be discarded
        self.differentiated_edges = [
            ('file', 'member_of', 'archive'),
            ('archive', 'member_of', 'file'),
            ('file', 'describes', 'case'),
            ('case', 'describes', 'file'),
            ('file', 'related_to', 'file'),
        ]

        self.file_to_case_paths = [
            list(reversed(l))[1:]+['case']
            for l in self.case_to_file_paths
        ]

        self.possible_associated_entites = [
            'portion',
            'aliquot',
            'case',
            'slide',
        ]

        self.index_file_extensions = {
            '.bai',
            '.tbi',
        }

    def warning(self, title, text, tags=[], *args, **kwargs):
        log.warning("{}: {}".format(title, text))
        statsd.event(
            title,
            text,
            source_type_name="esbuild",
            alert_type="warning",
            tags=tags,
        )

    def error(self, title, text, tags=[], *args, **kwargs):
        log.error("{}: {}".format(title, text))
        statsd.event(
            title,
            text,
            source_type_name="esbuild",
            alert_type="error",
            tags=tags,
        )

    def pbar(self, title, maxval):
        """Create and initialize a custom progressbar

        :param str title: The text of the progress bar
        :param int maxval: The maximumum value of the progress bar

        """
        maxval = maxval or 1  # prevent maxal of 0
        pbar = ProgressBar(widgets=[
            title, Percentage(), ' ',
            Bar(marker='#', left='[', right=']'), ' ',
            ETA(), ' '], maxval=maxval)
        pbar.update(0)
        return pbar

    ###################################################################
    #                        Tree functions
    ###################################################################

    def parse_tree(self, tree, result):
        """Recursively walk a mapping tree and generate a simpler tree with
        just node labels and not correspondences.

        """

        for key in tree:
            if key != 'corr':
                result[key] = {}
                self.parse_tree(tree[key], result[key])
        return result

    def create_tree(self, node, mapping, tree):
        """Recursively walk a mapping to create a walkable tree.

        """

        if node.label in self.leaf_nodes:
            return {}
        submap = mapping[node.label]
        corr, plural = submap['corr']
        for child in self.G.neighbors(node):
            if child.label not in submap:
                continue
            tree[child] = {}
            self.create_tree(child, submap, tree[child])
        return tree

    def walk_tree(self, node, tree, mapping, doc, level=0,
                  ids=None):
        """Recursively walk from a node to all possible neighbors that are
        allowed in the tree structure.  Add the node's properties to the doc.

        """

        corr, plural = mapping[node.label]['corr']
        subdoc = self._get_base_doc(node)
        for child in tree[node]:
            child_corr, child_plural = mapping[node.label][child.label]['corr']
            if child_plural not in subdoc and child_corr == ONE_TO_ONE:
                subdoc[child_plural] = {}
            elif child_plural not in subdoc:
                subdoc[child_plural] = []
            self.walk_tree(child, tree[node], mapping[node.label],
                           subdoc[child_plural], level+1, ids=ids)

            # Aggregate ids as we walk the tree
            top_level_ids = self.mapper.top_level_ids
            if ids is not None and child.label in top_level_ids:
                ids['{}_ids'.format(child.label)].add(child.node_id)
                sub_id = child._props.get('submitter_id')
                if sub_id is not None:
                    ids['submitter_{}_ids'.format(child.label)].add(sub_id)

        if corr == ONE_TO_MANY:
            doc.append(subdoc)
        else:
            doc.update(subdoc)
        return doc

    def copy_tree(self, original, new):
        """Recursively copy the tree so that it can later be pruned per file.

        """

        for node in original:
            new[node] = {}
            self.copy_tree(original[node], new[node])
        return new

    def _get_base_doc(self, node, include_id=True):
        """This is the basic document generator.  Take all the properties of a
        node and add it the the result.  The result doc will have *_id
        where * is the node type.

        """

        base = {}

        if include_id and node.label in self.file_labels:
            base.update({'file_id': node.node_id})

        elif include_id and node._dictionary['category'] == 'analysis':
            base.update({'analysis_id': node.node_id})

        elif include_id:
            base.update({'{}_id'.format(node.label): node.node_id})

        base.update({
            key: value
            for key, value in node._props.iteritems()
            # Only use props in the pinned version of the dictionary
            if key in node.__pg_properties__
            # Ignore certain keys by type
            and key not in self.hidden_properties.get(node.label, [])
            # Hide project_id for all nodes but project, viz. PGDC-1550
            and (key != 'project_id' or node.label == 'project')
        })

        return base

    ###################################################################
    #                        Path functions
    ###################################################################

    def walk_path(self, node, path, whole=False):
        """Given a list of strings, treat it as a path, and yield the end of
        possible traversals.  If `whole` is true, return every node
        along the traversal.

        """

        if path:
            for neighbor in self.neighbors_labeled(node, path[0]):
                if whole or (len(path) == 1 and path[0] == neighbor.label):
                    yield neighbor

                for n in self.walk_path(neighbor, path[1:], whole):
                    yield n

    def walk_paths(self, node, paths, whole=False):
        """Given a list of paths, yield the result of walking each path. If
        `whole` is true, return every node along each traversal.

        """

        return {
            n for n in itertools.chain(*[
                self.walk_path(node, path, whole=whole)
                for path in paths
            ])
        }

    def remove_bam_index_files(self, files):
        return {
            f for f in files
            if not self.is_index_file(f)
        }

    ###################################################################
    #                          Cases
    ##################################################################

    def remove_hidden_nodes(self, nodes):
        """Returns a subset of :param:`nodes` for which
        ``self.is_node_hidden(node)`` is not True.

        :param nodes: iterable of nodes to filter
        :returns: subset set of :param:`nodes`

        """
        return {
            node for node in nodes
            if not self.is_node_hidden(node)
        }

    def get_case_files(self, node):
        """Return a list of file nodes by walking out from case"""

        files = self.walk_paths(node, self.case_to_file_paths)
        # Set file metadata fields from indexd as node properties
        files = (self.add_file_metadata_from_indexd(f) for f in files)

        files = self.remove_bam_index_files(files)
        files = self.remove_hidden_nodes(files)

        return files

    def get_case_tree(self, node):
        """Use tree to create nested json

        :returns: doc, ptree, visited_ids

        """
        ptree = self.get_case_ptree(node)
        visited_ids = defaultdict(set)
        doc = self.walk_tree(
            node,
            ptree,
            self.ptree_mapping,
            [],
            ids=visited_ids
        )[0]

        # Convert to list for later serialization
        visited_ids = {key: list(ids) for key, ids in visited_ids.iteritems()}

        # Inject a dictionary of ids for each visited entity (in
        # TOP_LEVEL_IDS)
        doc.update(visited_ids)

        return doc, ptree, visited_ids

    def get_relevant_ids(self, node, visited_ids):
        """Create a flattened copy of visited_ids to filter relevant
        annotations by entity id

        """

        return [
            _entity_id
            for _entity_type in visited_ids.itervalues()
            for _entity_id in _entity_type
        ] + [node.node_id]

    def get_case_ptree(self, node):
        """Walk graph naturally for tree of node objects"""

        return {node: self.create_tree(node, self.ptree_mapping, {})}

    def get_relevant_annotations(self, file_docs, relevant_ids):
        """Return a flat list of annotations who describe entities in
        :param:`relevant_ids`

        """

        return [
            annotation
            for file_ in file_docs
            for annotation in file_.get('annotations', [])
            if annotation['entity_id'] in relevant_ids
        ]

    def denormalize_case(self, node):
        """Given a case node, return the entire case document,
        the files belonging to that case, and the annotations
        that were aggregated to those files.

        """
        # Walk from case to leaves (not files) and create a case doc,
        # a participant tree, and a list of visited ids
        case, ptree, visited_ids = self.get_case_tree(node)

        # Get the file nodes related to the case
        files = self.get_case_files(node)

        # Create case summary
        case['summary'] = self.get_case_summary(node, files)

        # Take any out of place nodes and put then in correct place in tree
        self.reconstruct_biospecimen_paths(case)

        # Get the case's project
        project = self.patch_project(case['project'])

        # Denormalize the cases files
        returned_files = self.get_case_file_docs(node, ptree, files)

        # Add files to cases
        # Do not add cases, annotations and associated entities to case.files
        case['files'] = [{k: f[k] for k in f if k not in ['cases',
                                                          'annotations',
                                                          'associated_entities']}
                         for f in returned_files]

        self.validate_case(node, case)

        # Flatten ids we visited in traversal to create a list of ids
        # that are relevant to this case (including the case's id)
        relevant_ids = self.get_relevant_ids(node, visited_ids)

        # Pull out the annotations from files
        annotations = self.get_relevant_annotations(returned_files, relevant_ids)

        # Create copy of annotations to return and add properties
        # (note: this is *not* in-place)
        returned_annotations = map(copy, annotations)
        self.patch_annotations(returned_annotations, node, project)

        return case, returned_files, returned_annotations

    def get_case_file_docs(self, node, ptree, files):
        """Given a list of files, return a list of file docs"""
        return [
            self.denormalize_file(file_, ptree)
            for file_ in files
        ]

    def patch_annotations(self, annotations, node, project):
        """Add misc properties to annotations in-place"""

        for annotation in annotations:
            annotation['project'] = project
            annotation['case_id'] = node.node_id
            annotation['case_submitter_id'] = node.submitter_id

    def get_exp_strats(self, files):
        """Get the set of experimental_strategies where intersection of the
        set `files` and the set of files that relate to that
        experimental_strategy is non-null

        """
        self._cache_experimental_strategies()
        for exp_strat, file_list in self.experimental_strategies.iteritems():
            intersection = (file_list & files)
            if intersection:
                yield {
                    'experimental_strategy': exp_strat,
                    'file_count': len(intersection)
                }

    def get_data_categories(self, files):
        """Get the set of data_categories where intersection of the
        set `files` and the set of files that relate to that
        data_category is non-null

        """
        self._cache_data_categories()
        for data_category, file_list in self.data_categories.iteritems():
            intersection = (file_list & files)
            if intersection:
                yield {
                    # data_type is renamed data_category, viz.
                    # https://jira.opensciencedatacloud.org/browse/PGDC-1472
                    'data_category': data_category,
                    'file_count': len(intersection),
                }

    def get_case_summary(self, node, files):
        """Generate a dictionary containing a summary of a cases files
        and file classifications

        """
        return {
            'file_count': len(files),
            'file_size': sum([f['file_size'] for f in files]),
            'experimental_strategies': list(self.get_exp_strats(files)),
            # data_type is renamed data_category, viz.
            # https://jira.opensciencedatacloud.org/browse/PGDC-1472
            'data_categories': list(self.get_data_categories(files)),
        }

    def reconstruct_biospecimen_paths(self, case):
        """For each sample.aliquot or sample.slide, reconstruct
           entire path. Note: the path is culled in common/mappings.py
           in get_case_es_mapping. The new path(s) need to be popped
           there or tests will fail.
        """

        # Get all the "correct" aliquots and slides, save them
        # so we can differentiate between these and the other
        # linked ones
        samples = case.get('samples', [])
        correct_aliquots = set()
        correct_slides = set()
        correct_analytes = set()
        for sample in samples:
            for portion in sample.get('portions', []):
                for slide in portion.get('slides', []):
                    correct_slides.add(slide['slide_id'])
                for analyte in portion.get('analytes', []):
                    correct_analytes.add(analyte['analyte_id'])
                    for aliquot in analyte.get('aliquots', []):
                        correct_aliquots.add(aliquot['aliquot_id'])

        for sample in samples:
            sample['portions'] = sample.get('portions', [])

            # Get all analytes connected to samples (TT-260)
            sample_analytes = sample.pop('analytes', [])
            for analyte in sample_analytes:
                # put analyte under portion
                if analyte['analyte_id'] not in correct_analytes:
                    log.info('Moving {} to correct location'.format(analyte['analyte_id']))
                    sample['portions'].append({
                        'portion_id': str(uuid4()),
                        'analytes': [analyte]
                        })

            # Get all slides connected to samples (SVT-249)
            sample_slides = sample.pop('slides', [])
            for slide in sample_slides:
                # Put slide under portion
                if slide['slide_id'] not in correct_slides:
                    log.info('Moving {} to correct location'.format(slide['slide_id']))
                    sample['portions'].append({
                        'portion_id': str(uuid4()),
                        'slides': [slide]
                        })

            # Get all aliquots connected to samples
            sample_aliquots = sample.pop('aliquots', [])
            for aliquot in sample_aliquots:
                # Put aliquot under analyte
                if aliquot['aliquot_id'] not in correct_aliquots:
                    new_dict = {
                        'analytes': [{
                            'analyte_id': str(uuid4()),
                            'aliquots': [aliquot]
                        }]
                    }
                    # check if another entry already added the fake id
                    if 'portion_id' not in sample['portions']:
                        new_dict['portion_id'] = str(uuid4())
                    sample['portions'].append(new_dict)

            for portion in sample['portions']:
                portion['analytes'] = portion.get('analytes', [])

                # Get aliquots connected to portions
                portion_aliquots = portion.pop('aliquots', [])
                for aliquot in portion_aliquots:
                    # Put aliquot under analyte
                    if aliquot['aliquot_id'] not in correct_aliquots:
                        portion['analytes'].append([{
                            'analyte_id': str(uuid4()),
                            'aliquots': [aliquot]}])

    def patch_project(self, project_doc):
        # Delete some keys from project document
        keys_to_delete = ESMapper.project_keys_to_hide
        for key in keys_to_delete:
            project_doc.pop(key, None)

        # Populate project_id
        code = project_doc.pop('code')
        program = project_doc['program']['name']
        project_id = '{}-{}'.format(program, code)
        project_doc['project_id'] = project_id

        return project_doc

    ###################################################################
    #                       File denormalization
    ###################################################################

    def denormalize_file(self, node, ptree):
        """Given a cases tree and a file node, create the file json
        document.

        """
        # Add file metadata fields from indexd
        node = self.add_file_metadata_from_indexd(node)

        # Create a copy to avoid mutation of passed argument
        ptree = self.copy_tree(ptree, {})

        # Create base file doc
        case_id = ptree.keys()[0].node_id if ptree.keys() else None
        doc = self._get_base_doc(node)

        # Add file fields
        self.add_node_type(node, doc)
        self.add_file_neighbors(node, doc)
        self.add_data_category(node, doc)
        self.add_related_files(node, doc)
        self.add_index_files(node, doc)
        self.add_archives(node, doc)
        doc['cases'] = []
        relevant = self.add_cases(node, ptree, doc)
        self.add_file_associated_entities(node, doc, case_id)
        self.add_annotations(node, relevant, doc)
        self.add_acl(node, doc)
        self.add_file_data_format(node, doc)

        return doc

    def add_file_metadata_from_indexd(self, node):
        """
        Reads file metadata from indexd and sets it to node
        """
        # Try to get cached metadata value
        record = self.file_metadata.get(node.node_id)

        # If not found, get it from indexd
        if not record:
            record = self.indexd.get(node.node_id)
            if not record:
                if node.sysan.get('to_delete'):
                    self.file_metadata[node.node_id] = {'error': 'to_delete file'}
                else:
                    self.error(
                        "No indexd data found for {}, ignoring".format(node),
                        "node_type: {} node_id: {}".format(node.label, node.node_id),
                        tags=["indexd", node.label]
                    )
                return node
            record = record.to_json()
            # Cache indexd record
            self.file_metadata[node.node_id] = record

        # Set node file metadata attributes according to indexd record
        for key in self.data_file_indexd_fields:
            # Try to pick basic value
            value = record.get(key)
            if value is None:
                value = record['metadata'].get(key)
            if key == 'file_state':
                for s3_url in record['urls_metadata'].keys():
                    if record['urls_metadata'][s3_url].get('type', None) == self.INDEXD_URL_TYPE:
                        value = record['urls_metadata'][s3_url].get('state', None)

            # Special values
            if key == 'file_size':
                value = record.get('size')
            elif key == 'md5sum':
                value = record['hashes'].get('md5')
            # Set node attribute from indexd record
            setattr(node, key, value)

        return node

    def add_node_type(self, node, doc):
        doc['type'] = node.label

    def get_data_format(self, node):
        """Return the ``data_format`` given a file node based on

        1. its properties (data_format or file_format)
        2. an edge to a DataFormat node

        """

        if 'data_format' in node._props:
            format_ = node._props['data_format']

        elif 'file_format' in node._props:
            format_ = node._props['file_format']

        else:
            # get data_format from edge to DataFormat
            formats = list(self.neighbors_labeled(node, 'data_format'))

            # Get the first format
            if formats:
                format_ = formats.pop()._props['name']
            else:
                format_ = None

            # If there are still formats in a list, record warning
            if formats:
                self.warning(
                    "{} has mulitple data_formats".format(node),
                    "{} has additional data_formats: {}".format(node, formats),
                    tags=["file_id:{}".format(node.node_id)],
                )

        return format_

    def prune_case(self, relevant_nodes, ptree, keys):
        """Start with whole case tree and remove any nodes that did not
        contribute the the creation of this file.

        .. note:: :param:`ptree` is edited **in place*

        :param relevant_nodes:
            The ancestors that should not be pruned from the tree
            (most likely self.relevant_nodes[some_file])
        :param ptree:
            The canonical ptree dict tree containing a the descendents
            of a case
        :param keys:
           Only prune a given node ``node`` if ``node.label`` in keys

        """
        for node in ptree.keys():
            if ptree[node]:
                self.prune_case(relevant_nodes, ptree[node], keys)
            if node.label in keys and node not in relevant_nodes:
                ptree.pop(node)

    def add_file_data_format(self, node, doc):
        """Add (or overwrite) the data format if found

        """
        data_format = self.get_data_format(node)
        if data_format:
            doc['data_format'] = data_format

    def add_file_neighbors(self, node, doc):
        """Given a file, walk to all of it's neighbors specified by the schema
        and add them to the document.

        """

        auto_neighbors = [n for n in dict(self.ftree_mapping['file']).keys()
                          if n not in ['archive', 'portion', 'file']]
        for neighbor in set(self.neighbors_labeled(node, auto_neighbors)):
            corr, label = self.ftree_mapping['file'][neighbor.label]['corr']
            if neighbor.label in self.flatten:
                base = neighbor[self.flatten[neighbor.label]]
            else:
                base = self._get_base_doc(neighbor)
            if corr == ONE_TO_ONE:
                if label in doc:
                    self.warning(
                        "Duplicate edge on {}".format(node.node_id),
                        ("File {} has more than one {}, this is unexpected."
                         .format(node, label)),
                        tags=["file_id:{}".format(node.node_id)],
                    )
                else:
                    doc[label] = base
            else:
                if label not in doc:
                    doc[label] = []
                doc[label].append(base)

    def is_index_file(self, node):
        """Given a node, return whether it is considerend an 'index file'

        :returns: bool

        """
        # Active index files
        if node._dictionary['category'] == 'index_file':
            return True

        # Legacy index files
        elif node.label == 'file':
            # Set file metadata fields
            node = self.add_file_metadata_from_indexd(node)

            for extension in self.index_file_extensions:
                if getattr(node, 'file_name', '').endswith(extension):
                    return True

        else:
            return False

    def get_file_index_files(self, node):
        """Given a file, return any neighboring index files"""
        return [
            n for n in list(self.neighbors_labeled(node, 'file'))
            if self.G[node][n].get("label") == "related_to"
            and self.is_index_file(n)
        ]

    def add_index_files(self, node, doc):
        """Given a file, walk to any neighboring index files and add
        them to the index_files section of the document.

        """
        index_file_docs = []
        index_files = self.get_file_index_files(node)

        log.debug('Found index files for {}: {}'.format(node, index_files))

        for index_file in index_files:
            index_file_doc = self._get_base_doc(index_file)
            index_file_doc['data_format'] = self.get_data_format(index_file)

            index_file_docs.append(index_file_doc)

        if index_file_docs:
            doc['index_files'] = index_file_docs

    def add_related_files(self, node, doc):
        """Given a file, walk to any (non data-from) neighboring files and add
        them to the related_files section of the document.

        ..note::
            Index files, e.g. ``.bai`` files, are added by
            :func:`self.add_index_files`

        """
        rf_docs = []

        metadata_labels = [
            'analysis_metadata',
            'run_metadata',
            'experiment_metadata',
        ]

        # Get related_files
        related_files = [
            n for n in list(self.neighbors_labeled(node, 'file'))
            if self.G[node][n].get("label") == "related_to"
            and not self.is_index_file(n)
        ]

        related_files += list(self.neighbors_labeled(node, metadata_labels))

        for related_file in related_files:
            # Add file metadata fields from indexd
            related_file = self.add_file_metadata_from_indexd(related_file)

            rf_doc = self._get_base_doc(related_file, include_id=False)
            rf_doc['file_id'] = related_file.node_id

            # Data types
            data_subtypes = self.neighbors_labeled(
                related_file,
                'data_subtype',
            )

            for dst in data_subtypes:
                # data_subtype is renamed data_type, viz.
                # https://jira.opensciencedatacloud.org/browse/PGDC-1472
                rf_doc['data_type'] = dst['name']
                self.add_data_category(related_file, rf_doc)

            # Type
            if related_file._props.get('file_name', '').endswith('.sdrf.txt'):
                rf_doc['type'] = 'magetab'
            else:
                rf_doc['type'] = None

            # Access
            self.add_file_access(related_file, rf_doc)

            rf_doc['data_format'] = self.get_data_format(related_file)

            rf_docs.append(rf_doc)

        # Legacy files have two different types of relationships to
        # file, one that is `member_of` (which goes into
        # file.archives) and one that is `related_to` (which goes
        # here).  For now, we don't do this for non-legacy files.
        if node.label == 'file':
            for archive in set(self.neighbors_labeled(node, 'archive')):
                if self.G[node][archive].get('label') != 'member_of':
                    name = '{}.{}.0.tar.gz'.format(
                        archive['submitter_id'], archive['revision'])
                    rf_docs.append({
                        'file_id': archive.node_id,
                        'file_name': name,
                        'type': 'magetab',
                        'access': 'open',
                    })

        if rf_docs:
            # related_files is renamed metadata_files,
            # viz. https://jira.opensciencedatacloud.org/browse/PGDC-1838
            doc['metadata_files'] = rf_docs

    def add_archives(self, node, doc):
        """For each archive attached to a given file node, multixplex on
        whether it is a containing or related archive and add it to the
        respective places in the doc.

        """

        for archive in set(self.neighbors_labeled(node, 'archive')):
            is_skipped_legacy_edge = (
                node.label == 'file' and
                self.G[node][archive].get('label') != 'member_of'
            )

            if is_skipped_legacy_edge:
                continue

            if 'archive' in doc:
                return self.warning(
                    "Duplicate archives for {}".format(node),
                    ("File {} has more than archive.".format(node)),
                    tags=["file_id:{}".format(node.node_id)],
                )

            archive_doc = self._get_base_doc(archive)

            # Archive is a file_doc for the legacy index, so it
            # will have `file_id` not `archive_id`.  If so, coerce
            # it back here.
            if 'file_id' in archive_doc:
                archive_doc['archive_id'] = archive_doc.pop('file_id')

            doc['archive'] = archive_doc

    def add_data_category(self, node, doc):
        """Add the data_subtype to the file document with child data_category

        """

        self._cache_data_categories()
        data_categories = [
            data_category
            for data_category, files in self.data_categories.items()
            if node in files
        ]
        if data_categories:
            # data_type is renamed data_category, viz.
            # https://jira.opensciencedatacloud.org/browse/PGDC-1472
            doc['data_category'] = data_categories[0]

    def add_cases(self, node, ptree, doc):
        """Given a file and a case tree, re-insert the case as a
        child of file with only the biospecimen entities that are
        direct ancestors of the file.

        """
        if not ptree:
            log.warn('No ptree (case tree) for %s', node)
            return []

        if node not in self.relevant_nodes:
            log.warn('No relevant cases for %s', node)
            return []

        relevant = self.relevant_nodes[node]
        prune_keys = ['sample', 'portion', 'analyte', 'aliquot', 'file']

        self.prune_case(relevant, ptree, prune_keys)

        doc['cases'] = [
            self.walk_tree(path, ptree, self.ptree_mapping, [])[0]
            for path in ptree
        ]

        for case in doc['cases']:
            self.patch_project(case['project'])
            self.reconstruct_biospecimen_paths(case)

        return relevant

    def add_annotations(self, node, relevant, doc):
        """Given a file node, aggregate all of the annotations from a pruned
        case tree and insert them at the root level of the file
        document.

        """

        annotations = doc.pop('annotations', [])

        for relevant_node in relevant:
            ann_docs = self.annotation_entities.get(relevant_node, {})
            annotations.extend(ann_docs.values())

        if annotations:
            doc['annotations'] = annotations

    def add_acl(self, node, doc):
        """Add the protection status of a file to the file document.

        """

        self.add_file_access(node, doc)
        doc['acl'] = node.acl

    def add_file_access(self, node, doc):
        """Summarizes whether the ACL implies that the file is either ``open``
        or ``controlled``

        """

        if node.acl == ['open']:
            doc['access'] = 'open'
        else:
            doc['access'] = 'controlled'

    def get_file_associated_entities(self, node):
        """Returns a list of entities that are 'associated' with a file"""
        return list(self.neighbors_labeled(
            node, self.possible_associated_entites))

    def add_file_associated_entities(self, node, doc, case_id):
        self._cache_entity_cases()

        docs = []
        entities = self.get_file_associated_entities(node)

        for e in entities:

            if e not in self.entity_cases:
                # Skip, the cases is likely missing because it is omitted
                continue

            case = self.entity_cases[e]
            subdoc = {
                'entity_type': e.label,
                'entity_id': e.node_id,
                'case_id': case.node_id
            }

            entity_submitter_id = e._props.get('submitter_id')
            if entity_submitter_id:
                subdoc['entity_submitter_id'] = entity_submitter_id

            docs.append(subdoc)

        if docs:
            doc['associated_entities'] = docs

    def upsert_file_into_dict(self, files, file_doc):
        did = file_doc['file_id']
        if did not in files:
            files[did] = file_doc
        else:
            # If file in dict already, merge cases
            existing_ids = {c['case_id'] for c in files[did]['cases']}
            for case in file_doc['cases']:
                case_id = case['case_id']
                if case_id not in existing_ids:
                    files[did]['cases'] += file_doc['cases']

    ###################################################################
    #                       Project summaries
    ###################################################################

    def denormalize_project(self, p):
        """Summarize a project.

        """
        self._cache_all()
        doc = self._get_base_doc(p)

        # Get programs
        program = self.neighbors_labeled(p, 'program').next()
        log.info('Program: {}'.format(program))
        doc['program'] = self._get_base_doc(program)

        # project_id <- program.name-project.code
        self.patch_project(doc)

        log.info('Finding cases')
        cases = list(self.neighbors_labeled(p, 'case'))
        log.info('Got {} cases'.format(len(cases)))

        # Get files
        log.info('Getting files')
        files = set()
        case_files = {}
        for case in cases:
            case_files[case] = self.remove_bam_index_files(
                self.walk_paths(case, self.case_to_file_paths))
            files = files.union(case_files[case])

        log.info('Got {} total files from {} cases'.format(
            len(files), len(case_files)))

        # filter files
        files = {
            f for f in files
            if not self.is_node_hidden(f)
        }

        log.info('Got {} files from {} cases'.format(
            len(files), len(case_files)))

        # Get experimental strategies
        exp_strat_summaries = []
        self._cache_experimental_strategies()
        for exp_strat in self.experimental_strategies.keys():
            log.info('exp_strat: {}'.format(exp_strat))
            exp_files = (self.experimental_strategies[exp_strat] & files)

            if not len(exp_files):
                continue

            case_count = len({
                p for p, p_files in case_files.iteritems()
                if len(exp_files & p_files)
            })

            exp_strat_summaries.append({
                'case_count': case_count,
                'experimental_strategy': exp_strat,
                'file_count': len(exp_files),
            })

        # Get data types
        data_category_summaries = []
        self._cache_data_categories()

        for data_category in self.data_categories.keys():
            log.info('data_category: {}'.format(data_category))
            dt_files = (self.data_categories[data_category] & files)

            if not len(dt_files):
                continue

            case_count = len({
                p for p, p_files in case_files.iteritems()
                if len(dt_files & p_files)
            })

            data_category_summaries.append({
                'case_count': case_count,
                # data_type is renamed data_category, viz.
                # https://jira.opensciencedatacloud.org/browse/PGDC-1472
                'data_category': data_category,
                'file_count': len(dt_files),
            })

        # Summarize diesease_type and primary_site
        disease_types = set()
        primary_sites = set()

        for case in cases:
            if case['disease_type']:
                disease_types.add(case['disease_type'])
            if case['primary_site']:
                primary_sites.add(case['primary_site'])

        doc['disease_type'] = list(disease_types)
        doc['primary_site'] = list(primary_sites)

        # Compile summary
        doc['summary'] = {
            'case_count': len(cases),
            'file_count': len(files),
            'file_size': sum([f['file_size'] for f in files]),
        }

        if exp_strat_summaries:
            doc['summary']['experimental_strategies'] = exp_strat_summaries

        if data_category_summaries:
            # data_type is renamed data_category, viz.
            # https://jira.opensciencedatacloud.org/browse/PGDC-1472
            doc['summary']['data_categories'] = data_category_summaries

        return doc

    ###################################################################
    #                     Topmost denorm functions
    ###################################################################

    def denormalize_cases(self, cases=None):

        """If cases is not specified, denormalize all cases in
        the graph.  If cases is specified, denormalize only those
        given.

        :returns:
            Tuple containing (case docs, file docs, annotation docs)

        """
        self._cache_all()
        case_docs, ann_docs, file_docs = [], {}, {}
        if not cases:
            cases = self.cases
        pbar = self.pbar('Denormalizing cases ', len(cases))
        for n in cases:
            pa, fi, an = self.denormalize_case(n)
            case_docs.append(pa)
            for a in an:
                if a['annotation_id'] not in ann_docs:
                    ann_docs[a['annotation_id']] = a
            for f in fi:
                self.upsert_file_into_dict(file_docs, f)
            pbar.update(pbar.currval+1)
        pbar.finish()
        return case_docs, file_docs.values(), ann_docs.values()

    def denormalize_projects(self, projects=None):
        """If projects is not specified, denormalize all projects in
        the graph.  If projects is specified, denormalize only those
        given.

        """

        self._cache_all()
        if not projects:
            projects = self.projects
        project_docs = []
        pbar = self.pbar('Denormalizing projects ', len(projects))
        for project in projects:
            project_docs.append(self.denormalize_project(project))
            pbar.update(pbar.currval+1)
        pbar.finish()
        return project_docs

    def denormalize_annotation(self, node):
        """Denormalize a specific annotation.

        .. note: The project of an annotation will be injected during
        case denormalization.

        """
        ann_doc = self._get_base_doc(node)
        entities = self.G.neighbors(node)
        if len(entities) == 0:
            self.error(
                'Annotation has no entities',
                "{} has zero entity associated.".format(node.node_id),
                tags=["annotation_id:{}".format(node.node_id)],
            )
            # There are no entities! We cannot proceed.
            ann_doc.update(dict(
                entity_type=None,
                entity_id=None,
                entity_submitter_id=None,
            ))
            return ann_doc

        if len(entities) > 1:
            self.warning(
                'Annotation has multiple entities',
                "{} has more than one entity associated.".format(node.node_id),
                tags=["annotation_id:{}".format(node.node_id)],
            )
            # There are too many entities! proceed with only the first
            # entity

        entity = entities[0]
        ann_doc['entity_type'] = entity.label
        ann_doc['entity_id'] = entity.node_id
        esid = entity._props.get('submitter_id')
        if esid:
            ann_doc['entity_submitter_id'] = esid

        for e in node.edges_out:
            if e.get_name() == 'AnnotationRelatesToCase':
                ann_doc['case_id'] = e.dst_id

        return ann_doc

    def denormalize_all(self):
        """Return an entire index worth of case, file, annotation, and
        project documents

        """
        cases, files, annotations = self.denormalize_cases()
        projects = self.denormalize_projects()
        return cases, files, annotations, projects

    def denormalize_cases_sample(self, k=10):
        """Return an entire index worth of case, file, annotation
         documents

        """
        self._cache_all()
        cases = random.sample(self.cases, k)
        cases, files, annotations = self.denormalize_cases(cases)
        return cases, files, annotations

    def denormalize_sample(self, k=10):
        """Return an entire index worth of case, file, annotation, and
        project documents

        """
        cases, files, annotations = self.denormalize_sample_cases(k)
        projs = random.sample(self.projects, 1)
        projects = self.denormalize_projects(projs)
        return cases, files, annotations, projects

    ###################################################################
    #                         Graph functions
    ###################################################################

    def nodes_labeled(self, labels):
        """Returns an iterator over the edges in the graph with label `label`

        """

        labels = tuple(labels) if hasattr(labels, '__iter__') else (labels,)
        for n, p in self.G.nodes_iter(data=True):
            if n.label in labels:
                yield n

    @staticmethod
    def node_labels_by_category(categories):
        """Returns an iterator of node labels that are files

        """

        categories = (
            tuple(categories) if hasattr(categories, '__iter__')
            else (categories,)
        )

        return [
            n.label for n in Node.get_subclasses()
            if n._dictionary['category'] in categories
        ]

    def neighbors_labeled(self, node, labels, expected=None):
        """For a given node, return an iterator with generates neighbors to
        that node that are in a list of labels.  `label` can be either a
        string or list of strings.

        :param is_expected: Int count of expected elements

        """
        labels = tuple(labels) if hasattr(labels, '__iter__') else (labels,)

        if node in self.popular_nodes:
            if labels not in self.popular_nodes[node]:
                neighbors = self._cache_popular_neighbor(
                    node, self.G.neighbors(node), labels)
            else:
                neighbors = self.popular_nodes[node][labels]
        else:
            temp = self.G.neighbors(node)
            if len(temp) > 200:
                neighbors = self._cache_popular_neighbor(node, temp, labels)
            else:
                neighbors = {n for n in temp if n.label in labels}

        count = 0
        for n in neighbors:
            count += 1
            yield n

        if expected is not None and count != expected:
            self.warning(
                "{}: unexpected no. of '{}' neighbors".format(node, labels),
                '{}: {} != {} (expected)'.format(node, count, expected),
                tags=["{}:{}".format(node.label, node.node_id)])

    ###################################################################
    #                       Validation functions
    ###################################################################

    def validate_project_file_counts(self, project_doc, file_docs):
        log.info('Validating {}'.format(project_doc['project_id']))
        actual = len([f for f in file_docs
                      if project_doc['project_id']
                      in {p['project']['project_id']
                          for p in f['cases']}])
        expected = project_doc['summary']['file_count']
        if actual != expected:
            self.error(
                'File count mismatch',
                '{} file count mismatch: {} != {}'.format(
                    project_doc['project_id'], actual, expected),
                tags=["project_id:{}".format(project_doc['project_id'])],
            )

    def validate_docs(self, case_docs, file_docs, ann_docs, project_docs):
        for project_doc in project_docs:
            self.validate_project_file_counts(project_doc, file_docs)
            case_sample = random.sample(case_docs, min(len(case_docs), 100))
            for case_doc in case_sample:
                self.verify_data_category_count(case_doc)
        self.validate_annotations(ann_docs)

    def validate_annotations(self, ann_docs):
        for ann_doc in ann_docs:
            if ann_doc['entity_type'] == 'case':
                if ann_doc['entity_id'] != ann_doc['case_id']:
                    self.error(
                        'Annotation case_id does not match entity_id',
                        'case_id/entity_id mismatch: {} != {}'.format(
                            ann_doc['entity_id'], ann_doc['case_id']),
                        tags=["annotation_id:{}".format(
                            ann_doc.get("annotation_id", "?"))],
                    )

    def verify_data_category_count(self, case):
        for data_category in self.existing_data_types.keys():
            calc = len([
                f for f in case['files']
                if f.get('data_category') == data_category
            ])

            act = ([
                d['file_count']
                for d in case['summary']['data_categories']
                if d['data_category'] == data_category
            ][:1] or [0])[0]

            if act != calc:
                self.error(
                    'Inconsistent data_category count',
                    '{}: {} != {}'.format(data_category, act, calc),
                    tags=["case_id:{}".format(case.get("case_id", "?"))],
                )

    def validate_against_mapping(self, doc, mapping):
        """Recursively verify that all keys in the document are in the
        provided Elasticsearch mapping

        """
        if isinstance(doc, dict):
            # Recurse through all keys in dictionary
            for doc_key in doc.keys():
                if doc_key not in mapping['properties']:
                    self.error(
                        'Key not in mapping',
                        "Key '{}' was not found in mapping keys {}".format(
                            doc_key, mapping['properties'].keys()),
                        tags=["key:{}".format(doc_key)],
                    )
                    # Remove so there is not an error when populating index
                    doc.pop(doc_key, None)
                else:
                    self.validate_against_mapping(
                        doc[doc_key], mapping['properties'][doc_key])

        elif isinstance(doc, list):
            # Loop over all all items in the list. Note that ES
            # mappings do not distinguish between lists of subdocs and
            # single subdocs.
            for list_entry in doc:
                self.validate_against_mapping(list_entry, mapping)

    def validate_case(self, node, case):
        # Check that file count = summary.file_count
        if len(case['files']) != case['summary']['file_count']:
            self.error(
                'Inconsistent case file count',
                '{}: {} != {}'.format(node.node_id, len(case['files']),
                                      case['summary']['file_count']),
                tags=["case_id:{}".format(node.node_id)],
            )

        # Check for keys that are in the doc but not in the mapping
        self.validate_against_mapping(case, self.case_es_mapping)

    ###################################################################
    #                       Caching functions
    ###################################################################

    @staticmethod
    def is_harmonized_file(node):
        return (
            node.label == 'file' and
            node._sysan.get('source', '').endswith('_alignment')
        )

    def is_old_supplement_file(self, node):
        if node.label == 'file':
            node = self.add_file_metadata_from_indexd(node)
            return any(p.match(node._props.get('file_name', ''))
                       for p in self.supplement_regexes)
        return False

    def is_file_indexed(self, node):
        """Returns false if node is a file that is not supposed to be indexed.

        """

        # This function should test only file nodes
        if node.label not in self.file_labels:
            return True

        # Add file metadata to the node
        node = self.add_file_metadata_from_indexd(node)

        # Remove files with no acl entries
        if len(node.acl) == 0:
            log.info('File not indexed (empty acl): %s', node)
            return False

        # Skip old versions of supplement xmls
        if self.is_old_supplement_file(node):
            log.info('File not indexed (deprecated supplement): %s', node)
            return False

        # Skip old representation of harmonized files
        if self.is_harmonized_file(node):
            log.info('File not indexed (deprecated harmonized file): %s', node)
            return False

        # Is file to_delete
        if node.system_annotations.get("to_delete"):
            return False

        return True

    def is_omitted_project_or_neighbor_case(self, node):
        """Returns false if the node is a project that is not supposed to be
        indexed.

        """

        if node.label == 'project':
            projects = [node]
        elif node.label == 'case':
            projects = list(self.neighbors_labeled(node, 'project', 1))
        else:
            return False

        project_codes = [project.code for project in projects]
        program_names = [
            program.name
            for project in projects
            for program in self.neighbors_labeled(project, 'program', 1)
        ]

        # Check if project is not released (for non-AWG build only)
        if not self.build_awg:
            for project in projects:
                if project.released is not True:
                    log.info('Omitting %s, project %s not released', node, project)
                    return True

        # Check project and program against omitted_projects
        for program_name in program_names:
            for project_code in project_codes:
                if (program_name, project_code) in self.omitted_projects:
                    return True
                elif self.build_projects:
                    if (program_name, project_code) in self.build_projects:
                        return False
                    else:
                        return True

        return False

    def is_unindexed_case(self, node):
        return (
            node.label == 'case'
            and not list(self.neighbors_labeled(node, 'project', 1))
        )

    def is_node_unindexed_by_property(self, node):
        """Returns True if node should be removed because its properties are
        specified in self.unindexed_by_property as an indication to
        remove it from the index.

        """

        filters = self.unindexed_by_property.get(node.label, [])

        for filter_ in filters:
            is_subset = not set(filter_.items()) - set(node._props.items())

            if is_subset:
                return True

        return False

    def is_node_public(self, node):
        """Returns whether a node is public.

        A node is public if:
        1. it's a project and it's released
        2. it's a node with a 'state' that is a 'released' state
        3. it's not a project or it doesn't have a state defined on it

        When self.build_awg is set, the rules are different:
        1. it's a project and it is 'awg_review' == True
        2. it's a node with a 'state' that is a AWG state
        """

        # AWG mode
        if self.build_awg:
            awg_states = {'live', 'submitted', 'processed', 'released'}

            if node.label == 'project':
                return node.awg_review is True

            # NOTE: this one is questionable
            elif 'state' not in node.__pg_properties__:
                return True  # True or False?

            elif node.state in awg_states:
                return True

        # Regular esbuild
        else:
            released_states = {'live', 'released'}

            if node.label == 'project':
                return node.released is True

            elif 'state' not in node.__pg_properties__:
                return True

            elif node.state in released_states:
                return True

    def cache_skipped_node(self, node, reason):
        """
        Caches skipped node in self.skipped_nodes['{reason-for-skipping}']
        """
        self.skipped_nodes.setdefault(reason, [])
        self.skipped_nodes[reason].append(str(node))

    def is_node_indexed(self, node):
        """Returns false if the node is not supposed to be indexed"""

        # Is the node allowed to be displayed publicly
        if not self.is_node_public(node):
            self.cache_skipped_node([node, node._props.get('state')], 'not-public')
            return False

        if self.is_unindexed_case(node):
            self.cache_skipped_node(node, 'unindexed-case')
            return False

        # Check for non-indexed files
        if not self.is_file_indexed(node):
            self.cache_skipped_node(node, 'unindexed-file')
            return False

        # Check for non-indexed files
        if self.is_node_unindexed_by_property(node):
            self.cache_skipped_node(node, 'unindexed-by-property')
            return False

        # Check for omitted_projects
        if self.is_omitted_project_or_neighbor_case(node):
            self.cache_skipped_node(node, 'omitted-project')
            return False

        return True

    def is_node_hidden(self, node):
        """Return True if the node should be traversed (and therefore must
        remain in the cache) but should not appear in any documents

        """

        # Hide all submitted_* node types from indices
        if node.label.startswith('submitted_'):
            return True

        if node.label == 'archive':
            return True

        return False

    @staticmethod
    def truncate_path(path, label):
        """
        Given a path (a list of node labels), "truncate" it from the left
        such that it starts with the given label, or return [], e.g.:

        truncate_path(["a", "b", "c"], "a") -> ["b", "c"]
        truncate_path(["c", "d"], "b") -> []

        """
        for i, currlabel in enumerate(path):
            if currlabel == label:
                return path[i+1:]
        return []

    def get_suppressed_children(self, redacted):
        """Get the children of a redacted node.

        """
        to_suppress = []
        if redacted.label == "case":
            paths = self.case_to_file_paths
        else:
            paths = [self.truncate_path(p, redacted.label)
                     for p in self.case_to_file_paths]
            # filter empty paths
            paths = [p for p in paths if p]
        log.info("suppressing %s, which is redacted directly.", redacted)
        to_suppress.append(redacted)
        log.info("Walking down towards file with paths %s", paths)
        extra = self.walk_paths(redacted, paths, whole=True)
        log.info("Found %s other things to suppress by walking from %s",
                 extra, redacted)
        to_suppress.extend(extra)
        return to_suppress

    def get_redaction_annotations(self):
        """Returns an iterator of annotations that should cause redactions"""

        return (
            annotation for annotation in self.nodes_labeled('annotation')
            if annotation.classification == "Redaction"
            and annotation.status != 'Rescinded'
            and annotation.category not in self.redacted_but_not_suppressed
        )

    def suppressed_nodes(self):
        """
        Find all nodes that need to be suppressed due to redactions.
        """

        to_suppress = []
        for redaction in self.get_redaction_annotations():
            redacted_list = self.G.neighbors(redaction)

            if len(redacted_list) == 0:
                # If there is no entity, then we have to move on to
                # the next annotation
                self.error(
                    'Redaction annotation no entities',
                    "Redaction {} has zero entities associated.".format(
                        redaction),
                    tags=["annotation:{}".format(redaction)],
                )
                continue

            if len(redacted_list) > 1:
                # an annotation should only ever annotate one thing,
                # however, proceed to redact them all
                self.warning(
                    'Redaction annotation has multiple entities',
                    ("{} has more than one entity associated. "
                     "For security reasons, removing all from index!")
                    .format(redaction),
                    tags=["annotation:{}".format(redaction)],
                )

            for redacted in redacted_list:
                to_suppress += self.get_suppressed_children(redacted)

            # returning the redaction annotations themselves here might
            # seem weird, but including the redaction annotations
            # themselves without the things they point to won't work, so
            # we have to remove them.
            log.info("suppressing %s, the redaction annotation.", redaction)
            to_suppress.append(redaction)

        return to_suppress

    def remove_unindexed_nodes_from_graph(self):
        """
        Removes nodes from cached graph in self.G according to:
        - is_node_indexed(node)
        - suppressed_nodes()
        """
        log.info('Selecting entities to be removed from cache...')
        removed_nodes = [node for node in self.G.nodes()
                         if not self.is_node_indexed(node)]
        log.info("Removing {} nodes from cache".format(len(removed_nodes)))
        self.G.remove_nodes_from(removed_nodes)
        log.info("Finding and removing suppressed nodes")
        suppressed = self.suppressed_nodes()
        log.info("Removing %s suppressed nodes", len(suppressed))
        self.G.remove_nodes_from(suppressed)

    def iter_database_edges(self):
        """Returns an iterable of edges to load from the database.

        Eagerly (with join) loads the source and destination of the edge.
        NOTE: All nodes that are not Project and expected to be picked up
        must have project_id field corresponding to project they are part of
        As of Jan 2018, this is not true for Legacy and old Active nodes

        NOTE: [AWG build mode] If self.build_awg is set, will return only edges
        that are connected to nodes that are part of awg_review == True projects
        """

        if (self.build_awg or self.selective_caching) and self.build_projects:
            # Load only node ids with relevant project_id's
            project_ids = ['-'.join(p) for p in self.build_projects]

            # For AWG build, keep only awg_review == True project subset
            if self.build_awg:
                awg_projects = {
                    '-'.join([p.programs[0].name, p.code]) for p in
                    self.g.nodes(md.Project).props(awg_review=True)
                }
                project_ids = [p for p in project_ids if p in awg_projects]

            relevant_node_ids = {
                nd.node_id for nd in
                self.g.nodes().prop_in('project_id', project_ids)
            }

            # Add relevant Project nodes to relevant nodes set:
            projects = list({p[1] for p in self.build_projects})
            relevant_projects = self.g.nodes(md.Project).prop_in('code', projects)

            relevant_node_ids.update([p.node_id for p in relevant_projects])

            # Query only relevant edges 
            query = lambda node_type: self.g.edges(node_type).src(relevant_node_ids)

        else:
            # Query all edges
            query = lambda node_type: self.g.edges(node_type)

        return itertools.chain(*[
            query(subclass)
            .options(joinedload(subclass.src))
            .options(joinedload(subclass.dst))
            .yield_per(int(1e5))
            for subclass in Edge.__subclasses__()
        ])

    def cache_database(self):
        """Load the database into memory and remember only edge labels that we
        will need to distinguish later.

        """

        with self.g.session_scope():
            pbar = self.pbar('Caching Database: ', self.g.edges().count())
            # Cache graph to self.G
            # NOTE: if build_awg or selective_caching are set, will only iterate over relevant edges
            for e in self.iter_database_edges():
                pbar.update(pbar.currval+1)
                triple = (e.src.label, e.label, e.dst.label)
                needs_differentiation = (triple in self.differentiated_edges)
                if triple == ("file", "data_from", "file"):
                    # for files that are "data_from" other files, the
                    # centers and aliquots of the source files count
                    # as neighbors of the dst files
                    for center in e.src.centers:
                        self.G.add_edge(e.dst, center)
                    for aliquot in e.src.aliquots:
                        self.G.add_edge(e.dst, aliquot)
                if e.label == 'relates_to' and e.__dst_class__ == 'Case':
                    pass
                elif needs_differentiation and e._props:
                    self.G.add_edge(
                        e.src, e.dst, label=e.label, props=e._props)
                elif needs_differentiation and not e._props:
                    self.G.add_edge(e.src, e.dst, label=e.label)
                elif e._props:
                    self.G.add_edge(e.src, e.dst, props=e._props)
                else:
                    self.G.add_edge(e.src, e.dst)
            pbar.finish()

        # Prune graph
        log.info('Cached {} nodes'.format(self.G.number_of_nodes()))
        self.remove_unindexed_nodes_from_graph()

        # Aggressively cache relationships, nodes by type, traversals, etc.
        self._cache_all()

    def _cache_all(self):
        """Create key value maps to cache nodes by label, by path, etc.

        """

        self._cache_existing_data_types()
        self._cache_experimental_strategies()
        self._cache_data_categories()
        self._cache_annotations()
        self._cache_relevant_nodes()
        self._cache_entity_cases()
        self._cache_cases()
        self._cache_projects()

    def _cache_projects(self):
        """Save a list of all Project nodes"""

        if not self.projects:
            log.info('Caching projects...')
            self.projects = list(self.nodes_labeled('project'))

    def _cache_cases(self):
        """Save a list of all Case nodes"""

        if not self.cases:
            log.info('Caching cases...')
            self.cases = list(self.nodes_labeled('case'))

    def _cache_entity_cases(self):
        """Cache the related Case nodes for each file"""

        if self.entity_cases:
            return

        entities = list(self.nodes_labeled(self.possible_associated_entites))
        pbar = self.pbar('Caching entity cases: ', len(entities))
        self.entity_cases = {}

        for e in entities:
            if e.label == "case":
                # if the associated entity is a case, it's case is
                # just itself. this is kindy of sketchy but w/e
                self.entity_cases[e] = e
                continue

            paths = (
                self.truncate_path(path, e.label)
                for path in  self.file_to_case_paths
            )
            cases = self.walk_paths(e, paths)

            if len(cases) > 1:
                self.warning(
                    'Entity associated with > 1 case',
                    '{}: Found {} cases'.format(e, len(cases)),
                    tags=["entity:{}".format(e)],
                )
                return

            if len(cases) != 0:
                self.entity_cases[e] = cases.pop()

            pbar.update(pbar.currval+1)
        pbar.finish()

    def get_cls_file_to_case_paths(self, cls):
        """Given a node, return the paths the lead monotonically up to case"""

        parent_labels = {
            link['dst_type'].label
            for link in cls._pg_links.values()
        }
        return (
            path
            for path in self.file_to_case_paths
            if path and path[0] in parent_labels
        )

    def _cache_relevant_nodes(self):
        """The file documents will need to be pruned to only the nodes that
        are relevant to the file. Here we cache all of the nodes
        encountered when traversing to all related cases.

        """

        if self.relevant_nodes:
            return

        self.relevant_nodes = {}

        files = list(self.nodes_labeled(self.file_labels))
        pbar = self.pbar('Caching file paths: ', len(files))

        for f in files:
            paths = self.get_cls_file_to_case_paths(f)
            self.relevant_nodes[f] = self.walk_paths(f, paths, whole=True)
            pbar.update(pbar.currval+1)

        pbar.finish()

    def _cache_annotations(self):
        if not self.annotations:
            # cache what nodes are annotations
            self.annotations = list(self.nodes_labeled('annotation'))
        if self.annotation_entities:
            # we've already cached the related entities
            return
        if not self.annotations:
            # there aren't any entities to relate
            self.annotation_entities = {}
            log.warn('No annotations found in the cached database!')
            return
        pbar = self.pbar('Caching annotations: ', len(self.annotations))
        self.annotation_entities = {}
        for a in self.annotations:
            for n in self.G.neighbors(a):
                if n not in self.annotation_entities:
                    self.annotation_entities[n] = {}
                a_doc = self.denormalize_annotation(a)
                self.annotation_entities[n][a.node_id] = a_doc
            pbar.update(pbar.currval+1)
        pbar.finish()

    def _cache_popular_neighbor(self, node, neighbors, labels):
        if node not in self.popular_nodes:
            self.popular_nodes[node] = {}
        self.popular_nodes[node][labels] = {
            n for n in neighbors if n.label in labels}
        return self.popular_nodes[node][labels]

    def _cache_data_categories(self):
        """Looking up the files that are classified in each data_type is a
        common computation.  Here we cache this information for easy retrieval.

        ..note::
            data_type is renamed data_category, viz.
            https://jira.opensciencedatacloud.org/browse/PGDC-1472

        """

        if len(self.data_categories):
            return

        log.info('Caching data categories')
        for data_category in self.nodes_labeled('data_type'):
            category = data_category._props['name']
            self.data_categories[category] = self.remove_bam_index_files(
                set(self.walk_path(data_category, ['data_subtype', 'file'])))

        # New files have 'data_category' as a property
        for file_ in self.nodes_labeled(self.file_labels):
            category = file_._props.get('data_category')
            if not category:
                continue
            self.data_categories.setdefault(category, set()).add(file_)

    def _cache_experimental_strategies(self):
        """Looking up the files that are classified in each
        experimental_strategy is a common computation.  Here we cache
        this information for easy retrieval.

        """

        if len(self.experimental_strategies):
            return

        log.info('Caching experitmental strategies')
        for exp_strat in self.nodes_labeled('experimental_strategy'):
            strategy = exp_strat._props['name']
            self.experimental_strategies[strategy] = set(self.walk_path(
                exp_strat, ['file']))

        # New files have 'experimental_strategy' as a property
        for file_ in self.nodes_labeled(self.file_labels):
            strategy = file_._props.get('experimental_strategy')
            if not strategy:
                continue
            self.experimental_strategies.setdefault(strategy, set()).add(file_)

    def _cache_existing_data_types(self):
        """The last version of this code imported a hard coded list and called
        it DATA_TYPES.  This function replaces this hardcoded nested
        dict by pulling it from the graph at runtime.

        :returns:
            The data types in the graph in the format
            ``{'data_type.name': ['data_subtype.name']}``

        """

        with self.g.session_scope():
            return {
                data_type.name: [
                    subtype.name
                    for subtype in data_type.data_subtypes
                ] for data_type in self.g.nodes(md.DataType).all()
            }
