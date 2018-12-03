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
)


@pytest.fixture(scope='function')
def setup_test():
    es = Elasticsearch("localhost")
    delete_all_indices(es)
    data.insert(_graph)

    os.environ["PG_HOST"] = PG_HOST
    os.environ["PG_USER"] = PG_USER
    os.environ["PG_PASS"] = PG_PASSWORD
    os.environ["PG_NAME"] = PG_DATABASE
    os.environ["ELASTICSEARCH_HOST"] = "localhost"

    yield es
    delete_all_indices(es)


def get_all_indices(es):
    return (
        # closed indices:
        es.cluster.state()['blocks'].get('indices', {}).keys() +
        # opened indices:
        es.indices.stats()['indices'].keys()
    )


def delete_all_indices(es):
    for index in get_all_indices(es):
        es.indices.delete(index)


def make_gdc_es(indexd_client, converter):
    return GDCElasticsearch(
        converter_class=converter,
        indexd_client=indexd_client,
        index_name="test_{}".format(converter.__name__.lower()),
    )


@pytest.mark.parametrize('converter,index_alias', [
    (ActiveGraphIndexBuilder, 'gdc_from_graph'),
    (LegacyGraphIndexBuilder, 'gdc_legacy_graph'),
])
def test_basic_es_generate(setup_test, init_indexd, converter, index_alias):
    es = setup_test
    gdces = make_gdc_es(init_indexd, converter)
    gdces.go()
    assert len(es.indices.get_alias()) == 1
    # also verify that the to_delete file is not in the index and
    # got deleted
    with _graph.session_scope():
        assert not es.exists(index=index_alias,
                             doc_type="file",
                             id=get_node_id("to-delete-file"))

    # Test Case exists by id
    with _graph.session_scope():
        assert es.exists(index=index_alias,
                         doc_type="case",
                         id=get_node_id('case-tcga-brca-breast'))


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


def test_doesnt_delete_file_with_derived_files(setup_test, init_indexd):
    gdces = make_gdc_es(init_indexd, ActiveGraphIndexBuilder)
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
