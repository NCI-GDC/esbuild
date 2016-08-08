# -*- coding: utf-8 -*-
"""esbuild.graph.active.builder
----------------------------------

Defines :class:`ActiveGraphIndexBuilder` for building the graph index
for Active projects.

Strategy to add analysis and file types:

- An attempt to balance abstraction by creating the traversals from a
known point to limit wandering through the graph.  Currently the
subgraph that includes active data_file and analysis nodes is isolated
by removing read_group, so we create a readgroup subtree and append
all paths generated in the readgroup subtree to paths from aliquot to
case - jsm (2016-03-22)

- we don't need a special path for harmonized files because they get
tied to the relevant aliquots during cache_database

"""
from cdisutils.log import get_logger

import logging

from gdcdatamodel.models import(
    ReadGroup
)

from ..common.builder import (
    GraphIndexBuilder,
)

from .mappings import (
    ActiveESMapper,
)


log = get_logger("graph_active_index")
log.setLevel(level=logging.INFO)


def list_product(roots, subtrees):
    """Appends each subtree to each root.

    It's not quite a cartesian product, example::

        roots = [['a', 'b'], ['-', '#']]
        subtrees = [range(0, 2), range(2, 4), range(4, 8)]
        list(list_product(roots, subtrees))

        [['a', 'b', 0, 1],
         ['a', 'b', 2, 3],
         ['a', 'b', 4, 5, 6, 7],
         ['-', '#', 0, 1],
         ['-', '#', 2, 3],
         ['-', '#', 4, 5, 6, 7]]

    """
    return [root + subtree for root in roots for subtree in subtrees]


def subtree_paths_to_file(cls, paths=None, visited=None,
                          categories={'data_file', 'analysis'},
                          exclude_paths_through=set()):
    """Recurse through all child nodes in categories :param:`categories`
    and return all paths from :param:`cls` to destination child file
    nodes.

    :param cls: The originating node class
    :param categories: The set of categories through which recursion is allowed

    """

    visited = visited if visited is not None else []
    paths = paths if paths is not None else []

    if cls._dictionary['category'] == 'data_file':
        paths.append(visited)

    for backref in cls._pg_backrefs.values():
        child = backref['src_type']

        should_recur = (
            child._dictionary['category'] in categories and
            child.label not in visited and
            child.label not in exclude_paths_through
        )

        if should_recur:
            subtree_paths_to_file(
                child,
                paths,
                visited=visited+[child.label],
                exclude_paths_through=exclude_paths_through
            )

    return paths


class ActiveGraphIndexBuilder(GraphIndexBuilder):

    mapper = ActiveESMapper

    """
    Since the Active index has more complicated paths from case to
    file, this is an attempt not to hard code them.  See module doc.
    """

    # Skip any paths that traverse through nodes in
    # ``exclude_paths_through``.
    #
    # In the index, AlignedReads were associated with two aliquots
    # because they go through the Alignment Cocleaning
    # Workflow. However, they should have edges directly back to a
    # single SubmittedAlignedReads that goes back to a single
    # aliquot. They should only be associated with this aliquot.
    #
    # The impact is that the user can not filter properly on the
    # sample types, e.g. tumor versus normal as it returns all of the
    # AlignedReads.
    #
    # The solution applied here is to simply remove paths through
    # specific nodes and rely on the shortcut edges when traversing to
    # Read Groups.
    #
    # See PGDC-2349 for details.
    exclude_paths_through = {
        'alignment_cocleaning_workflow',
    }

    # Filter nodes out if their properties are a superset of any of
    # the dictionaries listed here by label
    unindexed_by_property = {
        "annotation": [
            {"status": "Rescinded"},
        ],
    }

    case_to_aliquot = [
        ['sample', 'aliquot'],
        ['sample', 'portion', 'analyte', 'aliquot'],
    ]

    readgroup_subtree = list_product(
        [[ReadGroup.label]],
        subtree_paths_to_file(
            ReadGroup,
            exclude_paths_through=exclude_paths_through
        )
    )

    aliquot_to_copy_number_paths = [
        ['submitted_tangent_copy_number',
         'copy_number_liftover_workflow',
         'copy_number_segment'],
    ]

    case_to_file_paths = [
        ['biospecimen_supplement'],
        ['clinical_supplement'],
    ]

    case_to_copy_number_paths = list_product(
        case_to_aliquot, aliquot_to_copy_number_paths)

    case_to_file_paths += list_product(case_to_aliquot, readgroup_subtree)
    case_to_file_paths += case_to_copy_number_paths

    file_labels = GraphIndexBuilder.node_labels_by_category([
        'data_file',
        'index_file',
    ])

    # Specify which analysis nodes get which types of
    # `analysis.metadata` {'metadata type': set({'labels'})}
    analysis_metadata = {
        'read_groups': {
            'alignment_workflow',
            'alignment_cocleaning_workflow',
        }
    }

    # Do not create file docs for archives
    file_labels.remove('archive')

    # Pre-calculate the paths to read_group from each type of file
    file_to_read_group_paths = {}
    for path in readgroup_subtree:
        file_to_read_group_paths.setdefault(path[-1], []).append(path[-2::-1])

    def denormalize_file(self, node, ptree):
        doc = (super(ActiveGraphIndexBuilder, self)
               .denormalize_file(node, ptree))

        self.add_file_analysis(node, doc)
        self.add_file_downstream_analyses(node, doc)
        return doc

    def get_file_index_files(self, node):
        """Given a file, return any neighboring index files"""
        return [
            n for n in list(self.get_child_with_category(node, 'index_file'))
            if self.is_index_file(n)
        ]

    def get_parent_with_category(self, node, category):
        """returns iterable of neighors from outbound edges with category"""

        labels = [
            l['dst_type'].label for l in node._pg_links.values()
            if l['dst_type']._dictionary['category'] == category
        ]

        return self.neighbors_labeled(node, labels)

    def get_child_with_category(self, node, category):
        """returns iterable of neighors from inbound edges with category"""

        labels = [
            l['src_type'].label for l in node._pg_backrefs.values()
            if l['src_type']._dictionary['category'] == category
        ]

        return self.neighbors_labeled(node, labels)

    def add_file_analysis(self, node, doc):
        """Add the 'analysis' that produced the current file"""

        analyses = list(self.get_parent_with_category(node, 'analysis'))

        if analyses:
            # Add the first analysis
            analysis = analyses.pop()
            analysis_doc = self._get_base_doc(analysis)
            read_groups = self.get_file_read_groups(node)
            self.add_analysis_input_files(analysis, analysis_doc)
            self.add_analysis_metadata(analysis, read_groups, analysis_doc)
            doc['analysis'] = analysis_doc

        # If there are remaining analysis, record a warning and skip
        if analyses:
            self.warning(
                "Multiple analysis on {}".format(node),
                "{} has multiple analyses {}, this is unexpected."
                .format(node, analyses),
                tags=["file_id:{}".format(node.node_id)],
            )

    def add_file_downstream_analyses(self, node, doc):
        """Add the 'analysis' that produced the current file"""

        analyses = list(self.get_child_with_category(node, 'analysis'))

        for analysis in analyses:
            analysis_doc = self._get_base_doc(analysis)
            self.add_analysis_output_files(analysis, analysis_doc)
            doc.setdefault('downstream_analyses', []).append(analysis_doc)

    def add_analysis_input_files(self, node, doc):
        """For a given analysis node, add the input_files to the doc"""

        input_files = [
            f for f in self.get_parent_with_category(node, 'data_file')
            if not self.is_node_hidden(f)
        ]
        input_file_docs = map(self.get_simple_file_doc, input_files)

        if input_file_docs:
            doc.setdefault('input_files', []).extend(input_file_docs)

    def add_analysis_output_files(self, node, doc):
        """For a given analysis node, add the output_files to the doc"""

        output_files = [
            f for f in self.get_child_with_category(node, 'data_file')
            if not self.is_node_hidden(f)
        ]
        output_file_docs = map(self.get_simple_file_doc, output_files)

        if output_file_docs:
            doc.setdefault('output_files', []).extend(output_file_docs)

    def add_analysis_metadata(self, analysis, read_groups, doc):
        """For a given analysis node, add the metadata to the doc"""

        metadata_doc = {}

        if analysis.label in self.analysis_metadata['read_groups']:
            self.add_analysis_metadata_read_groups(read_groups, metadata_doc)

        if metadata_doc:
            doc['metadata'] = metadata_doc

    def add_analysis_metadata_read_groups(self, read_groups, doc):
        """For a given analysis node, add read_groups to the metadata subdoc"""

        read_group_docs = []

        for read_group in read_groups:
            read_group_doc = self._get_base_doc(read_group)

            read_group_qc_docs = self.get_read_group_qc_docs(read_group)
            if read_group_qc_docs:
                read_group_doc['read_group_qcs'] = read_group_qc_docs

            read_group_docs.append(read_group_doc)

        if read_group_docs:
            doc['read_groups'] = read_group_docs

    def get_read_group_qc_docs(self, read_group):
        """Returns a list of documents for Read Group QCs"""

        read_group_qc_docs = []
        rg_qcs = self.neighbors_labeled(read_group, 'read_group_qc')
        for read_group_qc in rg_qcs:
            read_group_qc_docs.append(self._get_base_doc(read_group_qc))

        return read_group_qc_docs

    def get_file_read_groups(self, node):
        """Given a data_file node, traverse up the tree to read_groups

        :returns: set of read_groups

        """

        paths = self.file_to_read_group_paths.get(node.label, [])
        return set(self.walk_paths(node, paths))

    def get_analysis_read_groups(self, node):
        """Given a analysis node, traverse up the tree to read_groups:

        :returns: set of read_groups

        """

        return {
            path
            for file_ in self.get_parent_with_category(node, 'data_file')
            for path in self.get_file_read_groups(file_)
        }

    def get_simple_file_doc(self, node):
        """Create a simple file doc for {input,output}_files

        """

        doc = self._get_base_doc(node)

        self.add_data_category(node, doc)
        self.add_file_access(node, doc)

        doc['data_format'] = self.get_data_format(node)

        for dst in self.neighbors_labeled(node, 'data_subtype'):
            doc['data_type'] = dst['name']

        return doc

    def get_file_associated_entities(self, node):
        """Returns a list of entities that are 'associated' with a file"""

        entities = (super(ActiveGraphIndexBuilder, self)
                    .get_file_associated_entities(node))

        # Add entities via read_group
        entities += [
            entity
            for rg in self.get_file_read_groups(node)
            for entity in
            self.neighbors_labeled(rg, self.possible_associated_entites)
        ]

        # Add entities with one step through a data_file
        entities += [
            entity
            for parent in self.get_parent_with_category(node, 'data_file')
            for entity in
            self.neighbors_labeled(parent, self.possible_associated_entites)
        ]

        # Copy number paths
        cnv_paths = [
            path[-2::-1] for path in
            list_product([['aliquot']], self.aliquot_to_copy_number_paths)
        ]
        entities += [
            entity for entity in self.walk_paths(node, cnv_paths)
        ]

        return list(set(entities))
