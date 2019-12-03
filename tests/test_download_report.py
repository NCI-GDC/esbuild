import pytest
from unittest import TestCase
from datetime import datetime
from elasticsearch import Elasticsearch
from esbuild.reports.download_report import DownloadStatsIndexBuilder

import uuid
from tests import data
from tests.data import get_node_id
from tests.conftest import ES_HOST, ES_PORT, clear_graph_database

from gdcdatamodel.models import (
    File,
    FileReport,
    Aliquot,
    Tag,
    ExperimentalStrategy,
    Platform,
    Project,
)


@pytest.fixture(scope='class')
def cls_with_graph(request, graph):
    request.cls.graph = graph


@pytest.mark.usefixtures('cls_with_graph')
class DownloadStatsIndexBuilderTest(TestCase):

    def setUp(self):
        super(DownloadStatsIndexBuilderTest, self).setUp()

        clear_graph_database(self.graph)

        # TODO maybe think about a better / more general way to do this
        FileReport.metadata.create_all(self.graph.engine)

        data.insert(self.graph)

        self.es = Elasticsearch(hosts=[ES_HOST], port=ES_PORT)
        self.index_name = "download_stats_test"
        self.builder = DownloadStatsIndexBuilder(
            graph=self.graph,
            es=self.es,
            index_name=self.index_name
        )

        self.builder.create_es_index()

    def tearDown(self):
        self.es.indices.delete(index=self.index_name)

        with self.graph.session_scope() as session:
            session.execute(FileReport.__table__.delete())

        clear_graph_database(self.graph)

    def create_file(self):
        file = File(
            node_id=str(uuid.uuid4()),
            file_name="test_file.txt",
            file_size=1000,
            md5sum="fake_md5sum",
            state="live",
        )
        return file

    def create_download(self, file, size=None, username='', country='US'):
        if not size:
            size = file.file_size
        download = FileReport(
            node_id=file.node_id,
            ip='127.0.0.1',
            country_code=country,
            streamed_bytes=size,
            timestamp=datetime.now(),
            username=username,
        )
        self.graph.current_session().merge(download)

    def test_basic_index_build(self):
        with self.graph.session_scope():
            aliquot = (self.graph.nodes(Aliquot)
                             .ids(get_node_id("aliquot-1")).one())
            tag = self.graph.nodes(Tag).props(name="snv").one()
            strat = self.graph.nodes(ExperimentalStrategy).props(name="RNA-Seq").one()
            platform = self.graph.nodes(Platform).props(name="Illumina HiSeq").one()
            file = self.create_file()
            self.create_download(file, username='FOO')
            file.aliquots = [aliquot]
            file.tags = []
            file.tags = [tag]
            file.experimental_strategies = [strat]
            file.platforms = [platform]
        with self.graph.session_scope():
            brca = self.graph.nodes(Project).props(code="BRCA").one()
            self.builder.go(projects=[brca])
        self.es.indices.refresh(index=self.index_name)
        result = self.es.get(
            index=self.index_name,
            doc_type=self.builder.doc_type,
            id="TCGA-BRCA"
        )["_source"]
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["tags"][0]["tag"], "snv")
        self.assertEqual(result["tags"][0]["size"], 1000)
        self.assertEqual(result["user_access_types"][0]["user_access_type"],
                         "authenticated_protected")  # acls is [], so it's protected
        self.assertEqual(result["user_access_types"][0]["size"], 1000)
        self.assertEqual(result["platforms"][0]["platform"], "Illumina HiSeq")
        self.assertEqual(result["platforms"][0]["size"], 1000)
        self.assertEqual(result["countries"][0]["country"], "US")
        self.assertEqual(result["countries"][0]["size"], 1000)
        self.assertEqual(result["continents"][0]["continent"], "North America")
        self.assertEqual(result["continents"][0]["size"], 1000)
        # confirm that we can update once index exists
        with self.graph.session_scope():
            self.create_download(file, country='CA', size=500)
        with self.graph.session_scope():
            brca = self.graph.nodes(Project).props(code="BRCA").one()
            self.builder.go(projects=[brca])
        result = self.es.get(
            index=self.index_name,
            doc_type=self.builder.doc_type,
            id="TCGA-BRCA"
        )["_source"]
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["tags"][0]["tag"], "snv")
        self.assertEqual(result["tags"][0]["size"], 1500)
        self.assertEqual([c for c in result["countries"]
                          if c["country"] == "CA"][0]["size"],
                         500)
        self.assertEqual([c for c in result["user_access_types"]
                          if c["user_access_type"] == "anonymous"][0]["size"],
                         500)
