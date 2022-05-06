from gdcdatamodel.models.submission import TransactionSnapshot

from esbuild.gdc_elasticsearch import GDCElasticsearch
from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.graph.common.builder import AVAILABLE_GENCODE_VERSIONS
from esbuild.utils import (
    INDEXD_METADATA_FIELDS,
    VersionedNodesDiffCollector,
    extract_indexd_metadata,
)


def assert_metadata(latest, diff):
    metadata = extract_indexd_metadata(latest)

    for field, val in metadata.items():
        assert diff.get(field) == val


def test_cache_versioned_nodes(
    pg_driver, versioned_reads_setup, setup_test, indexd_client
):
    cacher = VersionedNodesDiffCollector(
        project_ids=["TCGA-BRCA"],
        graph=pg_driver,
        indexd_client=indexd_client,
        allowed_gencode_versions=AVAILABLE_GENCODE_VERSIONS,
    )
    diffs = cacher.collect_differences()

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


def assert_inclusion(doc1, doc2, ignore=("updated_datetime",)):
    for field, val in doc1.items():
        if field not in ignore and field in doc2:
            assert doc2.get(field) == val, (field, val, doc2.get(field))


def assert_aligned_reads_documents(indexd, pg_driver, ar_node, es_response):
    ari_node = ar_node.aligned_reads_indexes[0]

    # Query for latest released IndexD document. The ES index should contain
    # this metadata
    ar_doc = indexd.get_latest_version(ar_node.node_id, True)
    ari_doc = indexd.get_latest_version(ari_node.node_id, True)

    # Query for TransactionSnapshots
    with pg_driver.session_scope():
        ar_ts = (
            pg_driver.nodes(TransactionSnapshot)
            .filter(
                TransactionSnapshot.id == ar_node.node_id,
                TransactionSnapshot.action == "version",
            )
            .first()
        )
        ari_ts = (
            pg_driver.nodes(TransactionSnapshot)
            .filter(
                TransactionSnapshot.id == ari_node.node_id,
                TransactionSnapshot.action == "version",
            )
            .first()
        )

    ar_hits = [
        hit["_source"]
        for hit in es_response["hits"]["hits"]
        if ar_doc.did == hit["_id"]
    ]

    ar_props = extract_indexd_metadata(ar_doc)
    ari_props = extract_indexd_metadata(ari_doc)

    # Assert root level document properties
    ar_hit = ar_hits[0]
    assert_inclusion(ar_props, ar_hit)

    # Assert nested index_file properties
    assert len(ar_hit["index_files"]) == 1
    assert_inclusion(ar_hit["index_files"][0], ari_props)

    # Make sure either both snapshots exist or none
    assert ar_ts and ari_ts or (not ar_ts and not ari_ts)

    # No previous versions, just early exit
    if not ar_ts:
        return

    # Make sure that non IndexD property values are pulled from the snapshot
    ar_props = (
        ar_ts.new_props if ar_doc.did == ar_node.node_id else ar_ts.old_props
    )  # noqa
    assert_inclusion(ar_props, ar_hit, INDEXD_METADATA_FIELDS + ["updated_datetime"])

    ari_props = (
        ari_ts.new_props if ari_doc.did == ari_node.node_id else ari_ts.old_props
    )  # noqa
    assert_inclusion(
        ari_props,
        ar_hit["index_files"][0],
        INDEXD_METADATA_FIELDS + ["updated_datetime"],
    )


def test_esbuild_versioning(
    pg_driver,
    init_indexd,
    versioned_reads_expectations,
    versioned_reads_setup,
    setup_test,
):
    es = setup_test
    builder = GDCElasticsearch(
        converter_class=ActiveGraphIndexBuilder,
        indexd_client=init_indexd,
        index_prefix="gdc_es_test",
        index_alias_prefix="test_gdc_from_graph",
        pg_driver=pg_driver,
        cache_versioned=True,
        build_projects=["TCGA-BRCA"],
        es=es,
    )
    builder.go()

    es_expectations = versioned_reads_expectations
    nodes, versioned_nodes, versioned_docs, params = versioned_reads_setup

    source = INDEXD_METADATA_FIELDS + ["index_files"]
    res = es.search(
        index="gdc_es_test_file",
        body={
            "query": {"terms": {"submitter_id": ["ar_sar1", "ar_sur1"]}},
            "_source": source,
        },
    )

    total = res["hits"]["total"]

    assert total["relation"] == "eq"
    assert len(es_expectations) == total["value"]

    # If there were no versions, there are no differences to be detected
    if not params["make_versions"]:
        return

    expected_ars = set(es_expectations.keys())
    ars = [n for n in nodes if n.label == "aligned_reads" and n.node_id in expected_ars]
    for ar in ars:
        assert_aligned_reads_documents(init_indexd, pg_driver, ar, res)
