import pytest

from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from tests.integration.conftest import Index


@pytest.fixture
def molecular_test_scenario(generate_scenario):
    generate_scenario("molecular_test_scenario.yaml")


@pytest.fixture
def molecular_test_index(pg_driver, init_indexd, molecular_test_scenario):
    builder = ActiveGraphIndexBuilder(pg_driver, init_indexd)
    with pg_driver.session_scope():
        builder.cache_database()
    index = builder.denormalize_all()

    return Index._make(index)
