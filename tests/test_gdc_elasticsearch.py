# -*- coding: utf-8 -*-
"""
Tests the GDC Elasticsearch interaction for active and legacy
indices.

"""
from concurrent import futures
import json
from unittest import mock

import pytest
import elasticsearch

from esbuild import gdc_elasticsearch, reindexing, utils
from esbuild.gdc_elasticsearch import GDCElasticsearch
from esbuild.graph.active import builder
from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder
from gdcdatamodel.models import Demographic, File
from tests import data
from tests.conftest import cleanup_nodes, get_all_indices
from tests.data import get_node_id

GRAPH_INDEX_DOC_TYPES = ["project", "case", "annotation", "file"]


@pytest.fixture
def make_gdc_es(pg_driver, es_client):
    def wrapper(indexd_client, converter, **kwargs):
        return GDCElasticsearch(
            converter_class=converter,
            es=es_client,
            indexd_client=indexd_client,
            index_prefix=kwargs.get("index_prefix", "gdc_es_test"),
            index_alias_prefix=kwargs.get("index_alias_prefix", "gdc_from_graph"),
            pg_driver=pg_driver,
            **kwargs
        )

    return wrapper


@pytest.fixture()
def derived_file(pg_driver):
    with pg_driver.session_scope() as sxn:
        to_delete_file = (
            pg_driver.nodes(File).ids([get_node_id("to-delete-file")]).one()
        )
        derived_file = data.fuzzed(
            File, state="live", file_name="foo-bar", file_size=1234
        )
        to_delete_file.derived_files = [derived_file]
        sxn.merge(derived_file)

    yield derived_file

    cleanup_nodes(pg_driver, [derived_file])


def verify_index_settings(es, index, replicas, shards):
    """Assert that the given index has the expected settings."""

    # Confirm the settings are as expected.
    settings_response = es.indices.get_settings(
        index, name=["index.number_of_replicas", "index.number_of_shards"]
    )
    settings = settings_response[index]["settings"]
    assert int(settings["index"]["number_of_replicas"]) == replicas
    assert int(settings["index"]["number_of_shards"]) == shards

    # Confirm the actual number of replicas/shards matches the settings.
    stats = es.indices.stats(index, level="shards")
    assert stats["_shards"]["total"] == (replicas + 1) * shards
    assert len(stats["indices"][index]["shards"]) == shards


@pytest.fixture
def patched_demographic(pg_driver):
    with pg_driver.session_scope() as s:
        demographic = pg_driver.nodes(Demographic).one()
        s.execute(
            """
            UPDATE node_demographic
            SET _props = :props
            WHERE node_id = :id
            """,
            {
                "id": demographic.node_id,
                "props": json.dumps(
                    dict(
                        demographic.props,
                        **{
                            "fake_property": True,
                        }
                    )
                ),
            },
        )

    yield

    with pg_driver.session_scope():
        demographic = pg_driver.nodes().get(demographic.node_id)
        demographic._props.pop("fake_property")
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(demographic, "_props")


@pytest.mark.parametrize("converter", [ActiveGraphIndexBuilder])
def test_basic_es_generate(setup_test, init_indexd, converter, make_gdc_es):
    es = setup_test
    gdces = make_gdc_es(init_indexd, converter)
    gdces.go()

    all_indices = get_all_indices(setup_test)
    expected_indices = set(gdces.index_names.values()) | {"build_metadata"}

    assert set(all_indices) == expected_indices
    assert len(all_indices) == len(expected_indices)

    # check that we esbuilt the index with the expected default settings
    for index in gdces.index_names.values():
        verify_index_settings(setup_test, index=index, replicas=0, shards=1)

    # also verify that the to_delete file is not in the index and
    # got deleted
    file_index = gdces.index_names["file"]
    assert not es.exists(index=file_index, id=get_node_id("to-delete-file"))

    # Test Case exists by id
    case_index = gdces.index_names["case"]
    assert es.exists(index=case_index, id=get_node_id("case-tcga-brca-breast"))

    # Test blocking release annotation does not exist in index
    annotation_index = gdces.index_names["annotation"]
    assert not es.exists(
        index=annotation_index, id=get_node_id("block-release-annotation")
    )
    assert not es.exists(
        index=annotation_index, id=get_node_id("block-release-annotation-released")
    )
    assert es.exists(
        index=annotation_index, id=get_node_id("annotation-approved-center-qc-failed")
    )


@pytest.mark.parametrize(
    "converter", [ActiveGraphIndexBuilder, LegacyGraphIndexBuilder]
)
def test_unexpected_properties(
    setup_test, init_indexd, converter, make_gdc_es, patched_demographic
):
    gdces = make_gdc_es(init_indexd, converter)
    gdces.go()
    assert len(get_all_indices(setup_test)) == len(gdces.index_names) + 1


@pytest.mark.parametrize(
    "converter", [ActiveGraphIndexBuilder, LegacyGraphIndexBuilder]
)
def test_gdc_elasticsearch_with_audit_disabled(
    setup_test, init_indexd, converter, make_gdc_es
):
    gdces = make_gdc_es(init_indexd, converter, audit=False)
    gdces.go()

    assert len(get_all_indices(setup_test)) == len(gdces.index_names)


@pytest.mark.parametrize(
    "converter", [ActiveGraphIndexBuilder, LegacyGraphIndexBuilder]
)
def test_doesnt_delete_file_with_derived_files(
    setup_test, init_indexd, converter, pg_driver, derived_file, make_gdc_es
):
    gdces = make_gdc_es(init_indexd, converter)
    gdces.go()

    assert len(get_all_indices(setup_test)) == len(gdces.index_names) + 1

    with pg_driver.session_scope():
        # verify that the to_delete file did not get deleted
        node = pg_driver.nodes(File).get(get_node_id("to-delete-file"))
        assert node
        # verify the filename is correct
        assert init_indexd.get(node.node_id).file_name == "a_file_to_be_deleted.txt"


@pytest.mark.parametrize("replicas, shards", [(0, 1), (2, 6)])
def test_index_settings(setup_test, init_indexd, make_gdc_es, replicas, shards):
    """Test configuring settings for an index created by esbuild."""
    gdces = make_gdc_es(
        indexd_client=init_indexd,
        converter=ActiveGraphIndexBuilder,
        index_replicas=replicas,
        index_shards=shards,
    )
    gdces.go()

    all_indices = get_all_indices(setup_test)
    assert len(all_indices) == len(gdces.index_names) + 1

    for index in gdces.index_names.values():
        verify_index_settings(
            es=setup_test, index=index, replicas=replicas, shards=shards
        )


# TT-1053 index redaction
def test_redaction_annotation_indexed(setup_test, init_indexd, make_gdc_es):

    es = setup_test

    gdces = make_gdc_es(init_indexd, ActiveGraphIndexBuilder)
    gdces.go()

    assert not es.exists(  # The case needs to be unindexed
        index=gdces.index_names["case"],
        id=get_node_id("redaction-case-released"),
    )
    assert es.exists(
        index=gdces.index_names["annotation"],
        id=get_node_id("redaction-annotation"),
    )

    # Check subject withdrew consent case and redaction still show up
    assert es.exists(
        index=gdces.index_names["case"],
        id=get_node_id("withdrew-consent-case-released"),
    )
    assert es.exists(
        index=gdces.index_names["annotation"],
        id=get_node_id("withdrew-consent-annotation"),
    )

    # Check released-rescinded redaction doesn't show up
    assert es.exists(
        index=gdces.index_names["case"],
        id=get_node_id("released-rescinded-case"),
    )
    assert not es.exists(
        index=gdces.index_names["annotation"],
        id=get_node_id("released-rescinded-annotation"),
    )


def get_graph_counts(es, index_prefix, index_types):
    counts = {}
    for index_type in index_types:
        index = "{}_{}".format(index_prefix, index_type)
        r = es.count(index=index)
        counts[index_type] = r["count"]

    return counts


def get_modified_mapping():
    mappings = builder.ActiveESMapper.get_case_es_mapping().to_dict()
    mappings["properties"]["project"]["properties"]["project_id"]["type"] = "text"

    return mappings


def test_reindex_change_field_type(setup_test, init_indexd, make_gdc_es):
    gdc_es = make_gdc_es(init_indexd, ActiveGraphIndexBuilder)
    aggs_query = {
        "aggs": {"projects": {"terms": {"field": "project.project_id", "size": 100}}},
        "_source": False,
        "size": 0,
    }
    es = setup_test
    case_index = "gdc_es_test_case"

    # We have to use the old service to set up all of the test indices
    gdc_es.go(roll_alias=False)
    # project.project_id is a keyword type and aggregations are possible
    aggs_resp1 = es.search(index=case_index, body=aggs_query)

    # get counts before reindexing
    counts1 = get_graph_counts(es, "gdc_es_test", ("case",))

    # make sure that the number of cases is as expected
    case_count = sum(
        bucket["doc_count"]
        for bucket in aggs_resp1["aggregations"]["projects"]["buckets"]
    )
    assert case_count == counts1["case"]

    new_index_prefix = "new_gdc_es_test"
    new_case_index = new_index_prefix + "_case"
    modified_mapping = get_modified_mapping()
    settings = builder.ActiveESMapper.index_settings()

    with mock.patch(
        "esbuild.graph.active.builder.ActiveESMapper"
    ) as mapper, futures.ThreadPoolExecutor() as executor:
        task_factory = gdc_elasticsearch.TaskFactory(es, executor)
        progress_manager = reindexing.TaskProgressManager(
            task_factory, mock.MagicMock()
        )
        reindexer = reindexing.Reindexer(
            es, mock.MagicMock(), progress_manager, mock.MagicMock(), executor
        )

        mapper.get_case_es_mapping.return_value = modified_mapping
        mapper.get_file_es_mapping.return_value = {}
        mapper.index_settings.return_value = settings

        reindexer.reindex(case_index, new_case_index)

    counts2 = get_graph_counts(es, new_index_prefix, ("case",))

    # Make sure that the counts are still the same
    assert counts1 == counts2

    # The following should fail, because ES doesn't do aggs on 'text' fields
    error_message = r".*Text fields are not optimised for operations that require "
    "per-document field data like aggregations and sorting, so these operations are "
    "disabled by default\. Please use a keyword field instead\. Alternatively, set "
    "fielddata=true on \[project.project_id] in order to load field data by uninverting "
    "the inverted index\. Note that this can use significant memory.*"

    with pytest.raises(elasticsearch.RequestError, match=error_message):
        es.search(index=new_case_index, body=aggs_query)


@pytest.mark.usefixtures("setup_test")
def test_build_from_readonly(ro_pg_driver, init_indexd, es_client):
    """
    Make sure that no write attempts are made during ESBuild run and also that
    correct indices/aliases were created
    """

    # Making sure ES is empty
    assert len(es_client.indices.get_alias()) == 0

    gdc_es = GDCElasticsearch(
        ActiveGraphIndexBuilder,
        init_indexd,
        es=es_client,
        pg_driver=ro_pg_driver,
        index_prefix="graph_from_readonly",
        index_alias_prefix="graph_alias",
    )
    gdc_es.go()

    all_aliases = es_client.indices.get_alias()
    graph_aliases = es_client.indices.get_alias("graph_from_*")

    expected_names = gdc_es.index_names.values()

    assert set(expected_names) <= all_aliases.keys(), all_aliases
    assert "build_metadata" in all_aliases, all_aliases
    assert graph_aliases.keys() == set(gdc_es.index_names.values())

    for index_type, index_name in gdc_es.index_names.items():
        index_info = all_aliases[index_name]
        expected_alias = gdc_es.index_aliases[index_type]

        assert expected_alias in index_info["aliases"], index_info


@pytest.mark.usefixtures("setup_test")
def test_build_index_no_alias(pg_driver, init_indexd, es_client):
    """Make sure no alias was set if roll_alias was False"""

    # Making sure ES is empty
    assert len(es_client.indices.get_alias()) == 0

    gdc_es = GDCElasticsearch(
        ActiveGraphIndexBuilder,
        init_indexd,
        es=es_client,
        pg_driver=pg_driver,
        index_prefix="graph_from_readonly",
        index_alias_prefix="graph_alias",
    )
    gdc_es.go(roll_alias=False)

    graph_aliases = es_client.indices.get_alias("graph_from_*")

    assert graph_aliases.keys() == set(gdc_es.index_names.values())

    for index_name, index_info in graph_aliases.items():
        assert index_info["aliases"] == {}


@pytest.mark.usefixtures("setup_test")
def test_reindex_per_project(
    pg_driver, es_client: elasticsearch.Elasticsearch, init_indexd
):
    gdc_es = GDCElasticsearch(
        ActiveGraphIndexBuilder,
        init_indexd,
        es=es_client,
        pg_driver=pg_driver,
        index_prefix="reindex_test",
    )
    gdc_es.go(roll_alias=False)

    es_client.index(
        index="reindex_test_project",
        body={"project_id": "GDC-MISC"},
        id="GDC-MISC",
    )
    es_client.index(
        index="reindex_test_project",
        body={"project_id": "FALSE"},
        id="FALSE",
    )
    es_client.index(
        index="reindex_test_case",
        body={"project": {"project_id": "GDC-MISC"}, "case_id": "gdc-misc-case-1"},
        id="gdc-misc-case-1",
    )
    es_client.index(
        index="reindex_test_case",
        body={"project": {"project_id": "GDC-MISC"}, "case_id": "gdc-misc-case-2"},
        id="gdc-misc-case-2",
    )
    es_client.indices.refresh(index=["reindex_test_case", "reindex_test_project"])

    with futures.ThreadPoolExecutor() as executor:
        task_factory = gdc_elasticsearch.TaskFactory(es_client, executor)
        progress_manager = reindexing.TaskProgressManager(
            task_factory, mock.MagicMock()
        )
        reindexer = reindexing.Reindexer(
            es_client,
            utils.ReleaseHelper(es_client, "build_metadata", True),
            progress_manager,
            mock.MagicMock(),
            executor,
        )

        reindexer.reindex(
            old_index="reindex_test",
            new_index="gdc_misc",
            index_types=["case", "project"],
            project_ids=["GDC-MISC"],
        )

    case_results = es_client.search(index="gdc_misc_case")
    project_results = es_client.search(index="gdc_misc_project")

    assert case_results["hits"]["total"]["value"] == 2
    assert project_results["hits"]["total"]["value"] == 1


def test_es_with_gencode(pg_driver, setup_test, apply_gencode_to_indexd, make_gdc_es):
    es = setup_test
    gdc_es = make_gdc_es(
        indexd_client=apply_gencode_to_indexd,
        converter=ActiveGraphIndexBuilder,
        gencode_version="v22",
    )
    gdc_es.go()

    all_indices = get_all_indices(setup_test)
    expected_indices = set(gdc_es.index_names.values()) | {"build_metadata"}
    assert set(all_indices) == expected_indices

    file_index = gdc_es.index_names["file"]
    with pg_driver.session_scope():
        sea_0 = pg_driver.nodes().props(submitter_id="gv_secondary_exp_1").one()
        assert not es.exists(index=file_index, id=sea_0.node_id)
