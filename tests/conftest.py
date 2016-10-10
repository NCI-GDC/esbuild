# -*- coding: utf-8 -*-
"""
Setup esbuild tests
"""

from collections import namedtuple
from elasticsearch import Elasticsearch
from psqlgraph import PsqlGraphDriver, Node, Edge
#from gdcdatamodel.viz import create_graphviz

import data
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

    es_driver = Elasticsearch(ES_HOST, port=ES_PORT)
    index = 'test_index__'
    doc_type = 'test'
    docs = [{
        'id': 'test-doc-1',
        'value': 1,
    }, {
        'id': 'test-doc-2',
        'value': 2,
    }]

    es_driver.indices.create(index=index, ignore=400)
    for doc in docs:
        es_driver.create(
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
    es_driver.indices.delete(index=index, ignore=400)
