import psqlgraph
import pytest
from indexclient import client

from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from tests.integration.conftest import Index


@pytest.fixture
def other_clinical_attribute_scenario(generate_scenario) -> None:
    generate_scenario("other_clinical_attribute_scenario.yaml")


@pytest.fixture
def other_clinical_attribute_scenario_index(
    pg_driver: psqlgraph.PsqlGraphDriver,
    init_indexd: client.IndexClient,
    other_clinical_attribute_scenario,
):
    builder = ActiveGraphIndexBuilder(pg_driver, init_indexd)

    with pg_driver.session_scope():
        builder.cache_database()

    index = builder.denormalize_all()

    return Index._make(index)
