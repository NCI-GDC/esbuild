from esbuild.utils import VersionedNodesCacher


def test_cache_versioned_nodes(graph, versioned_reads_setup, setup_test,
                               indexd_client):
    cacher = VersionedNodesCacher(project_ids=['TCGA-BRCA'], graph=graph,
                                  indexd_client=indexd_client)
    diffs = cacher.run()

    _, expected_diffs, expected_docs = versioned_reads_setup

    import pdb; pdb.set_trace()
    assert len(diffs) == len(expected_diffs)
    assert {n.node_id for n in expected_diffs} == set(diffs.keys())
