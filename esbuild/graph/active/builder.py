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

from gdcdatamodel.models import(
    ReadGroup
)

from ..common.builder import (
    GraphIndexBuilder,
)

from .mappings import (
    ActiveESMapper,
)


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
                          categories={'data_file', 'analysis'}):
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
        recurse = (
            child._dictionary['category'] in categories
            and child.label not in visited
        )

        if recurse:
            subtree_paths_to_file(child, paths, visited+[child.label])

    return paths


def get_case_to_file_paths():
    """Since the Active index has more complicated paths from case to
    file, this is an attempt not to hard code them.  See module doc.

    """

    case_to_aliquot = [
        ['sample', 'aliquot'],
        ['sample', 'portion', 'analyte', 'aliquot'],
    ]

    readgroup_subtree = list_product(
        [[ReadGroup.label]],
        subtree_paths_to_file(ReadGroup)
    )

    case_to_file_paths = [
        ['file'],
    ]

    case_to_file_paths += list_product(case_to_aliquot, readgroup_subtree)

    return case_to_file_paths


class ActiveGraphIndexBuilder(GraphIndexBuilder):

    mapper = ActiveESMapper
    case_to_file_paths = get_case_to_file_paths()

    def denormalize_file(self, node, ptree):
        doc = (super(ActiveGraphIndexBuilder, self)
               .denormalize_file(node, ptree))

        self.add_file_analysis(node, doc)
        self.add_file_downstream_analysis(node, doc)

        return doc

    def get_file_index_files(self, node):
        """Given a file, return any neighboring index files"""
        return [
            n for n in list(self.get_child_with_category(node, 'index_file'))
            if self.is_index_file(n)
        ]

    def get_parent_with_category(self, node, category):
        """returns iterable of neighors from outbound edges with category

        """

        return self.neighbors_labeled(node, [
            l['dst_type'].label for l in node._pg_links.values()
            if l['dst_type']._dictionary['category'] == category
        ])

    def get_child_with_category(self, node, category):
        """returns iterable of neighors from inbound edges with category

        """

        return self.neighbors_labeled(node, [
            l['src_type'].label for l in node._pg_backrefs.values()
            if l['src_type']._dictionary['category'] == category
        ])

    def add_file_analysis(self, node, doc):
        """Add the 'analysis' that produced the current file.

        """

        analyses = list(self.get_parent_with_category(node, 'analysis'))

        if analyses:
            # Add the first analysis
            analysis = analyses.pop()
            analysis_doc = self._get_base_doc(analysis)
            self.add_analysis_input_files(analysis, analysis_doc)
            self.add_analysis_metadata(analysis, analysis_doc)
            doc['analysis'] = analysis_doc

        # If there are remaining analysis, record a warning and skip
        if analyses:
            self.warning(
                "Multiple analysis on {}".format(node),
                "{} has multiple analyses {}, this is unexpected."
                .format(node, analyses),
                tags=["file_id:{}".format(node.node_id)],
            )

    def add_file_downstream_analysis(self, node, doc):
        """Add the 'analysis' that produced the current file.

        """

        analyses = list(self.get_child_with_category(node, 'analysis'))

        if analyses:
            # Add the first downstream analyisis
            analysis = analyses.pop()
            analysis_doc = self._get_base_doc(analysis)
            self.add_analysis_output_files(analysis, analysis_doc)
            doc['downstream_analysis'] = analysis_doc

        # If there are remaining analysis, record a warning and skip
        if analyses:
            self.warning(
                "Multiple downstream analysis on {}".format(node),
                ("{} has multiple downstream analyses {}, "
                 "this is unexpected.").format(node, analyses),
                tags=["file_id:{}".format(node.node_id)],
            )

    def add_analysis_input_files(self, node, doc):
        """For a given analysis node, add the input_files to the doc.

        """

        input_files = self.get_parent_with_category(node, 'data_file')
        input_file_docs = map(self.get_simple_file_doc, input_files)

        if input_file_docs:
            doc.setdefault('input_files', []).extend(input_file_docs)

    def add_analysis_output_files(self, node, doc):
        """For a given analysis node, add the output_files to the doc.

        """

        output_files = self.get_child_with_category(node, 'data_file')
        output_file_docs = map(self.get_simple_file_doc, output_files)

        if output_file_docs:
            doc.setdefault('output_files', []).extend(output_file_docs)

    def add_analysis_metadata(self, node, doc):
        """For a given analysis node, add the metadata to the doc.

        """

        metadata_doc = {}
        self.add_analysis_metadata_read_groups(node, metadata_doc)

        if metadata_doc:
            doc['metadata'] = metadata_doc

    def add_analysis_metadata_read_groups(self, node, doc):
        """For a given analysis node, add read_groups to the metadata subdoc.

        """

        parent_files = self.get_parent_with_category(node, 'data_file')
        read_groups = [
            rg
            for f in parent_files
            for rg in self.neighbors_labeled(f, 'read_group')
        ]

        if read_groups:
            doc['read_groups'] = [
                self._get_base_doc(rg)
                for rg in read_groups
            ]

    def get_simple_file_doc(self, node):
        """Create a simple file doc for {input,output}_files

        """

        doc = {}
        self.add_data_type(node, doc)
        for dst in self.neighbors_labeled(node, 'data_subtype'):
            doc['data_type'] = dst['name']

        doc['file_id'] = node.node_id
        doc['file_name'] = node._props.get('file_name')
        doc['file_size'] = node._props.get('file_size')
        doc['data_format'] = self.get_data_format(node)

        return doc
