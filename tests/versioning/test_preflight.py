from esbuild.gdc_elasticsearch import GDCElasticsearch
from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.utils import VersionedNodesCacher, MetadataTransformer


def assert_metadata(latest, diff):
    tf = MetadataTransformer.transform(latest)

    for field, val in tf.items():
        assert diff.get(field) == val


def test_cache_versioned_nodes(graph, versioned_reads_setup, setup_test,
                               indexd_client):
    cacher = VersionedNodesCacher(project_ids=['TCGA-BRCA'], graph=graph,
                                  indexd_client=indexd_client)
    diffs = cacher.run()

    _, expected_diffs, expected_docs, params = versioned_reads_setup

    if params.make_versions and params.make_versions:
        assert len(diffs) == len(expected_diffs)
        assert len(diffs) == len(expected_docs)
        assert {n.node_id for n in expected_diffs} == set(diffs.keys())
        assert set(expected_docs.keys()) == set(diffs.keys())
        for did, doc in expected_docs.items():
            assert_metadata(doc, diffs[did])
    else:
        assert len(expected_docs) == 0


def test_esbuild_versioning(graph, init_indexd, versioned_reads_expectations,
                            versioned_reads_setup, setup_test):
    es = setup_test
    builder = GDCElasticsearch(
        converter_class=ActiveGraphIndexBuilder,
        indexd_client=init_indexd,
        index_base='gdc_es_test',
        index_close_thresh=4,
        build_projects=['TCGA-BRCA'],
        pg_driver=graph,
    )
    builder.go()

    es_expectations = versioned_reads_expectations
    _, _, versioned_docs, _ = versioned_reads_setup

    source = MetadataTransformer.INDEXD_META_FIELDS + ['index_files']
    res = es.search(index=builder.index_name, doc_type='file',
                    body={'query': {'terms': {'submitter_id': ['ar_sar1',
                                                               'ar_sur1']}},
                          '_source': source})

    assert len(es_expectations) == res['hits']['total']
