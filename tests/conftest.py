# -*- coding: utf-8 -*-
"""
Setup esbuild tests
"""

from collections import namedtuple
from elasticsearch import Elasticsearch
from gdcdatamodel.viz import create_graphviz
from psqlgraph import PsqlGraphDriver, Node, Edge

import data
import es_data
import logging
import os
import pytest
import time

# ======================================================================
# Test Settings

Index = namedtuple('Index', 'cases, files, annotations, projects')

TEST_DIR = os.path.dirname(os.path.realpath(__file__))
BIN_DIR = os.path.join(os.path.dirname(TEST_DIR), 'bin')

ES_HOST = 'localhost'
ES_PORT = 9200

PG_HOST = 'localhost'
PG_USER = 'test'
PG_PASSWORD = 'test'
PG_DATABASE = 'automated_test'

# ======================================================================
# Util

logger = logging.getLogger("conftest")
logger.setLevel(logging.DEBUG)


_graph = PsqlGraphDriver(PG_HOST, PG_USER, PG_PASSWORD, PG_DATABASE)


@pytest.fixture
def clear_database():
    """Clear graph from database"""

    edge_tables = Edge.get_subclass_table_names()
    node_tables = Node.get_subclass_table_names()
    tables = ['_voided_nodes', '_voided_edges'] + [
        t for t in edge_tables + node_tables
        if t not in {'edge_edge', 'node_node'}
    ]

    with _graph.engine.begin() as conn:
        conn.execute('TRUNCATE {}'.format(', '.join(tables)))


class TestError(Exception):
    """Monkeypatch exception for testinting exception handling"""
    pass


def raise_test_error(*args, **kwargs):
    """For monkeypatching to test exception handling"""

    raise TestError('{} {}'.format(args, kwargs))


def render_database():
    """Save PDF graph of test suite data"""

    with _graph.session_scope():
        dot = create_graphviz(_graph.nodes())
        dot.render('test_suite_data.gv')


# ======================================================================
# Fixtures

@pytest.fixture
def environment(monkeypatch):
    """Monkeypatch the script environment"""

    monkeypatch.setenv('ELASTICSEARCH_HOST', 'localhost')
    monkeypatch.setenv('ES_USER', '')
    monkeypatch.setenv('ES_PASSWORD', '')
    monkeypatch.setenv('PG_HOST', PG_HOST)
    monkeypatch.setenv('PG_USER', PG_USER)
    monkeypatch.setenv('PG_PASS', PG_PASSWORD)
    monkeypatch.setenv('PG_NAME', PG_DATABASE)


@pytest.fixture(scope="module", autouse=True)
def sample_database():
    """Add all test data to the database.

    Attempt to render a PDF representation of the test suite.

    """

    clear_database()
    data.insert(_graph)

    try:
        render_database()
    except Exception as exc:
        logger.error('Failed to write updated database viz files: %s', exc)


@pytest.yield_fixture()
def graph():
    """Fixture to return temporary session database driver"""

    with _graph.session_scope() as session:
        session.commit, session._commit = session.flush, session.commit
        yield _graph
        session.rollback()


# ======================================================================
# Elasticsearch test index


@pytest.yield_fixture(scope='module')
def test_index():
    """Generate an index as a fixture for re-use between tests"""

    # Create test index with dummy docs
    es_driver = Elasticsearch(ES_HOST, port=ES_PORT)
    index = 'test_index__'
    doc_type = 'test'
    docs = es_data.dummy_docs

    # Try to remove old test index if any 
    es_driver.indices.delete(index=index, ignore=404)

    # Create test index and put mappings
    es_driver.indices.create(index=index, ignore=400,
                             body=es_data.get_index_settings())

    es_driver.indices.put_mapping(index=index, doc_type='test',
                                  body=es_data.get_mapping('test'))
    # Populate test index
    for doc in docs:
        es_driver.index(
            index=index,
            id=doc['id'],
            doc_type=doc_type,
            body=doc,
            ignore=409,
        )

    # Create dummy build_metadata documents
    metadata_docs = es_data.build_metadata

    for doc in metadata_docs:
        es_driver.index(index=index, doc_type='build_metadata',
                        body=doc, id=','.join(doc['build_projects']))

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
    for dtype, dcount in [['test', len(docs)],
                          ['build_metadata', len(metadata_docs)],
                          ['case', len(es_data.case_docs)],
                          ['file', len(es_data.file_docs)],
                          ['project', len(es_data.project_docs)],
                          ['annotation', len(es_data.annotation_docs)]]:
        while True:
            count = es_driver.count(index=index, doc_type=dtype)['count']
            if count == dcount:
                break
            time.sleep(0.1)

    yield es_driver, index, doc_type, docs
    es_driver.indices.delete(index=index, ignore=400)
