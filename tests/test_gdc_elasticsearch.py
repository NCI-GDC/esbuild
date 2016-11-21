# -*- coding: utf-8 -*-
"""
Tests the GDC Elasticsearch interaction for active and legacy
indices.

"""

from elasticsearch import Elasticsearch
from gdcdatamodel.models import File, Demographic
from elasticsearch.exceptions import AuthorizationException
from bin.gdc_datarelease import GDCDataRelease
from esbuild.export.es_upload import GDCElasticsearch
from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder
from psqlgraph import PsqlGraphDriver
from unittest import TestCase

import data
import json
import os
import tempfile
import shutil


from conftest import (
    PG_HOST,
    PG_USER,
    PG_PASSWORD,
    PG_DATABASE,
    _graph,
)


class GDCElasticsearchTest(object):

    def setUp(self):
        data.insert(_graph)

        os.environ["PG_HOST"] = PG_HOST
        os.environ["PG_USER"] = PG_USER
        os.environ["PG_PASS"] = PG_PASSWORD
        os.environ["PG_NAME"] = PG_DATABASE

        os.environ["ELASTICSEARCH_HOST"] = "localhost"

        os.environ["SAVE_DIR"] = tempfile.mkdtemp()

        self.es = Elasticsearch(os.environ['ELASTICSEARCH_HOST'])
        self.delete_all_indices()

    def delete_all_indices(self):
        indices = self.es.indices.get_aliases()
        for index, info in indices.items():
            if info.get("aliases"):
                for alias in info["aliases"].keys():
                    self.es.indices.delete_alias(index=index, name=alias)
            self.es.indices.delete(index)

    def tearDown(self):
        super(GDCElasticsearchTest, self).tearDown()
        self.delete_all_indices()

        # if os.path.exists(os.environ['SAVE_DIR']):
            # shutil.rmtree(os.environ['SAVE_DIR'])


    def make_gdc_es(self):
        raise NotImplementedError()

    def get_es_indices(self):
        return self.es.indices.get_aliases().keys()

    def test_basic_es_generate(self):
        gdces, denorm_docs  = self.make_gdc_es()
        gdces.save_to_elasticsearch(index_base="gdc_es_test", denorm_docs=denorm_docs)
        self.assertEqual(len(self.get_es_indices()), 1)
        # also verify that the to_delete file is not in the index and
        # got deleted
        with _graph.session_scope():
            self.assertFalse(self.es.exists(index="gdc_es_test",
                                            doc_type="file",
                                            id="to-delete-file"))

    def test_unexpected_properties(self):
        with _graph.session_scope() as s:
            demographic = _graph.nodes(Demographic).one()
            s.execute("""
            UPDATE node_demographic
            SET _props = :props
            WHERE node_id = :id
            """, {
                'id': demographic.node_id,
                'props': json.dumps(dict(demographic.props, **{
                    'fake_property': True,
                }))
            })

        gdces, denorm_docs = self.make_gdc_es()
        gdces.save_to_elasticsearch(index_base="gdc_es_test", denorm_docs=denorm_docs)
        self.assertEqual(len(self.get_es_indices()), 1)

    def test_doesnt_delete_file_with_derived_files(self):
        gdces, denorm_docs = self.make_gdc_es()
        with _graph.session_scope():
            to_delete_file = _graph.nodes(File).ids("to-delete-file").one()
            derived_file = data.fuzzed(File, state="live")
            to_delete_file.derived_files = [derived_file]

        gdces.save_to_elasticsearch(index_base="gdc_es_test", denorm_docs=denorm_docs)
        self.assertEqual(len(self.get_es_indices()), 1)

        # verify that the to_delete file did not get deleted
        with _graph.session_scope():
            self.assertEqual(_graph.nodes(File).get('to-delete-file').file_name,
                             "a_file_to_be_deleted.txt")

    def test_old_index_cleanup(self):
        for i in range(7):
            gdces, denorm_docs = self.make_gdc_es()
            gdces.save_to_elasticsearch(index_base="gdc_es_test", denorm_docs=denorm_docs)

        indices = self.get_es_indices()

        # running the index build seven times should delete indicies 1 and 2
        self.assertEqual(set(indices), {"gdc_es_test_3",
                                        "gdc_es_test_4",
                                        "gdc_es_test_5",
                                        "gdc_es_test_6",
                                        "gdc_es_test_7"})
        for i in xrange(3, 6):
            with self.assertRaises(AuthorizationException):
                self.es.indices.stats('gdc_es_test_'+str(i))


class GDCActiveElasticsearchTest(GDCElasticsearchTest, TestCase):

    def make_gdc_es(self):
        g = GDCDataRelease(converter_class=ActiveGraphIndexBuilder)
        _, denorm_docs = g.save_to_disk(g.active)
        return g, denorm_docs


class GDCLegacyElasticsearchTest(GDCElasticsearchTest, TestCase):

    def make_gdc_es(self):
        g = GDCDataRelease(converter_class=LegacyGraphIndexBuilder)
        _, denorm_docs = g.save_to_disk(g.legacy)
        return g, denorm_docs

