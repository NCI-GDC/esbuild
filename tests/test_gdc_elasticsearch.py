from base import TestBase
from elasticsearch import Elasticsearch
from gdcdatamodel.models import File, Demographic
from elasticsearch.exceptions import AuthorizationException
from esbuild.gdc_elasticsearch import GDCElasticsearch
from prelude import create_prelude_nodes

import es_fixtures
import json
import os

from base import (
    PG_HOST,
    PG_USER,
    PG_PASSWORD,
    PG_DATABASE,
)


class GDCElasticsearchTest(TestBase):

    @classmethod
    def setUpClass(cls):
        super(GDCElasticsearchTest, cls).setUpClass()
        cls.delete_all_nodes()
        create_prelude_nodes(cls.g)

    def setUp(self):
        super(GDCElasticsearchTest, self).setUp()
        self.delete_non_prelude_nodes()
        es_fixtures.insert(self.g)
        self.add_file_nodes()

        os.environ["PG_HOST"] = PG_HOST
        os.environ["PG_USER"] = PG_USER
        os.environ["PG_PASS"] = PG_PASSWORD
        os.environ["PG_NAME"] = PG_DATABASE
        os.environ["ELASTICSEARCH_HOST"] = "localhost"

        self.es = Elasticsearch("localhost")
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

    def make_gdc_es(self):
        return GDCElasticsearch(index_base="gdc_es_test")

    def get_es_indices(self):
        return self.es.indices.get_aliases().keys()

    def test_basic_es_generate(self):
        gdces = self.make_gdc_es()
        gdces.go()
        self.assertEqual(len(self.get_es_indices()), 1)
        # also verify that the to_delete file is not in the index and
        # got deleted
        with self.g.session_scope():
            self.assertIsNone(self.g.nodes(File).get('file2'))
            self.assertFalse(self.es.exists(index="gdc_es_test",
                                            doc_type="file",
                                            id="file2"))

    def test_unexpected_properties(self):
        with self.g.session_scope() as s:
            demographic = self.g.nodes(Demographic).one()
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

        gdces = self.make_gdc_es()
        gdces.go()
        self.assertEqual(len(self.get_es_indices()), 1)

    def test_doesnt_delete_file_with_derived_files(self):
        gdces = self.make_gdc_es()
        with self.g.session_scope():
            to_delete_file = self.g.nodes(File).ids("file2").one()
            derived_file = self.get_fuzzed_node(File, state="live")
            to_delete_file.derived_files = [derived_file]
        gdces.go()
        self.assertEqual(len(self.get_es_indices()), 1)
        # verify that th eto_delete file did not get deleted
        with self.g.session_scope():
            self.assertEqual(self.g.nodes(File).get('file2').file_name,
                             "a_file_to_be_deleted.txt")

    def test_old_index_cleanup(self):
        for i in range(7):
            gdces = self.make_gdc_es()
            gdces.go()
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
