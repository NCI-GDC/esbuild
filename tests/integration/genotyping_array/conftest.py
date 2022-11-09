from typing import Any, Callable

import pytest
from indexclient import client
import psqlgraph

from esbuild.graph.active import builder
from tests.integration import conftest


@pytest.fixture
def genotyping_array_graph(generate_scenario: Callable[[str], Any]) -> None:
    generate_scenario("genotyping_array_scenario.yaml")


@pytest.fixture
def genotyping_array_index(
    pg_driver: psqlgraph.PsqlGraphDriver,
    init_indexd: client.IndexClient,
    genotyping_array_graph: None,
) -> conftest.Index:
    active_builder = builder.ActiveGraphIndexBuilder(pg_driver, init_indexd)
    with pg_driver.session_scope():
        active_builder.cache_database()
    index = active_builder.denormalize_all()

    return conftest.Index(*index)
