# -*- coding: utf-8 -*-
"""
esbuild.graph.common.cache
----------------------------------

Functionality to create a multiprocessing manager to share cached
graph information between processes

"""

import logging
import itertools
import networkx as nx

from collections import namedtuple
from cdisutils.log import get_logger
from gdcdatamodel import models as md
from psqlgraph import Edge, Node
from sqlalchemy.orm import joinedload
from types import StringTypes

from esbuild.graph.common import (
    util,
)

logger = get_logger(__name__)
logger.setLevel(logging.INFO)

def to_node_id(node_or_node_id):
    """Returns the node_id of a node if provided a Node, elif it's a
    string, assume it's a node_id and return that

    """

    if hasattr(node_or_node_id, 'node_id'):
        return node_or_node_id.node_id

    elif isinstance(node_or_node_id, StringTypes)
        return node_or_node_id.node_id

    else:
        raise TypeError("Not sure how to convert {} to node_id"
                        .format(node_or_node_id))


class CachingOptions(object):

    """An object to hold the options required to hold the required options
    to cache information to a SharedGraph object

    """

    def __init__(
            self,
            case_to_file_paths,
            redacted_but_not_suppressed,
            differentiated_edges,
            file_labels,
            unindexed_by_property,
            omitted_projects,
            index_file_extensions,
            possible_associated_entites,
            supplement_regexes,
    ):
        """Options required to cache information to SharedGraph object

        :param list case_to_file_paths:
            specifies all possible paths from case entities to file
            entities. is a list of lists of string labels

        :param list redacted_but_not_suppressed:
            Suppress entities with redaction annotation if
            entity.annotation.category not in this list

        :param file_labels:
            Node labels that should be treated as properties

        :param unindezed_by_property:
            Filter nodes out if their properties are a superset of any of
            the dictionaries listed here by label

        """

        self.case_to_file_paths = case_to_file_paths
        self.redacted_but_not_suppressed = redacted_but_not_suppressed
        self.differentiated_edges = differentiated_edges
        self.file_labels = file_labels
        self.unindexed_by_property = unindexed_by_property
        self.omitted_projects = omitted_projects
        self.index_file_extensions = index_file_extensions
        self.possible_associated_entites = possible_associated_entites
        self.supplement_regexes = supplement_regexes

        self.file_to_case_paths = util.reverse_paths(
            self.case_to_file_paths, 'case')


class CachedGraph(object):
    """Represents the shared information for esbuild workers. This data
    includes a cached version of the psqlgraph graph in NetworkX as
    well as more aggresively cached things, e.g. relationships.

    """

    def __init__(self, psqlgraph_driver, caching_options):

        # Injected Dependencies
        self.psqlgraph_driver = psqlgraph_driver
        self.graph = nx.Graph()
        self.caching_options = caching_options

        # Cached information
        self.nodes = {}
        self.experimental_strategies = {}
        self.data_categories = {}
        self.popular_nodes = {}
        self.cases = None
        self.projects = None
        self.relevant_nodes = None
        self.annotations = None
        self.entity_cases = None
        # Different from ``self.data_categories`` in that it's a
        # replacement for a hardcoded dict of data_type, data_subtype
        # relationships.  This is populated by
        # ``self._cache_existing_data_types()``
        self.existing_data_types = {}

    def iter_database_edges(self):
        """Returns an iterable of edges to load from the database.

        Eagerly (with join) loads the source and destination of the edge.

        """

        return itertools.chain(*[
            self.psqlgraph_driver.edges(subclass)
            .options(joinedload(subclass.src))
            .options(joinedload(subclass.dst))
            .yield_per(int(1e5))
            for subclass in Edge.__subclasses__()
        ])

    @staticmethod
    def warning(*args, **kwargs):
        """Log a warning to logger and statsd"""

        util.log_warning(logger, *args, **kwargs)

    @staticmethod
    def error(*args, **kwargs):
        """Log a error to logger and statsd"""

        util.log_error(logger, *args, **kwargs)

    def get_edge(self, src, dst):
        """Returns any information stored about the edge between two nodes"""

        return self.graph[src][dst]

    def get_suppressed_children(self, redacted):
        """Get the children of a redacted node"""

        to_suppress = []
        if redacted.label == "case":
            paths = self.caching_options.case_to_file_paths
        else:
            paths = [
                util.truncate_path(p, redacted.label)
                for p in self.caching_options.case_to_file_paths if p
            ]

        logger.info("suppressing %s, which is redacted directly.", redacted)
        to_suppress.append(redacted)

        logger.info("Walking down towards file with paths %s", paths)
        extra = self.walk_paths(redacted, paths, whole=True)

        logger.info("Found %s other things to suppress by walking from %s",
                    extra, redacted)
        to_suppress.extend(extra)

        return to_suppress

    def get_node_in_graph(self, node_or_node_id):
        return self.nodes[node_or_node_id(node_or_node_id)]

    def neighbors(self, node_or_node_id):
        """Get the neighbors of a given node"""

        node = self.get_node_in_graph(node_or_node_id)


    def suppressed_nodes(self):
        """
        Find all nodes that need to be suppressed due to redactions.
        """

        redactions = [
            a for a in self.nodes_labeled('annotation')
            if a.classification == "Redaction" and
            a.category not in self.caching_options.redacted_but_not_suppressed
        ]

        to_suppress = []
        for redaction in redactions:
            redacted_list = self.graph.neighbors(redaction)

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
            logger.info("suppressing %s, the redaction annotation.", redaction)
            to_suppress.append(redaction)

        return to_suppress

    def is_unindexed_case(self, node):
        return (
            node.label == 'case'
            and not list(self.neighbors_labeled(node, 'project', 1))
        )

    def is_node_indexed(self, node):
        """Returns false if the node is not supposed to be indexed.

        """

        if self.is_unindexed_case(node):
            logger.info('Node not indexed (case not indexed): %s', node)
            return False

        # Check for non-indexed files
        if not self.is_file_indexed(node):
            logger.info('Node not indexed (file not indexed): %s', node)
            return False

        # Check for non-indexed files
        if self.is_node_unindexed_by_property(node):
            logger.info('Node not indexed (not by property): %s', node)
            return False

        # Check for omitted_projects
        if self.is_omitted_project_or_neighbor_case(node):
            logger.info('Node not indexed (omitted project ): %s', node)
            return False

        return True

    def remove_unindexed_nodes_from_graph(self):
        logger.info('Selecting entities to be removed from cache...')

        removed_nodes = [
            node for node in self.graph.nodes()
            if not self.is_node_indexed(node)
        ]

        logger.info("Removing %s nodes from cache", len(removed_nodes))
        self.graph.remove_nodes_from(removed_nodes)

        logger.info("Finding and removing suppressed nodes")
        suppressed = self.suppressed_nodes()

        logger.info("Removing %s suppressed nodes", len(suppressed))
        self.graph.remove_nodes_from(suppressed)

    def cache_database(self):
        """Load the database into memory and remember only edge labels that we
        will need to distinguish later.

        """

        with self.psqlgraph_driver.session_scope() as session:

            pbar = util.get_pbar(
                'Caching Database: ',
                self.psqlgraph_driver.edges().count())

            for edge in self.iter_database_edges():
                pbar.update(pbar.currval+1)

                src, dst = edge.src, edge.dst

                triple = (src.label, edge.label, dst.label)
                needs_differentiation = (
                    triple in self.caching_options.differentiated_edges
                )

                if triple == ("file", "data_from", "file"):
                    # for files that are "data_from" other files, the
                    # centers and aliquots of the source files count
                    # as neighbors of the dst files
                    for center in edge.src.centers:
                        self.graph.add_edge(dst, center)
                    for aliquot in edge.src.aliquots:
                        self.graph.add_edge(dst, aliquot)

                if edge.label == 'relates_to' and edge.__dst_class__ == 'Case':
                    pass

                elif needs_differentiation and edge._props:
                    self.graph.add_edge(
                        src,
                        dst,
                        label=edge.label,
                        props=edge._props
                    )

                elif needs_differentiation and not edge._props:
                    self.graph.add_edge(src, dst, label=edge.label)

                elif edge._props:
                    self.graph.add_edge(src, dst, props=edge._props)

                else:
                    self.graph.add_edge(src, dst)

            session.expunge_all()
            pbar.finish()

        # Prune graph
        logger.info('Cached {} nodes'.format(self.graph.number_of_nodes()))
        self.remove_unindexed_nodes_from_graph()

        # Aggressively cache relationships, nodes by type, traversals, etc.
        self._cache_all()

    def _cache_all(self):
        """Create key value maps to cache nodes by label, by path, etc.

        """

        self._cache_node_ids()
        self._cache_existing_data_types()
        self._cache_experimental_strategies()
        self._cache_data_categories()
        self._cache_relevant_nodes()
        self._cache_entity_cases()
        self._cache_cases()
        self._cache_projects()

    def cache_node_ids(self):
        """Create a hashtable from node_id to node in the graph"""

        self.nodes = {
            node.node_id: node
            for node in self.graph.nodes_iter()
        }

    def _cache_projects(self):
        """Save a list of all Project nodes"""

        if not self.projects:
            logger.info('Caching projects...')
            self.projects = list(self.nodes_labeled('project'))

    def _cache_cases(self):
        """Save a list of all Case nodes"""

        if not self.cases:
            logger.info('Caching cases...')
            self.cases = list(self.nodes_labeled('case'))

    def _cache_entity_cases(self):
        """Cache the related Case nodes for each file"""

        if self.entity_cases:
            return

        entities = list(self.nodes_labeled(
            self.caching_options.possible_associated_entites))
        pbar = util.get_pbar('Caching entity cases: ', len(entities))
        self.entity_cases = {}

        for entity in entities:
            if entity.label == "case":
                # if the associated entity is a case, it's case is
                # just itself. this is kindy of sketchy but w/e
                self.entity_cases[entity] = entity
                continue

            paths = (
                util.truncate_path(path, entity.label)
                for path in  self.caching_options.file_to_case_paths
            )
            cases = self.walk_paths(entity, paths)

            if len(cases) > 1:
                self.warning(
                    'Entity associated with > 1 case',
                    '{}: Found {} cases'.format(entity, len(cases)),
                    tags=["entity:{}".format(entity)],
                )
                return

            if len(cases) != 0:
                self.entity_cases[entity] = cases.pop()

            pbar.update(pbar.currval+1)
        pbar.finish()

    def _cache_relevant_nodes(self):
        """The file documents will need to be pruned to only the nodes that
        are relevant to the file. Here we cache all of the nodes
        encountered when traversing to all related cases.

        """

        if self.relevant_nodes:
            return

        self.relevant_nodes = {}

        files = list(self.nodes_labeled(self.caching_options.file_labels))
        pbar = util.get_pbar('Caching file paths: ', len(files))

        for file_ in files:
            paths = util.get_file_to_case_paths(
                file_, self.caching_options.file_to_case_paths)
            self.relevant_nodes[file_] = self.walk_paths(
                file_, paths, whole=True)
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

        logger.info('Caching data categories')
        for data_category in self.nodes_labeled('data_type'):
            category = data_category._props['name']

            self.data_categories[category] = util.remove_index_files(
                set(self.walk_path(data_category, ['data_subtype', 'file'])),
                self.caching_options.index_file_extensions,
            )

        # New files have 'data_category' as a property
        for file_ in self.nodes_labeled(self.caching_options.file_labels):
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

        logger.info('Caching experitmental strategies')
        for exp_strat in self.nodes_labeled('experimental_strategy'):
            strategy = exp_strat._props['name']
            self.experimental_strategies[strategy] = set(self.walk_path(
                exp_strat, ['file']))

        # New files have 'experimental_strategy' as a property
        for file_ in self.nodes_labeled(self.caching_options.file_labels):
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

        with self.psqlgraph_driver.session_scope():
            return {
                data_type.name: [
                    subtype.name
                    for subtype in data_type.data_subtypes
                ] for data_type in self.psqlgraph_driver.nodes(md.DataType)
            }

    ###################################################################
    #                         Graph functions
    ###################################################################

    def nodes_labeled(self, labels):
        """Returns an iterator over the edges in the graph with label `label`

        """

        labels = tuple(labels) if hasattr(labels, '__iter__') else (labels,)
        for node, _ in self.graph.nodes_iter(data=True):
            if node.label in labels:
                yield node

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
                    node, self.graph.neighbors(node), labels)
            else:
                neighbors = self.popular_nodes[node][labels]
        else:
            temp = self.graph.neighbors(node)
            if len(temp) > 200:
                neighbors = self._cache_popular_neighbor(node, temp, labels)
            else:
                neighbors = {n for n in temp if n.label in labels}

        count = 0
        for neighbor in neighbors:
            count += 1
            yield neighbor

        if expected is not None and count != expected:
            self.warning(
                "{}: unexpected no. of '{}' neighbors".format(node, labels),
                '{}: {} != {} (expected)'.format(node, count, expected),
                tags=["{}:{}".format(node.label, node.node_id)])

    @staticmethod
    def is_harmonized_file(node):
        return (
            node.label == 'file' and
            node._sysan.get('source', '').endswith('_alignment')
        )

    def is_old_supplement_file(self, node):
        return (
            node.label == 'file'
            and any(
                pattern.match(node._props.get('file_name', ''))
                for pattern in self.caching_options.supplement_regexes
            )
        )

    def is_file_indexed(self, node):
        """Returns false if node is a file that is not supposed to be indexed.

        """

        # This function should only be for files
        if node.label not in self.caching_options.file_labels:
            return True

        # Remove files with no acl entries
        if len(node.acl) == 0:
            logger.info('File not indexed (empty acl): %s', node)
            return False

        # Skip old versions of supplement xmls
        if self.is_old_supplement_file(node):
            logger.info('File not indexed (deprecated supplement): %s', node)
            return False

        # Skip old representation of harmonized files
        if self.is_harmonized_file(node):
            logger.info('File not indexed (deprecated harmonized file): %s', node)
            return False

        # Is file to_delete
        if node.system_annotations.get("to_delete"):
            return False

        # Is file not live
        if node.state not in ['live', 'submitted']:
            logger.info('File not indexed (bad state: %s): %s', node, node.state)
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

        # Check if project is not released
        for project in projects:
            if project.released is not True:
                logger.info('Omitting %s, project %s not released',
                            node, project)
                return True

        # Check project and program against omitted_projects
        for program_name in program_names:
            for project_code in project_codes:
                is_omitted = (
                    (program_name, project_code) in
                    self.caching_options.omitted_projects
                )
                if is_omitted:
                    return True

        return False

    def is_node_unindexed_by_property(self, node):
        """Returns True if node should be removed because its properties are
        specified in self.unindexed_by_property as an indication to
        remove it from the index.

        """

        filters = self.caching_options.unindexed_by_property.get(node.label, [])

        for filter_ in filters:
            is_subset = not set(filter_.items()) - set(node._props.items())

            if is_subset:
                return True

        return False

    ###################################################################
    #                        Path functions
    ###################################################################

    def neighbors(self, node):
        """Return the neighbors of given node"""

        return self.graph.neighbors(node)

    def walk_path(self, node, path, whole=False):
        """Given a list of strings, treat it as a path, and yield the end of
        possible traversals.  If `whole` is true, return every node
        along the traversal.

        """

        if path:
            for neighbor in self.neighbors_labeled(node, path[0]):
                if whole or (len(path) == 1 and path[0] == neighbor.label):
                    yield neighbor

                for node in self.walk_path(neighbor, path[1:], whole):
                    yield node

    def walk_paths(self, node, paths, whole=False):
        """Given a list of paths, yield the result of walking each path. If
        `whole` is true, return every node along each traversal.

        """

        return {
            n for n in itertools.chain(*[
                self.walk_path(node, path, whole=whole)
                for path in paths if path
            ])
        }
