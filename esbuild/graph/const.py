# -*- coding: utf-8 -*-
"""
esbuild.graph.const
----------------------------------

Defines the constants for building GDC Elasticsearch mappings

"""

# These values specify the multiplicity of the relationship from
# parent to child.
ONE_TO_ONE = '__one_to_one__'
ONE_TO_MANY = '__one_to_many__'

TOP_LEVEL_IDS = [
    'sample',
    'portion',
    'analyte',
    'aliquot',
    'slide',
]
