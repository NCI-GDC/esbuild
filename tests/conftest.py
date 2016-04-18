# -*- coding: utf-8 -*-
"""
Setup esbuild tests
"""

from collections import namedtuple
from psqlgraph import PsqlGraphDriver, Node, Edge

import data
import os
import pytest

Index = namedtuple('Index', 'cases, files, annotations, projects')

TEST_DIR = os.path.dirname(os.path.realpath(__file__))
BIN_DIR = os.path.join(os.path.dirname(TEST_DIR), 'bin')

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
