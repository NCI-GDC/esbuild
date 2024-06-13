from typing import Any, Callable

import psqlgraph
import pytest
from indexclient import client

from esbuild.graph.active import builder
from tests.integration import conftest


@pytest.fixture
def copy_number_estimate_graph(generate_scenario: Callable[[str], Any]) -> None:
    generate_scenario("copy_number/estimate_scenario.yaml")


@pytest.fixture
def copy_number_estimate_index(
    pg_driver: psqlgraph.PsqlGraphDriver,
    init_indexd: client.IndexClient,
    copy_number_estimate_graph: None,
) -> conftest.Index:
    active_builder = builder.ActiveGraphIndexBuilder(
        pg_driver,
        init_indexd,
        index_prefix="",
        build_projects=(),
        build_awg=False,
        selective_caching=False,
        versioned_files={},
        allowed_gencode_versions=frozenset({"neutral", "v36"}),
    )
    with pg_driver.session_scope():
        active_builder.cache_database()
    index = active_builder.denormalize_all()

    return conftest.Index(*index)


@pytest.fixture
def copy_number_segment_graph(generate_scenario: Callable[[str], Any]) -> None:
    generate_scenario("copy_number/segment_scenario.yaml")


@pytest.fixture
def copy_number_segment_index(
    pg_driver: psqlgraph.PsqlGraphDriver,
    init_indexd: client.IndexClient,
    copy_number_segment_graph: None,
) -> conftest.Index:
    active_builder = builder.ActiveGraphIndexBuilder(
        pg_driver,
        init_indexd,
        index_prefix="",
        build_projects=(),
        build_awg=False,
        selective_caching=False,
        versioned_files={},
        allowed_gencode_versions=frozenset({"neutral", "v36"}),
    )
    with pg_driver.session_scope():
        active_builder.cache_database()
    index = active_builder.denormalize_all()

    return conftest.Index(*index)
