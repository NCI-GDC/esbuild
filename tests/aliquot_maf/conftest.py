import pytest

from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from tests.conftest import Index


@pytest.fixture
def maf_graph(generate_scenario):
    generate_scenario('maf_scenario.yaml')


@pytest.fixture
def maf_index(pg_driver, init_indexd, maf_graph):
    builder = ActiveGraphIndexBuilder(pg_driver, init_indexd)
    with pg_driver.session_scope():
        builder.cache_database()
    index = builder.denormalize_all()

    return Index._make(index)
