from typing import NamedTuple, Callable

import pytest

from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from indexclient.client import IndexClient
from psqlgraph import PsqlGraphDriver

from tests.conftest import Index


@pytest.fixture
def maf_graph(generate_scenario: Callable) -> None:
    generate_scenario("methylation_array_scenario.yaml")


@pytest.fixture
def methylation_index(
    pg_driver: PsqlGraphDriver, init_indexd: IndexClient, maf_graph
) -> NamedTuple:
    builder = ActiveGraphIndexBuilder(pg_driver, init_indexd)
    with pg_driver.session_scope():
        builder.cache_database()
    index = builder.denormalize_all()

    return Index._make(index)
