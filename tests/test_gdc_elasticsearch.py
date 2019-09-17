# -*- coding: utf-8 -*-
"""
Tests the GDC Elasticsearch interaction for active and legacy
indices.

"""

from elasticsearch import Elasticsearch
from gdcdatamodel.models import File, Demographic
from elasticsearch.exceptions import AuthorizationException
from esbuild.gdc_elasticsearch import GDCElasticsearch
from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder
from data import get_node_id
from conftest import get_all_indices

import data
import pytest
import json
import os


from conftest import (
    PG_HOST,
    PG_USER,
    PG_PASSWORD,
    PG_DATABASE,
    _graph,
    ES_HOST,
    ES_PORT,
    cleanup_indices,
)


@pytest.fixture
def setup_test(sample_database):
    es = Elasticsearch(hosts=[ES_HOST], port=ES_PORT)

    cleanup_indices(es)

    os.environ["PG_HOST"] = PG_HOST
    os.environ["PG_USER"] = PG_USER
    os.environ["PG_PASS"] = PG_PASSWORD
    os.environ["PG_NAME"] = PG_DATABASE
    os.environ["ELASTICSEARCH_HOST"] = "localhost"

    yield es

    cleanup_indices(es)


def make_gdc_es(indexd_client, converter):
    return GDCElasticsearch(
        converter_class=converter,
        indexd_client=indexd_client,
        index_base="gdc_es_test",
        index_close_thresh=4,
    )


@pytest.mark.parametrize('converter', [ActiveGraphIndexBuilder])
def test_basic_es_generate(setup_test, init_indexd, converter):
    es = setup_test
    gdces = make_gdc_es(init_indexd, converter)
    gdces.go()
    assert len(es.indices.get_alias()) == 1
    # also verify that the to_delete file is not in the index and
    # got deleted
    with _graph.session_scope():
        assert not es.exists(index="gdc_es_test",
                             doc_type="file",
                             id=get_node_id("to-delete-file"))

    # Test Case exists by id
    with _graph.session_scope():
        assert es.exists(index="gdc_es_test",
                         doc_type="case",
                         id=get_node_id('case-tcga-brca-breast'))

    # Test blocking release annotation does not exist in index
    with _graph.session_scope():
        assert not es.exists(
            index='gdc_es_test',
            doc_type='annotation',
            id=get_node_id('block-release-annotation'),
        )
        assert not es.exists(
            index='gdc_es_test',
            doc_type='annotation',
            id=get_node_id('block-release-annotation-released'),
        )
        assert es.exists( # just checking
            index='gdc_es_test',
            doc_type='annotation',
            id=get_node_id('annotation-approved-center-qc-failed'),
        )


@pytest.mark.parametrize('converter', [ActiveGraphIndexBuilder, LegacyGraphIndexBuilder])
def test_unexpected_properties(setup_test, init_indexd, converter):
    with _graph.session_scope() as s:
        demographic = _graph.nodes(Demographic).one()
        s.execute("""
        UPDATE node_demographic
        SET _props = :props
        WHERE node_id = :id
        """, {
            'id': demographic.node_id,
            'props': json.dumps(dict(demographic.props, **{
                'fake_property': True,
            }))
        })

    gdces = make_gdc_es(init_indexd, converter)
    gdces.go()
    assert len(get_all_indices(setup_test)) == 1


@pytest.mark.parametrize('converter', [ActiveGraphIndexBuilder, LegacyGraphIndexBuilder])
def test_doesnt_delete_file_with_derived_files(setup_test, init_indexd, converter):
    gdces = make_gdc_es(init_indexd, converter)
    with _graph.session_scope():
        to_delete_file = _graph.nodes(File).ids(get_node_id("to-delete-file")).one()
        derived_file = data.fuzzed(File, state="live")
        to_delete_file.derived_files = [derived_file]
    gdces.go()
    assert len(get_all_indices(setup_test)) == 1
    with _graph.session_scope():
        # verify that the to_delete file did not get deleted
        node = _graph.nodes(File).get(get_node_id('to-delete-file'))
        assert node
        # verify the filename is correct
        assert init_indexd.get(node.node_id).file_name == "a_file_to_be_deleted.txt"


@pytest.mark.parametrize('converter', [ActiveGraphIndexBuilder, LegacyGraphIndexBuilder])
def test_old_index_cleanup(setup_test, init_indexd, converter):
    for i in range(5):
        gdces = make_gdc_es(init_indexd, converter)
        gdces.go()

    # running the index build five times should delete index 1
    actual_indices = set(get_all_indices(setup_test))
    expected_indices = {"gdc_es_test_2", "gdc_es_test_3", "gdc_es_test_4",
                        "gdc_es_test_5"}
    assert actual_indices == expected_indices, actual_indices

    # index 1 should be deleted, index 2 and 3 should be closed
    for i in range(2, 4):
        with pytest.raises(AuthorizationException):
            setup_test.indices.stats('gdc_es_test_{}'.format(i))


# TT-1053 index redaction
def test_redaction_annotation_indexed(setup_test, init_indexd):

    es = setup_test

    gdces = make_gdc_es(init_indexd, ActiveGraphIndexBuilder)
    gdces.go()

    assert not es.exists(  # The case needs to be unindexed
        index='gdc_es_test',
        doc_type='case',
        id=get_node_id('redaction-case-released'),
    )
    assert es.exists(
        index='gdc_es_test',
        doc_type='annotation',
        id=get_node_id('redaction-annotation'),
    )

    # Check subject withdrew consent case and redaction still show up
    assert es.exists(
        index='gdc_es_test',
        doc_type='case',
        id=get_node_id('withdrew-consent-case-released'),
    )
    assert es.exists(
        index='gdc_es_test',
        doc_type='annotation',
        id=get_node_id('withdrew-consent-annotation'),
    )

    # Check released-rescinded redaction doesn't show up
    assert es.exists(
        index='gdc_es_test',
        doc_type='case',
        id=get_node_id('released-rescinded-case'),
    )
    assert not es.exists(
        index='gdc_es_test',
        doc_type='annotation',
        id=get_node_id('released-rescinded-annotation'),
    )
