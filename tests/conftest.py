# -*- coding: utf-8 -*-
"""
Setup esbuild tests
"""

import logging
import os
import time
from collections import namedtuple

import psqlgraph
import pytest
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

from esbuild.utils import ReleaseHelper
from tests import data, es_data

# ======================================================================
# Test Settings

Index = namedtuple('Index', 'cases, files, annotations, projects')

TEST_DIR = os.path.dirname(os.path.realpath(__file__))

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
def init_indexd(indexd_client):
    # Insert indexd data:
    for record in data.INDEXD:
        record = dict(record)  # prevent data.INDEXD object mutation
        did = record.pop('did')
        md5 = record.pop('md5sum')
        size = record.pop('file_size')
        file_name = record.pop('file_name', None)
        file_state = record.pop('file_state', 'validated')
        acl = record.pop('acl')
        urls = record.pop('urls')
        # NOTE: 'file_state' is stored as 'state' in indexd.
        # However, this is not important as esbuild does not pay attention to 'file_state'
        # and it is removed from resulting elasticsearch documents. See PRTL-2109
        urls_metadata = {
            urls[0]: {'state': file_state}
        }
        indexd_client.create(
            did=did,
            acl=acl,
            hashes={'md5': md5},
            size=size,
            file_name=file_name,
            urls=urls,
            metadata=record,
            urls_metadata=urls_metadata,
        )

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

    monkeypatch.setenv('ELASTICSEARCH_HOST', ES_HOST)
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


@pytest.fixture(scope='module')
def test_index():
    """Generate an index as a fixture for re-use between tests"""

    es_driver = Elasticsearch(hosts=[ES_HOST], port=ES_PORT)
    index = 'test_index__'
    doc_type = 'test'
    docs = es_data.dummy_docs

    cleanup_indices(es_driver, [index])
    es_driver.indices.create(index=index, ignore=400)
    for doc in docs:
        es_driver.index(
            index=index,
            id=doc['id'],
            doc_type=doc_type,
            body=doc,
            ignore=409,
        )

    while True:
        count = es_driver.count(index=index, doc_type=doc_type)['count']
        if count == len(docs):
            break
        time.sleep(0.1)

    yield es_driver, index, doc_type, docs

    cleanup_indices(es_driver, [index])


@pytest.fixture(scope='module')
def test_index_data():
    """Generate data index as a fixture for re-use between tests"""

    # Create test index with dummy docs
    es_driver = Elasticsearch(hosts=[ES_HOST], port=ES_PORT)
    index = 'test_index_data__'

    cleanup_indices(es_driver, [index])

    # Create test index and put mappings
    es_driver.indices.create(index=index, ignore=400,
                             body=es_data.get_index_settings())

    # Create dummy build_metadata documents
    metadata_docs = es_data.build_metadata

    for doc in metadata_docs:
        es_driver.index(
            index=index, doc_type='build_metadata', body=doc,
            id=ReleaseHelper.get_build_metadata_id(doc['build_projects']))

    # Create dummy esbuild docs
    for dtype in ['case', 'file', 'project', 'annotation']:
        mapping = es_data.get_mapping(dtype)
        es_driver.indices.put_mapping(index=index, doc_type=dtype, body=mapping)
        for doc in getattr(es_data, '{}_docs'.format(dtype)):
            if dtype == 'project':
                es_driver.index(index=index, doc_type=dtype, body=doc, id=doc['project_id'])
            else:
                es_driver.index(index=index, doc_type=dtype, body=doc)

    # Make sure that docs are created:
    for dtype, dcount in [['build_metadata', len(metadata_docs)],
                          ['case', len(es_data.case_docs)],
                          ['file', len(es_data.file_docs)],
                          ['project', len(es_data.project_docs)],
                          ['annotation', len(es_data.annotation_docs)]]:
        while True:
            count = es_driver.count(index=index, doc_type=dtype)['count']
            if count == dcount:
                break
            time.sleep(0.1)

    yield es_driver, index

    cleanup_indices(es_driver, [index])


@pytest.fixture(scope='module')
def es_after_deletion(test_index_data):
    """
    Deletes some projects from the index but not updates the metadata,
    leaving build_metadata inconsistent purposefully
    """
    es, index_name = test_index_data
    helper = ReleaseHelper(es)

    # Will delete these projects' data
    projects_to_delete = ["TCGA-STAD", "FM-AD"]

    # Get project list before deletion
    projects_before = helper.get_project_ids(index_name)

    # Delete documents associated with selected projects from index
    helper.delete_docs_from_index(index_name, projects_to_delete)

    es.indices.refresh()
    # Wait for index to update
    time.sleep(2)
    return es, index_name, projects_before, projects_to_delete


@pytest.fixture
def setup_test(pg_driver):
    es = Elasticsearch(hosts=[ES_HOST], port=ES_PORT)

    cleanup_indices(es)

    yield es

    cleanup_indices(es)
