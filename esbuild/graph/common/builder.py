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
from functools32 import lru_cache
from gdcdatamodel import models as md
from multiprocessing import cpu_count, Queue, Process
from psqlgraph import Node, Edge
from sqlalchemy.orm import joinedload

import logging
import random
import re

from esbuild.graph.common import (
    util,
)

from esbuild.graph.common.index import (
    MemoryGraphIndex,
    DiskGraphIndex,
)

from esbuild.graph.common.cache import (
    CachingOptions,
    CachedGraph,
    CacheManager,
)

from .mappings import (
    ONE_TO_MANY,
    ONE_TO_ONE,
)

log = get_logger("graph_index")
log.setLevel(level=logging.INFO)


def build_worker(builder, case_in_q, result_q):
    """TODO: docstring

    """

    while True:

        case = case_in_q.get()
        if case is None:
            return log.info('No more work for builder %s', builder)

        try:
            result_q.put(builder.denormalize_case(case))
        except Exception as exception:
            log.exception(exception)
            result_q.put(exception)


def start_worker_pool(builders, cases):
    """Setup a process pool and schedule work to the case_in_q"""

    case_in_q, result_q = Queue(), Queue()

    pool = [
        Process(
            target=build_worker,
            args=(builder, case_in_q, result_q)
        ) for builder in builders
    ]

    # Schedule work
    for case in cases:
        case_in_q.put(case)

    # Put an end of work marker for all workers
    for _ in range(len(builders)):
        case_in_q.put(None)

    # Start all of the processes
    for process in pool:
        process.start()

    return case_in_q, result_q, pool


def build_index(builder_class, psqlgraph_driver_args, cases=None,
                threads=cpu_count()):
    """TODO: docstring

    """

    index = DiskGraphIndex('~/indexes')

    # caching_options = builder_class.get_caching_options()
    # cache = CachedGraph(
    #     caching_options=caching_options,
    #     psqlgraph_driver_args=psqlgraph_driver_args,
    # )
    # cache.cache_database()
    # builder = builder_class(cache, index)
    # return builder.denormalize_all()

    # Create managed cache
    caching_options = builder_class.get_caching_options()

    manager = CacheManager()
    manager.start()
    cache = manager.new_cached_graph(
        caching_options=caching_options,
        psqlgraph_driver_args=psqlgraph_driver_args,
    )
    cache.cache_database()

    # Map work to worker processes
    cases = cases or cache.get_cases()
    builders = [builder_class(cache) for _ in range(threads)]
    _, result_q, pool = start_worker_pool(builders, cases)

    pbar = util.get_pbar('Denormalizing cases ', len(cases))

    # Collect results
    while index.case_doc_count() < len(cases):
        try:
            if result_q.qsize() > 20:
                log.warning("Primary thread overworked! %d", result_q.qsize())
        except NotImplementedError:
            pass  #  on Mac OSX because of broken sem_getvalue()

        result = result_q.get()
        if isinstance(result, Exception):
            raise result

        case_doc, file_docs, annotation_docs = result

        # Collect docs
        index.add_case_doc(case_doc)
        map(index.add_annotation_doc, annotation_docs)
        map(index.add_file_doc, file_docs)

        pbar.update(pbar.currval+1)
    pbar.finish()

    for process in pool:
        process.join()

    # Create project docs serially
    project_docs = builders[0].denormalize_projects()
    map(index.add_project_doc, project_docs)

    return index


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

    - Josh (jsmiller@uchicago.edu)

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

    # Filter nodes out if their properties are a superset of any of
    # the dictionaries listed here by label
    unindexed_by_property = {
        # "label": [{"key1": "value1", "key2": "value2"}]
    }

    # Suppress entities with redaction annotation if
    # entity.annotation.category not in this list
    redacted_but_not_suppressed = ['Subject withdrew consent']

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

    leaf_nodes = ['center', 'tissue_source_site']

    # Omit entities from these projects
    omitted_projects = {
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
    flatten = {
        'tag': 'name',
        'platform': 'name',
        'data_format': 'name',
        'data_subtype': 'name',
        'experimental_strategy': 'name',
        'data_level': 'name',
    }

    # The edges below will maintain labels in the in memory graph,
    # all others will be discarded
    differentiated_edges = [
        ('file', 'member_of', 'archive'),
        ('archive', 'member_of', 'file'),
        ('file', 'describes', 'case'),
        ('case', 'describes', 'file'),
        ('file', 'related_to', 'file'),
    ]

    possible_associated_entites = [
        'portion',
        'aliquot',
        'case',
        'slide',
    ]

    index_file_extensions = {
        '.bai',
        '.tbi',
    }

    # The following attributes must be overridden
    case_to_file_paths = None
    mapper = None
    file_labels = None

    required_attrs = [
        'mapper',
        'case_to_file_paths',
        'file_labels',
    ]

    def __init__(self, cached_graph, index):
        """Walks the graph to produce elasticsearch json documents.

        :param cached_graph: Instance of CachedGraph (post .cached_database())
        :param index: Instance of GraphIndex

        """

        self.index = index
        self.cache = cached_graph

        # verify required attributes are set
        for required_attr in self.required_attrs:
            if getattr(self, required_attr) is None:
                raise NotImplementedError(
                    '{} must set {}'
                    .format(self.__class__.__name__, required_attr)
                )

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

        self.file_to_case_paths = util.reverse_paths(
            self.case_to_file_paths, 'case')

    @classmethod
    def get_caching_options(cls):
        """Returns caching options for this builder"""

        return CachingOptions(
            case_to_file_paths=cls.case_to_file_paths,
            redacted_but_not_suppressed=cls.redacted_but_not_suppressed,
            differentiated_edges=cls.differentiated_edges,
            file_labels=cls.file_labels,
            unindexed_by_property=cls.unindexed_by_property,
            omitted_projects=cls.omitted_projects,
            index_file_extensions=cls.index_file_extensions,
            possible_associated_entites=cls.possible_associated_entites,
            supplement_regexes=cls.supplement_regexes,
        )

    @staticmethod
    def warning(*args, **kwargs):
        """Log a warning to logger and statsd"""

        util.log_warning(log, *args, **kwargs)

    @staticmethod
    def error(*args, **kwargs):
        """Log a error to logger and statsd"""

        util.log_error(log, *args, **kwargs)

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

        for child in self.cache.neighbors(node):
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

        corr, _ = mapping[node.label]['corr']
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
    #                          cases
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

        files = self.cache.walk_paths(node, self.case_to_file_paths)
        files = self.remove_index_files(files)
        files = self.remove_hidden_nodes(files)

        return files

    def remove_index_files(self, files):
        """Partial function for util.remove_index_files"""

        return util.remove_index_files(files, self.index_file_extensions)

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

    def get_relevant_annotations(self, case_doc, relevant_ids):
        """Return a flat list of annotations who describe entities in
        :param:`relevant_ids`

        """

        return [
            annotation
            for file_ in case_doc['files']
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
        case['files'] = self.get_case_file_docs(node, ptree, files)

        # Flatten ids we visited in traversal to create a list of ids
        # that are relevant to this case (including the case's id)
        relevant_ids = self.get_relevant_ids(node, visited_ids)

        # Pull out the annotations from the case
        annotations = self.get_relevant_annotations(case, relevant_ids)

        # Set the annotation's case id in-place
        for annotation in annotations:
            annotation['case_id'] = node.node_id

        # Create copy of annotations to return and add properties
        # (note: this is *not* in-place)
        returned_annotations = map(copy, annotations)
        self.patch_annotations(returned_annotations, node, project)

        # Copy the files with all cases, do this because the nested
        # version of each file is about to have its file['cases'] set
        # to the current case, but we want to return a list of files
        # *without* all but one case pruned form file['cases']
        returned_files = deepcopy(case['files'])

        self.patch_case_files(node, case)
        self.validate_case(node, case)

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

    def patch_case_files(self, case, case_doc):
        """Trim other cases from files in-place"""

        for nested_file in case_doc['files']:
            nested_file['cases'] = [
                _case
                for _case in nested_file['cases']
                if _case['case_id'] == case.node_id
            ]
            nested_file.pop('annotations', None)
            nested_file.pop('associated_entities', None)

    def get_exp_strats(self, files):
        """Get the set of experimental_strategies where intersection of the
        set `files` and the set of files that relate to that
        experimental_strategy is non-null

        """

        exp_strats = self.cache.get_experimental_strategies()
        for exp_strat, file_list in exp_strats.iteritems():
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
        data_categories = self.cache.get_data_categories()

        for data_category, file_list in data_categories.iteritems():
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
        """For each sample.aliquot, reconstruct entire path

        """

        samples = case.get('samples', [])
        correct_aliquots = set()
        for sample in samples:
            for portion in sample.get('portions', []):
                for analyte in portion.get('analytes', []):
                    for aliquot in analyte.get('aliquots', []):
                        correct_aliquots.add(aliquot['aliquot_id'])

        for sample in samples:
            sample['portions'] = sample.get('portions', [])

            # Get all aliquots connected to samples
            sample_aliquots = sample.pop('aliquots', [])
            for aliquot in sample_aliquots:
                if aliquot['aliquot_id'] not in correct_aliquots:
                    sample['portions'].append({
                        'analytes': [{
                            'aliquots': [aliquot]
                        }]})

            for portion in sample['portions']:
                portion['analytes'] = portion.get('analytes', [])

                # Get aliquots connected to portions
                portion_aliquots = portion.pop('aliquots', [])
                for aliquot in portion_aliquots:
                    # Put aliquot under analyte
                    if aliquot['aliquot_id'] not in correct_aliquots:
                        portion['analytes'].append([{
                            'aliquots': [aliquot]}])

    def patch_project(self, project_doc):
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
            formats = list(self.cache.neighbors_labeled(node, 'data_format'))

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

        auto_neighbors = [
            n for n in dict(self.ftree_mapping['file']).keys()
            if n not in ['archive', 'portion', 'file']
        ]
        for neighbor in set(self.cache.neighbors_labeled(node, auto_neighbors)):
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

        return util.is_index_file(node, self.index_file_extensions)

    def get_file_index_files(self, node):
        """Given a file, return any neighboring index files"""
        return [
            n for n in list(self.cache.neighbors_labeled(node, 'file'))
            if self.cache.get_edge(node, n).get("label") == "related_to"
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
            n for n in list(self.cache.neighbors_labeled(node, 'file'))
            if self.cache.get_edge(node, n).get("label") == "related_to"
            and not self.is_index_file(n)
        ]

        related_files += list(self.cache.neighbors_labeled(node, metadata_labels))

        for related_file in related_files:
            rf_doc = self._get_base_doc(related_file, include_id=False)
            rf_doc['file_id'] = related_file.node_id

            # Data types
            data_subtypes = self.cache.neighbors_labeled(
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
            for archive in set(self.cache.neighbors_labeled(node, 'archive')):
                edge = self.cache.get_edge(node, archive)
                if edge.get('label') != 'member_of':
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

        for archive in set(self.cache.neighbors_labeled(node, 'archive')):
            if 'archive' in doc:
                return self.warning(
                    "Duplicate archives for {}".format(node),
                    ("File {} has more than archive.".format(node)),
                    tags=["file_id:{}".format(node.node_id)],
                )

            is_skipped_legacy_edge = (
                node.label == 'file' and
                self.cache.get_edge(node, archive).get('label') != 'member_of'
            )

            if not is_skipped_legacy_edge:
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
        cached_data_categories = self.cache.get_data_categories()

        data_categories = [
            data_category
            for data_category, files in cached_data_categories.items()
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

        relevant = self.cache.get_relevant_nodes(node)
        if not relevant:
            log.warn('No relevant cases for %s', node)
            return []

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

    @lru_cache(maxsize=int(2**20))
    def get_node_annotation_docs(self, node):
        """Returns the annotation docs for all annotations relevant to this
        node

        """

        annotations = self.cache.neighbors_labeled(node, 'annotation')

        return [
            self.denormalize_annotation(annotation)
            for annotation in annotations
        ]

    def add_annotations(self, node, relevant, doc):
        """Given a file node, aggregate all of the annotations from a pruned
        case tree and insert them at the root level of the file
        document.

        """

        annotations = doc.pop('annotations', [])

        for relevant_node in relevant:
            annotations.extend(self.get_node_annotation_docs(relevant_node))

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

        return list(self.cache.neighbors_labeled(
            node, self.possible_associated_entites))

    def add_file_associated_entities(self, node, doc, case_id):
        docs = []
        entities = self.get_file_associated_entities(node)

        for entity in entities:

            case = self.cache.get_entity_case(entity)
            if not case:
                # Skip, the cases is likely missing because it is omitted
                continue

            subdoc = {
                'entity_type': entity.label,
                'entity_id': entity.node_id,
                'case_id': case.node_id
            }

            entity_submitter_id = entity._props.get('submitter_id')
            if entity_submitter_id:
                subdoc['entity_submitter_id'] = entity_submitter_id

            docs.append(subdoc)

        if docs:
            doc['associated_entities'] = docs

    ###################################################################
    #                       Project summaries
    ###################################################################

    def denormalize_project(self, p):
        """Summarize a project.

        """

        doc = self._get_base_doc(p)

        # Get programs
        program = self.cache.neighbors_labeled(p, 'program')[0]
        log.info('Program: {}'.format(program))
        doc['program'] = self._get_base_doc(program)

        # project_id <- program.name-project.code
        self.patch_project(doc)

        log.info('Finding cases')
        cases = list(self.cache.neighbors_labeled(p, 'case'))
        log.info('Got {} cases'.format(len(cases)))

        # Get files
        log.info('Getting files')
        files = set()
        case_files = {}
        for case in cases:
            case_files[case] = self.remove_index_files(
                self.cache.walk_paths(case, self.case_to_file_paths))
            files = files.union(case_files[case])

        # filter files
        files = {
            f for f in files
            if not self.is_node_hidden(f)
        }

        log.info('Got {} files from {} cases'.format(
            len(files), len(case_files)))

        # Get experimental strategies
        experimental_strategies = self.cache.get_experimental_strategies()
        exp_strat_summaries = []
        for exp_strat in experimental_strategies:
            log.info('exp_strat: {}'.format(exp_strat))
            exp_files = (experimental_strategies[exp_strat] & files)

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

        cached_data_categories = self.cache.get_data_categories()
        for data_category in cached_data_categories.keys():
            log.info('data_category: {}'.format(data_category))
            dt_files = (cached_data_categories[data_category] & files)

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

        case_docs, ann_docs, file_docs = [], {}, {}
        if not cases:
            cases = self.cache.get_cases()
        pbar = util.get_pbar('Denormalizing cases ', len(cases))
        for n in cases:
            pa, fi, an = self.denormalize_case(n)
            case_docs.append(pa)

            for a in an:
                if a['annotation_id'] not in ann_docs:
                    ann_docs[a['annotation_id']] = a

            for f in fi:
                util.upsert_file_into_dict(file_docs, f)

            pbar.update(pbar.currval+1)
        pbar.finish()
        return case_docs, file_docs.values(), ann_docs.values()

    def denormalize_projects(self, projects=None):
        """If projects is not specified, denormalize all projects in
        the graph.  If projects is specified, denormalize only those
        given.

        """

        if not projects:
            projects = self.cache.get_projects()

        project_docs = []
        pbar = util.get_pbar('Denormalizing projects ', len(projects))
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
        entities = self.cache.neighbors(node)

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
        return ann_doc

    def denormalize_all(self):
        """Return an entire index worth of case, file, annotation, and
        project documents

        """

        case_docs, file_docs, annotation_docs = self.denormalize_cases()
        project_docs = self.denormalize_projects()

        map(self.index.add_case_doc, case_docs)
        map(self.index.add_file_doc, file_docs)
        map(self.index.add_annotation_doc, annotation_docs)
        map(self.index.add_project_doc, project_docs)

        return self.index

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
        for data_category in self.cache.get_existing_data_types():
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
                '{}: {} != {}'.format(
                    node.node_id, len(case['files']),
                    case['summary']['file_count']),
                tags=["case_id:{}".format(node.node_id)],
            )

        # Check for keys that are in the doc but not in the mapping
        self.validate_against_mapping(case, self.case_es_mapping)
