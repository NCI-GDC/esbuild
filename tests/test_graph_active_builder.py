# -*- coding: utf-8 -*-
"""
test_graph_index.py
----------------------------------

Test the builder for graph ES index

"""


from gdcdatamodel import models as md
from jsonpath_rw import parse

import pytest

from conftest import (
    Index,
    _graph,
)

from esbuild.graph.active.builder import (
    ActiveGraphIndexBuilder,
    list_product,
    subtree_paths_to_file,
    get_case_to_file_paths,
)

from esbuild.graph.legacy.builder import (
    LegacyGraphIndexBuilder,
)


# ======================================================================
# Fixtures

@pytest.fixture(scope="module")
def index():
    builder = ActiveGraphIndexBuilder(_graph)
    builder.cache_database()
    index = builder.denormalize_all()
    return Index._make(index)


@pytest.fixture
def aligned_reads(index):
    return [d for d in index.files if d['type'] == 'aligned_reads']


# ======================================================================
# Tests

@pytest.mark.parametrize('a,b,expected', [
    ([['a', 'b'], ['-', '#']],
     [range(0, 2), range(2, 4), range(4, 8)],
     [['a', 'b', 0, 1],
      ['a', 'b', 2, 3],
      ['a', 'b', 4, 5, 6, 7],
      ['-', '#', 0, 1],
      ['-', '#', 2, 3],
      ['-', '#', 4, 5, 6, 7]])
])
def test_list_product(a, b, expected):
    assert list_product(a, b) == expected


@pytest.mark.parametrize('node,expected', [
    (md.RnaExpressionWorkflow, ['exon_expression']),
    (md.RnaExpressionWorkflow, ['gene_expression']),
    (md.ReadGroup, [
        "submitted_aligned_reads",
        "alignment_cocleaning_workflow",
        "aligned_reads",
        "somatic_mutation_calling_workflow",
        "simple_somatic_mutation",
    ]),
])
def test_subtree_paths_to_file_subset(node, expected):
    assert expected in subtree_paths_to_file(node)


def test_subtree_paths_to_file_expecting_empty():
    assert subtree_paths_to_file(md.Annotation) == []


@pytest.mark.parametrize('path', LegacyGraphIndexBuilder.case_to_file_paths)
def test_get_case_to_file_paths_contains_legacy(path):
    assert path in get_case_to_file_paths()


@pytest.mark.parametrize('prefix', [
    ['sample', 'aliquot', 'read_group'],
    ['sample', 'portion', 'analyte', 'aliquot', 'read_group'],
])
def test_get_case_to_file_paths_contains_expected_path(prefix):
    assert prefix + [
        "submitted_aligned_reads",
        "alignment_cocleaning_workflow",
        "aligned_reads",
        "somatic_mutation_calling_workflow",
        "simple_somatic_mutation",
    ] in get_case_to_file_paths()


@pytest.mark.parametrize('doc_type,path,contained_keys,count', [
    ('cases', '[*].project', {'project_id'}, 1),
    ('cases', '[*].samples.[*]', {'sample_id'}, 2),
    ('cases', '[*].samples.[*].portions.[*]', {'portion_id'}, 2),
    ('cases', '[*].samples.[*].portions.[*].analytes.[*]', {'analyte_id'}, 5),
    ('cases', '[*].samples.[*].portions.[*].analytes.[*].aliquots.[*]', {'aliquot_id'}, 11),
    ('files', '[*]', {'file_size'}, 5),
])
def test_path_keys(index, doc_type, path, contained_keys, count):
    results = parse(path).find(getattr(index, doc_type))
    assert len(results) == count
    for doc in results:
        assert not contained_keys - set(doc.value.keys())


@pytest.mark.parametrize('doc_type,path,expected,count', [
    ('cases', '[*].demographic.year_of_birth', 1951, 1),
    ('cases', '[*].diagnoses.[*].age_at_diagnosis', 47, 1),
    ('cases', '[*].diagnoses.[*].treatments.[*].treatment_or_therapy', 'unknown', 1),
    ('cases', '[*].exposures.[*].cigarettes_per_day', 10, 1),
    ('cases', '[*].family_histories.[*].relationship_primary_diagnosis', 'Married', 1),
    ('files', '[*].index_files.[*].file_name', 'test_file.bam.bai', 1),
])
def test_path_values(index, doc_type, path, expected, count):
    results = parse(path).find(getattr(index, doc_type))
    assert len(results) == count
    for actual in results:
        assert actual.value == expected


def test_submitted_aligned_reads_no_analysis(graph, index):
    f_ids = {n.node_id for n in graph.nodes(md.SubmittedAlignedReads).all()}
    docs = [d for d in index.files if d['file_id'] in f_ids]
    for doc in docs:
        assert 'analysis' not in doc


def test_submitted_aligned_reads_has_downstream_analysis(graph, index):
    f_ids = {n.node_id for n in graph.nodes(md.SubmittedAlignedReads).all()}
    docs = [d for d in index.files if d['file_id'] in f_ids]
    for doc in docs:
        assert doc.get('downstream_analysis')
        assert doc['downstream_analysis'].get('output_files')


def test_aligned_reads_analysis_input_files(index, aligned_reads):
    for doc in aligned_reads:
        assert doc['analysis'].get('input_files')
        assert len(doc['analysis']['input_files']) == 2
        for f in doc['analysis']['input_files']:
            assert f['file_name']
            assert f['data_format']


def test_aligned_reads_analysis_read_group(index, aligned_reads):
    for doc in aligned_reads:
        assert doc['analysis'].get('metadata')
        assert doc['analysis']['metadata']['read_groups']
        for rg in doc['analysis']['metadata']['read_groups']:
            assert rg['read_group_id']
