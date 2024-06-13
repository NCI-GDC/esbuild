import pytest

from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from tests.integration.conftest import Index


@pytest.fixture
def maf_graph(generate_scenario):
    generate_scenario("maf_scenario.yaml")


@pytest.fixture
def maf_index(pg_driver, init_indexd, maf_graph):
    builder = ActiveGraphIndexBuilder(
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
        builder.cache_database()
    index = builder.denormalize_all()

    return Index._make(index)
