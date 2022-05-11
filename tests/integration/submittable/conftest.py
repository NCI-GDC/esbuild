import pytest

from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from tests.integration.conftest import Index


@pytest.fixture
def pathology_report_graph(generate_scenario):
    generate_scenario("pathology_report_scenario.yaml")


@pytest.fixture
def pathology_index(pg_driver, init_indexd, pathology_report_graph):
    builder = ActiveGraphIndexBuilder(pg_driver, init_indexd)
    with pg_driver.session_scope():
        builder.cache_database()
    index = builder.denormalize_all()

    return Index._make(index)
