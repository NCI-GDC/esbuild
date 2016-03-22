# -*- coding: utf-8 -*-
"""
esbuild.graph.const
----------------------------------

Defines the constants for building GDC Elasticsearch mappings

"""

from addict import Dict
from psqlgraph import Node

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

# ======================================================================
# Types

STRING = {
    'index': 'not_analyzed',
    'type': 'string',
}

LONG = {
    'type': 'long',
}

INTEGER = {
    'type': 'integer',
}

# ======================================================================
# Denormalization configuration options

FLATTEN = [
    'tag',
    'platform',
    'data_format',
    'experimental_strategy',
]

# ======================================================================
# Index settings

MULTIFIELDS = {
    'project': [
        'code',
        'disease_type',
        'name',
        'primary_site',
    ],
    'annotation': [
        'annotation_id',
        'entity_id',
    ],
    'files': [
        'file_id',
        'file_name',
    ],
    'case': [
        'case_id',
        'submitter_id',
    ],
}


def index_settings():
    return {
        "settings": {
            "analysis": {
                "analyzer": {
                    "id_search": {
                        "tokenizer": "whitespace",
                        "filter": ["lowercase"],
                        "type": "custom"
                    },
                    "id_index": {
                        "tokenizer": "whitespace",
                        "filter": [
                            "lowercase",
                            "edge_ngram"
                        ],
                        "type": "custom"
                    }
                },
                "filter": {
                    "edge_ngram": {
                        "side": "front",
                        "max_gram": 20,
                        "min_gram": 2,
                        "type": "edge_ngram"
                    }
                }
            }
        }
    }


# ======================================================================
# Utility functions

def _get_header(source):
    header = Dict()
    header.dynamic = 'strict'
    header._all.enabled = False
    header._source.compress = True
    header._source.excludes = ["__comment__"]
    header._id = {'path': '{}_id'.format(source)}
    return header


def _get_es_type(_type):
    if long in _type or int in _type:
        return 'long'
    elif float in _type:
        return 'double'
    else:
        return 'string'


def _munge_properties(source, nested=True):

    # Get properties from schema
    cls = Node.get_subclass(source)
    assert cls, 'No model for {}'.format(source)
    properties = cls.get_pg_properties()
    fields = properties.keys()

    # Add id to document
    id_name = '{}_id'.format(source)
    doc = Dict({id_name: STRING})

    # Add all properties to document
    for field in fields:
        _type = _get_es_type(properties[field] or [])
        # assign the type
        doc[field] = {'type': _type}
        if str(_type) == 'string':
            doc[field]['index'] = 'not_analyzed'
    return doc


def multifield(name):
    doc = Dict()
    doc.type = 'string'

    # Raw
    doc.fields.raw.index = 'not_analyzed'
    doc.fields.raw.store = 'yes'
    doc.fields.raw.type = 'string'

    # Analyzed
    doc.fields.analyzed.index = "analyzed"
    doc.fields.analyzed.index_analyzer = "id_index"
    doc.fields.analyzed.search_analyzer = "id_search"
    doc.fields.analyzed.type = "string"

    # Search
    doc.fields.search.index = 'analyzed'
    doc.fields.search.analyzer = 'id_search'
    doc.fields.search.type = 'string'
    return Dict({name: doc})


def flatten_data_type(root):
    """Compress nested data_type and sub_type into flat key/value

    ..note::
        data_type is renamed data_category, viz.
        https://jira.opensciencedatacloud.org/browse/PGDC-1472

    ..note::
        data_subtype is renamed data_type, viz.
        https://jira.opensciencedatacloud.org/browse/PGDC-1472

    """
    root.data_type = STRING

    # data_type is renamed data_category, viz.
    # https://jira.opensciencedatacloud.org/browse/PGDC-1472
    root.data_category = STRING


def patch_file_timestamps(doc):
    doc.properties.uploaded_datetime = LONG
    doc.properties.published_datetime = LONG
    return doc


def nested(source):
    return Dict(type='nested', properties=_munge_properties(source))


def add_multifields(doc, source):
    for key in MULTIFIELDS[source]:
        doc.properties.update(multifield(key))


def patch_project(doc):
    doc.pop('code')
