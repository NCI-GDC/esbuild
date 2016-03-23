# -*- coding: utf-8 -*-
"""
esbuild.graph.active.builder
----------------------------------

Defines :class:`ActiveGraphIndexBuilder` for building the graph index
for Active projects.

"""

from ..common.builder import (
    GraphIndexBuilder,
)

from .mappings import (
    file_tree,
    case_tree,
    annotation_tree,
    get_case_es_mapping,
)


class ActiveGraphIndexBuilder(GraphIndexBuilder):

    ptree_mapping = {'case': case_tree.to_dict()}
    ftree_mapping = {'file': file_tree.to_dict()}
    atree_mapping = {'annotation': annotation_tree.to_dict()}

    case_es_mapping = get_case_es_mapping()

    case_to_file_paths = [
        ['file'],
        ['sample', 'aliquot', 'file'],
        ['sample', 'portion', 'file'],
        ['sample', 'portion', 'analyte', 'aliquot', 'file'],
        # we don't need a special path for harmonized files
        # because they get tied to the relevant aliquots
        # during cache_database
    ]
