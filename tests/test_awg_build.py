import pytest

from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder
from conftest import _graph


@pytest.mark.parametrize('builder_class,expected_nodes',
    [
     (ActiveGraphIndexBuilder, {
        'case': {u'submitted-awg-case', u'processed-awg-case'},
        'project': {u'awg-one-project'},
        # Why does esbuild pick up all programs?
        'program': {u'internal-program', u'brca-program'}}),
     (LegacyGraphIndexBuilder, {
        'case': {'legacy-awg-case'},
        'project': {'legacy-awg-project'},
        # Why does esbuild pick up all programs?
        'program': {u'internal-program', u'brca-program'}}),
     ]
)
def test_awg_build(builder_class, expected_nodes):
    """
    Tests AWG build mode
    """
    build_projects = {'TCGA-BRCA', 'TCGA-LUAD', 'INTERNAL-AWG-ONE', 'TCGA-AWG-LEGACY'}
    builder = builder_class(_graph, build_awg=True, build_projects=build_projects)
    builder.cache_database()

    # Check that only AWG nodes were cached
    cached_nodes = {}
    for node in builder.G.nodes():
        cached_nodes.setdefault(node.label, set())
        cached_nodes[node.label].update([node.node_id])

    assert cached_nodes == expected_nodes
