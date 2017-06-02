# -*- coding: utf-8 -*-
"""esbuild.graph.legacy.mappings
----------------------------------

Defines the Elasticsearch mappings for the main GDC graph index.

.. _hierarchy-format:

    The hierarchies defined below will contain a tuple (CORR, name),
    where CORR is the expected correlation and ``name`` is what key to
    nest the child documents under

"""

from gdcdatamodel import models  # noqa

from ..common.mappings import (
    ESMapper,
)


class LegacyESMapper(ESMapper):

    @staticmethod
    def index_settings():

        settings = super(LegacyESMapper, LegacyESMapper).index_settings()

        settings['settings']['analysis'] = {
            'filter': {
                "edge_ngram": {
                    "side": "front",
                    "max_gram": 20,
                    "min_gram": 2,
                    "type": "edge_ngram"
                }
            },
            "analyzer": {
                "lowercase_keyword": {
                    "tokenizer": "keyword",
                    "filter": ["lowercase"],
                }
            }

        }

        return settings


get_file_es_mapping = LegacyESMapper.get_file_es_mapping
get_case_es_mapping = LegacyESMapper.get_case_es_mapping
get_project_es_mapping = LegacyESMapper.get_project_es_mapping
get_annotation_es_mapping = LegacyESMapper.get_annotation_es_mapping
index_settings = LegacyESMapper.index_settings
