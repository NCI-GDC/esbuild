from esbuild.utils import VersionedNodesCacher


def test_cache_versioned_nodes(graph, aligned_reads_created, setup_test,
                               indexd_client):
    cacher = VersionedNodesCacher(project_ids=['TCGA-BRCA'], graph=graph,
                                  indexd_client=indexd_client)
    diffs = cacher.run()

    nodes, _, _ = aligned_reads_created
    # 1 AlignedReads and 1 AlignedReadsIndex should be versioned
    assert len(diffs) == 2
    assert {n.node_id for n in nodes if n.state == 'submitted'} == set(diffs.keys())
