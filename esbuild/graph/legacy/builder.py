# -*- coding: utf-8 -*-
"""
esbuild.graph.legacy.builder
----------------------------------

Defines :class:`LegacyGraphIndexBuilder` for building the graph index
for Legacy projects.

"""

from ..common.builder import (
    GraphIndexBuilder,
)

from .mappings import (
    LegacyESMapper,
)


class LegacyGraphIndexBuilder(GraphIndexBuilder):

    mapper = LegacyESMapper

    case_to_file_paths = [
        ['file'],
        ['sample', 'aliquot', 'file'],
        ['sample', 'portion', 'file'],
        ['sample', 'portion', 'analyte', 'aliquot', 'file'],
        ['biospecimen_supplement'],
        ['clinical_supplement'],
    ]

    # Types of nodes to be treated as files
    file_labels = [
        'file',
        'biospecimen_supplement',
        'clinical_supplement',
    ]
