# -*- coding: utf-8 -*-
"""
Tests the GDC Elasticsearch interaction for active and legacy
indices.

"""
import json
import os

import pytest
from gdcdatamodel.models import File, Demographic
from elasticsearch import Elasticsearch
from elasticsearch.exceptions import AuthorizationException

from esbuild.gdc_elasticsearch import GDCElasticsearch
from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder
from tests import data
from tests.conftest import (
    PG_HOST,
    PG_USER,
    PG_PASSWORD,
    PG_DATABASE,
    _graph,
    ES_HOST,
    ES_PORT,
    cleanup_indices,
    get_all_indices,
)
from tests.data import get_node_id

GRAPH_INDEX_DOC_TYPES = ['project', 'case', 'annotation', 'file']


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


def get_graph_counts(es, index, doc_types):
    counts = {}
    for dt in doc_types:
        r = es.count(index=index, doc_type=dt)
        counts[dt] = r['count']

    return counts


def test_reindex_doc_types(setup_test, init_indexd):
    gdc_es = make_gdc_es(init_indexd, ActiveGraphIndexBuilder)
    gdc_es.go()

    es = setup_test

    new_index = 'new_{}'.format(gdc_es.index_name)

    gdc_es.reindex(gdc_es.index_name, new_index, types='annotation')

    counts1 = get_graph_counts(es, gdc_es.index_name, GRAPH_INDEX_DOC_TYPES)
    counts2 = get_graph_counts(es, new_index, GRAPH_INDEX_DOC_TYPES)

    assert counts1['annotation'] == counts2['annotation']
    assert all(c != 0 for _, c in counts1.items())
    assert all(c == 0 for dtype, c in counts2.items() if dtype != 'annotation')


def test_reindex_change_field_type(setup_test, init_indexd):
    gdc_es = make_gdc_es(init_indexd, ActiveGraphIndexBuilder)
    gdc_es.go()

    aggs_query = {
        'aggs': {'projects': {'terms': {'field': 'project.project_id'}}},
        '_source': False,
        'size': 0,
    }

    es = setup_test

    # project.project_id is a keyword type and aggregations are possible
    aggs_resp1 = es.search(index=gdc_es.index_name, doc_type='case',
                           body=aggs_query)

    # get counts before reindexing
    counts1 = get_graph_counts(es, gdc_es.index_name, GRAPH_INDEX_DOC_TYPES)

    # make sure that the number of cases is as expected
    assert sum([
        bucket['doc_count']
        for bucket in aggs_resp1['aggregations']['projects']['buckets']
    ]) == counts1['case']

    new_index = 'new_{}'.format(gdc_es.index_name)

    # Lets modify mappings for project_id and make it a 'text' type, this will
    # disable ability to run the previous aggregation
    index_settings = gdc_es.converter.mapper.index_settings()
    mappings = {
        'file': gdc_es.converter.mapper.get_file_es_mapping().to_dict(),
        'case': gdc_es.converter.mapper.get_case_es_mapping().to_dict(),
        'project': gdc_es.converter.mapper.get_project_es_mapping().to_dict(),
        'annotation': gdc_es.converter.mapper.get_annotation_es_mapping().to_dict(),
    }

    # Change project.project_id.type to 'text'
    mappings['project']['properties']['project_id']['type'] = 'text'
    mappings['case']['properties']['project']['properties']['project_id']['type'] = 'text'
    mappings['file']['properties']['cases']['properties']['project']['properties']['project_id']['type'] = 'text'
    mappings['annotation']['properties']['project']['properties']['project_id']['type'] = 'text'

    index_settings.update({'mappings': mappings})

    gdc_es.reindex(gdc_es.index_name, new_index, index_settings=index_settings)

    counts2 = get_graph_counts(es, new_index, GRAPH_INDEX_DOC_TYPES)

    # Make sure that the counts are still the same
    assert counts1 == counts2

    # The following should fail, because ES doesn't do aggs on 'text' fields
    try:
        _ = es.search(index=new_index, doc_type='case', body=aggs_query)
    except Exception as e:
        assert 'project.project_id' in str(e)
        assert 'use a keyword field instead' in str(e)
    else:
        raise AssertionError("No exception raised")
