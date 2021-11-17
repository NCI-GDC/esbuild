# -*- coding: utf-8 -*-
"""
Setup esbuild tests
"""

import logging
import os
import time
from collections import namedtuple

import yaml
import psqlgraph
import pytest
from datadog import statsd
from gdcdictionary import gdcdictionary
from gdcdatamodel import models
from gdcdatamodel.viz import create_graphviz
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import ElasticsearchException
from indexd_test_utils import (
    indexd_client,
    indexd_server,
    create_indexd_tables,
    index_driver,
    alias_driver,
    auth_driver,
    setup_indexd_test_database,
    indexd_admin_user,
)
from psqlgraph import PsqlGraphDriver, Node, Edge, mocks

from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.utils import ReleaseHelper, get_index_names
from tests import data, es_data

# ======================================================================
# Test Settings

Index = namedtuple('Index', 'cases, files, annotations, projects')

TEST_DIR = os.path.dirname(os.path.realpath(__file__))
DATA_DIR = os.path.join(TEST_DIR, 'data')

PG_HOST = 'localhost'
PG_USER = 'test'
PG_PASS = 'test'
PG_NAME = 'automated_test'
ES_HOST = 'localhost'
ES_PORT = 9200

# ======================================================================
# Util

logger = logging.getLogger("conftest")
logger.setLevel(logging.DEBUG)


def clear_graph_database(pg_driver):
    """Clear graph from database"""

    edge_tables = Edge.get_subclass_table_names()
    node_tables = Node.get_subclass_table_names()
    tables = ['_voided_nodes', '_voided_edges'] + [
        t for t in edge_tables + node_tables
        if t not in {'edge_edge', 'node_node'}
    ]

    with pg_driver.engine.begin() as conn:
        conn.execute('TRUNCATE {}'.format(', '.join(tables)))


def cleanup_nodes(pg_driver, nodes):
    with pg_driver.session_scope() as sxn:
        for n in nodes:
            nobj = pg_driver.nodes().get(n.node_id)
            if nobj:
                sxn.delete(nobj)


def drop_all(engine):
    models.versioned_nodes.Base.metadata.drop_all(engine)
    models.submission.Base.metadata.drop_all(engine)
    models.FileReport.metadata.drop_all(engine)
    psqlgraph.base.ORMBase.metadata.drop_all(engine)
    psqlgraph.base.VoidedBase.metadata.drop_all(engine)


def create_all(engine):
    psqlgraph.create_all(engine)
    models.versioned_nodes.Base.metadata.create_all(engine)
    models.submission.Base.metadata.create_all(engine)
    models.FileReport.metadata.create_all(engine)


@pytest.fixture(scope='session')
def graph():
    pg_conn = PsqlGraphDriver(
        host=os.getenv('PG_HOST', PG_HOST),
        user=os.getenv('PG_USER', PG_USER),
        password=os.getenv('PG_PASS', PG_PASS),
        database=os.getenv('PG_NAME', PG_NAME),
    )

    drop_all(pg_conn.engine)
    create_all(pg_conn.engine)

    yield pg_conn

    drop_all(pg_conn.engine)


@pytest.fixture
def create_indexd_documents(indexd_client):
    def _inner(records):
        docs = []
        # Insert indexd data:
        for record in records:
            record = dict(record)
            urls = record['urls']
            # NOTE: 'file_state' is stored as 'state' in indexd.
            # However, this is not important as esbuild does not pay attention to 'file_state'
            # and it is removed from resulting elasticsearch documents. See PRTL-2109
            urls_metadata = {
                urls[0]: {'state': record.get('file_state', 'validated')}
            }
            if "gencode_version" not in record:
                record["gencode_version"] = "neutral"
            doc = indexd_client.create(
                did=record['did'],
                acl=record['acl'],
                hashes={'md5': record['md5sum']},
                size=record['file_size'],
                file_name=record.get('file_name', None),
                urls=urls,
                metadata=record,
                urls_metadata=urls_metadata,
            )
            docs.append(doc)
        return docs
    return _inner


@pytest.fixture
def init_indexd(indexd_client, create_indexd_documents):

    create_indexd_documents(data.INDEXD)

    return indexd_client


class TestError(Exception):
    """Monkeypatch exception for testinting exception handling"""
    pass


def raise_test_error(*args, **kwargs):
    """For monkeypatching to test exception handling"""

    raise TestError('{} {}'.format(args, kwargs))


def render_database(pg_driver):
    """Save PDF graph of test suite data"""

    with pg_driver.session_scope():
        dot = create_graphviz(pg_driver.nodes())
        dot.render('test_suite_data.gv')


# ======================================================================
# Fixtures

@pytest.fixture(autouse=True)
def environment(monkeypatch):
    """Monkeypatch the script environment"""

    monkeypatch.setenv('ES_HOST', ES_HOST)
    monkeypatch.setenv('ES_USER', '')
    monkeypatch.setenv('ES_PASSWORD', '')
    monkeypatch.setenv('PG_HOST', PG_HOST)
    monkeypatch.setenv('PG_USER', PG_USER)
    monkeypatch.setenv('PG_PASS', PG_PASS)
    monkeypatch.setenv('PG_NAME', PG_NAME)


@pytest.fixture(scope="module")
def pg_driver(graph):
    """Add all test data to the database.

    Attempt to render a PDF representation of the test suite.

    """

    clear_graph_database(graph)

    data.insert(graph)

    try:
        render_database(graph)
    except Exception as exc:
        logger.error('Failed to write updated database viz files: %s', exc)

    yield graph

    clear_graph_database(graph)


@pytest.fixture(scope='module')
def ro_pg_driver(pg_driver):
    with pg_driver.engine.connect() as conn:
        ro_user = 'ro_test'
        ro_pass = 'ro_test'
        commands = [
            # "create user {} with password '{}'".format(ro_user, ro_pass),
            'grant connect on database {} to {}'.format(PG_NAME, ro_user),
            'grant select on all tables in schema public to {}'.format(ro_user),
        ]
        for cmd in commands:
            conn.execute(cmd)

    ro_pg_conn = PsqlGraphDriver(
        host=os.getenv('PG_HOST', PG_HOST),
        user=ro_user,
        password=ro_pass,
        database=os.getenv('PG_NAME', PG_NAME),
    )

    yield ro_pg_conn

    with pg_driver.engine.connect() as conn:
        commands = [
            'revoke all on all tables in schema public from {}'.format(ro_user),
            'revoke all on database {} from {}'.format(PG_NAME, ro_user),
        ]

        for cmd in commands:
            conn.execute(cmd)


@pytest.fixture(scope='session')
def graph_factory():
    graph_globals = {
        'properties': {
            'project_id': 'TCGA-BRCA',
            'state': 'released',
            'batch_id': 1,
            'experimental_strategy': 'WXS',
        }
    }
    factory = mocks.GraphFactory(models, gdcdictionary, graph_globals)

    return factory


# ======================================================================
# Elasticsearch test index


def get_all_indices(es):
    return (
        # closed indices
        list(es.cluster.state()['blocks'].get('indices', {}).keys()) +
        # opened indices:
        list(es.indices.stats()['indices'].keys())
    )


def cleanup_indices(es, indices=None):
    """
    Cleanup Elasticsearch cluster
    :param es: ES client
    :param indices: list of indices to delete
    """
    for _ in range(10):
        try:
            es.cluster.health(wait_for_status='yellow')
            break
        except ElasticsearchException:
            time.sleep(0.1)
    else:
        # Default timeout is 30 seconds, 10 iterations ~ 5 minutes
        raise Exception('Elasticsearch cluster offline after 5 minutes')

    if not indices:
        indices = get_all_indices(es)

    for index in indices:
        es.indices.delete(index, ignore=(404, 400))

    es.indices.refresh()


@pytest.fixture(scope="session")
def index_types():
    return ["annotation", "case", "file", "project"]


@pytest.fixture(scope="session")
def es_client():
    es = Elasticsearch(
        hosts=[ES_HOST],
        port=ES_PORT,
    )

    return es


@pytest.fixture(scope='module')
def test_index_data(index_types, es_client):
    """Generate data index as a fixture for re-use between tests"""

    # Create test index with dummy docs
    index_prefix = 'test_index_data'

    index_names = get_index_names(index_prefix, index_types)

    cleanup_indices(es_client, index_names.values())

    # Create dummy esbuild docs
    for index_type in index_types:
        mapping = es_data.get_mapping(index_type)

        es_client.indices.create(index=index_names[index_type], ignore=400,
                                 body=es_data.get_index_settings())
        es_client.indices.refresh(index=index_names[index_type])
        es_client.indices.put_mapping(index=index_names[index_type], body=mapping)

        for doc in getattr(es_data, '{}_docs'.format(index_type)):
            doc_id = doc["project_id"] if index_type == "project" else None

            es_client.index(
                index=index_names[index_type],
                body=doc,
                id=doc_id,
            )

    es_client.indices.refresh()

    # Make sure that docs are created:
    for index_type, counts in [['case', len(es_data.case_docs)],
                               ['file', len(es_data.file_docs)],
                               ['project', len(es_data.project_docs)],
                               ['annotation', len(es_data.annotation_docs)]]:
        while True:
            count = es_client.count(index=index_names[index_type])['count']
            if count == counts:
                break
            time.sleep(0.1)

    yield es_client, index_prefix

    cleanup_indices(es_client, index_names.values())


@pytest.fixture(scope='module')
def es_after_deletion(test_index_data, index_types):
    """
    Deletes some projects from the index but not updates the metadata,
    leaving build_metadata inconsistent purposefully
    """
    es, index_prefix = test_index_data
    helper = ReleaseHelper(es, audit_index="build_metadata_test")

    # Will delete these projects' data
    projects_to_delete = ["TCGA-STAD", "FM-AD"]

    # Get project list before deletion
    projects_before = helper.get_project_ids(index_prefix)

    index_names = get_index_names(index_prefix, index_types)
    # Delete documents associated with selected projects from index
    for index_type, index_name in index_names.items():
        helper.delete_docs_from_index(index_name, index_type, projects_to_delete)

    es.indices.refresh()

    return es, index_prefix, projects_before, projects_to_delete


@pytest.fixture
def setup_test(pg_driver, es_client):
    cleanup_indices(es_client)

    yield es_client

    cleanup_indices(es_client)


@pytest.fixture(autouse=True)
def mocked_statsd(monkeypatch):
    def event_mock(*_, **__):
        pass

    monkeypatch.setattr(statsd, 'event', event_mock)


@pytest.fixture
def generate_scenario(graph_factory, pg_driver, create_indexd_documents):
    nodes = []

    def _from_file(scenario):
        path = os.path.join(DATA_DIR, scenario)

        with open(path) as f:
            nodes_meta = yaml.safe_load(f)

        x_nodes = graph_factory.create_from_nodes_and_edges(
            nodes=nodes_meta['nodes'],
            edges=nodes_meta['edges'],
            all_props=True,
        )

        for n in x_nodes:
            n.acl = ['phs000178']

        x_nodes, records = data.patch_test_data_get_indexd(x_nodes)
        nodes.extend(x_nodes)
        docs = create_indexd_documents(records)

        case_nodes = [n for n in x_nodes if n.label == 'case']

        with pg_driver.session_scope():
            project = pg_driver.nodes(models.Project).props(code='BRCA').one()
            project.cases.extend(case_nodes)

        return x_nodes, docs

    yield _from_file

    cleanup_nodes(pg_driver, nodes)


@pytest.fixture
def scenario_index(pg_driver, init_indexd, generate_scenario):
    def make_graph(filename):
        generate_scenario(filename)

        builder = ActiveGraphIndexBuilder(pg_driver, init_indexd)

        with pg_driver.session_scope():
            builder.cache_database()

        index = builder.denormalize_all()

        return Index._make(index)

    return make_graph


@pytest.fixture
def gencode_version_graph(generate_scenario):
    generate_scenario("gencode_version.yaml")


@pytest.fixture
def apply_gencode_to_indexd(pg_driver, init_indexd, gencode_version_graph):
    gencode_versions = [
        ["gv_ge_0", "v22"],
        ["gv_ge_1", "v36"],
        ["gv_ge_2", None],
    ]
    with pg_driver.session_scope():
        for submitter_id, gencode in gencode_versions:
            node = pg_driver.nodes(models.GeneExpression).props(submitter_id=submitter_id).one()
            doc = init_indexd.get(node.node_id)
            doc.metadata["gencode_version"] = gencode
            doc.patch()
    return init_indexd
