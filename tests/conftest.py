# -*- coding: utf-8 -*-
"""
Setup esbuild tests
"""

from collections import namedtuple
from elasticsearch import Elasticsearch
from psqlgraph import PsqlGraphDriver, Node, Edge

import data
import os
import pytest
import time

Index = namedtuple('Index', 'cases, files, annotations, projects')

TEST_DIR = os.path.dirname(os.path.realpath(__file__))
BIN_DIR = os.path.join(os.path.dirname(TEST_DIR), 'bin')

ES_HOST = 'localhost'
ES_PORT = 9200

PG_HOST = 'localhost'
PG_USER = 'test'
PG_PASSWORD = 'test'
PG_DATABASE = 'automated_test'

_graph = PsqlGraphDriver(PG_HOST, PG_USER, PG_PASSWORD, PG_DATABASE)


# ======================================================================
# Util

@pytest.fixture
def clear_database():
    edge_tables = Edge.get_subclass_table_names()
    node_tables = Node.get_subclass_table_names()
    tables = ['_voided_nodes', '_voided_edges'] + [
        t for t in edge_tables + node_tables
        if t not in {'edge_edge', 'node_node'}
    ]

    with _graph.engine.begin() as conn:
        conn.execute('TRUNCATE {}'.format(', '.join(tables)))


class TestError(Exception):
    pass


def raise_test_error(*args, **kwargs):
    raise TestError('{} {}'.format(args, kwargs))


# ======================================================================
# Fixtures

@pytest.fixture
def environment(monkeypatch):
    monkeypatch.setenv('ELASTICSEARCH_HOST', 'localhost')
    monkeypatch.setenv('ES_USER', '')
    monkeypatch.setenv('ES_PASSWORD', '')
    monkeypatch.setenv('PG_HOST', PG_HOST)
    monkeypatch.setenv('PG_USER', PG_USER)
    monkeypatch.setenv('PG_PASS', PG_PASSWORD)
    monkeypatch.setenv('PG_NAME', PG_DATABASE)


@pytest.fixture(scope="module", autouse=True)
def sample_database():
    clear_database()
    data.insert(_graph)


@pytest.yield_fixture()
def graph():
    with _graph.session_scope() as session:
        session.commit, session._commit = session.flush, session.commit
        yield _graph
        session.rollback()


# ======================================================================
# Elasticsearch test index


@pytest.yield_fixture(scope='module')
def test_index():
    es = Elasticsearch(ES_HOST, port=ES_PORT)
    index = 'test_index__'
    doc_type = 'test'
    docs = [{
        'id': 'test-doc-1',
        'value': 1,
    }, {
        'id': 'test-doc-2',
        'value': 2,
    }]

    es.indices.create(index=index, ignore=400)
    for doc in docs:
        es.create(
            index=index,
            id=doc['id'],
            doc_type=doc_type,
            body=doc,
            ignore=409,
        )

    while True:
        count = es.count(index=index, doc_type=doc_type)['count']
        if count == len(docs):
            break
        time.sleep(0.1)

    yield es, index, doc_type, docs
    es.indices.delete(index=index, ignore=400)
