import os

import pytest
import yaml
from gdcdatamodel import models

from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from tests.conftest import cleanup_nodes, Index
from tests.data import patch_test_data_get_indexd

CURR_DIR = os.path.dirname(__file__)
NODES_METADATA_LOCATION = os.path.join(CURR_DIR, 'maf_nodes.yaml')
EDGES_METADATA_LOCATION = os.path.join(CURR_DIR, 'maf_edges.yaml')


@pytest.fixture
def maf_graph(graph_factory, pg_driver, create_indexd_documents):
    with open(NODES_METADATA_LOCATION) as f:
        maf_nodes_meta = yaml.safe_load(f)

    with open(EDGES_METADATA_LOCATION) as f:
        maf_edges_meta = yaml.safe_load(f)

    maf_nodes = graph_factory.create_from_nodes_and_edges(
        nodes=maf_nodes_meta['nodes'],
        edges=maf_edges_meta['edges'],
        all_props=True,
    )

    for n in maf_nodes:
        n.acl = ['phs000178']

    maf_nodes, records = patch_test_data_get_indexd(maf_nodes)
    docs = create_indexd_documents(records)

    case_nodes = [n for n in maf_nodes if n.label == 'case']

    with pg_driver.session_scope():
        project = pg_driver.nodes(models.Project).props(code='BRCA').one()
        project.cases.extend(case_nodes)

    yield maf_nodes, docs

    cleanup_nodes(pg_driver, maf_nodes)


@pytest.fixture
def maf_index(pg_driver, init_indexd, maf_graph):
    builder = ActiveGraphIndexBuilder(pg_driver, init_indexd)
    with pg_driver.session_scope():
        builder.cache_database()
    index = builder.denormalize_all()

    return Index._make(index)
