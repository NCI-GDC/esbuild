from collections.abc import Callable
from typing import Any

import psqlgraph
import pytest
from indexclient import client

from esbuild.graph.active import builder
from tests.integration import conftest


@pytest.fixture
def pathology_report_graph(generate_scenario):
    generate_scenario("pathology_report_scenario.yaml")


@pytest.fixture
def pathology_index(pg_driver, init_indexd, pathology_report_graph):
    active_builder = builder.ActiveGraphIndexBuilder(pg_driver, init_indexd)
    with pg_driver.session_scope():
        active_builder.cache_database()
    index = active_builder.denormalize_all()

    return conftest.Index._make(index)


@pytest.fixture
def submitted_expression_array_graph(generate_scenario: Callable[[str], Any]) -> None:
    generate_scenario("submitted_expression_array_scenario.yaml")


@pytest.fixture
def submitted_expression_array_index(
    pg_driver: psqlgraph.PsqlGraphDriver,
    init_indexd: client.IndexClient,
    submitted_expression_array_graph: Any,
) -> conftest.Index:
    active_builder = builder.ActiveGraphIndexBuilder(pg_driver, init_indexd)
    with pg_driver.session_scope():
        active_builder.cache_database()
    index = active_builder.denormalize_all()

    return conftest.Index(*index)
