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
    raise_test_error,
    Index,
    _graph,
)

from esbuild.graph.active.builder import (
    ActiveGraphIndexBuilder,
    list_product,
    subtree_paths_to_file,
    get_case_to_file_paths,
)


# ======================================================================
# Fixtures

@pytest.fixture(scope="module")
def index():
    builder = ActiveGraphIndexBuilder(_graph)
    builder.cache_database()
    index = builder.denormalize_all()
    return Index._make(index)


@pytest.fixture()
def builder():
    return ActiveGraphIndexBuilder(_graph)


@pytest.fixture
def aligned_reads(index):
    return [d for d in index.files if d['type'] == 'aligned_reads']


@pytest.fixture
def simple_somatic_mutations(index):
    return [d for d in index.files if d['type'] == 'simple_somatic_mutation']


@pytest.fixture(scope="session")
def mappings():
    mapper = ActiveGraphIndexBuilder.mapper
    return {
        'file': mapper.get_file_es_mapping(),
        'annotation': mapper.get_annotation_es_mapping(),
        'case': mapper.get_case_es_mapping(),
        'project': mapper.get_project_es_mapping(),
    }


# ======================================================================
# Tests

@pytest.mark.parametrize('mapping,path', [
    ('file', 'properties.file_name.fields.analyzed.index'),
    ('file', 'properties.analysis.properties.input_files.properties.data_category'),
    ('file', 'properties.analysis.properties.input_files.properties.file_id.fields.analyzed.index'),
    ('file', 'properties.downstream_analyses.properties.output_files.properties.data_category'),
    ('file', 'properties.downstream_analyses.properties.output_files.properties.file_id.fields.analyzed.index'),
    ('case', 'properties.submitter_id.fields.analyzed.index'),
    ('project', 'properties.name.fields.analyzed.index'),
    ('annotation', 'properties.entity_id.fields.analyzed.index'),
])
def test_mapping_contains(mappings, mapping, path):
    results = parse(path).find(mappings[mapping])
    assert len([r.value for r in results]) == 1


@pytest.mark.parametrize('mapping,path', [
    ('file', 'properties.uploaded_datetime'),
    ('annotation', 'properties.creator'),
])
def test_mapping_does_not_contain(mappings, mapping, path):
    assert len(parse(path).find(mappings[mapping])) == 0


@pytest.mark.parametrize('mapping,path,expected', [
    ('file', 'properties.downstream_analyses.type', ['nested']),
])
def test_mapping_value_in(mappings, mapping, path, expected):
    results = parse(path).find(mappings[mapping])
    for r in results:
        assert r.value in expected


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


@pytest.mark.parametrize('path', [
    ['case', 'sample', 'portion', 'analyte', 'aliquot'],
    ['case', 'sample', 'aliquot'],
])
def test_get_case_to_file_paths_is_absent(path):
    assert path not in get_case_to_file_paths()


@pytest.mark.parametrize('doc_type,path', [
    ('cases', '[*].clinical'),
    ('annotations', '[*].creator'),
])
def test_path_is_absent(index, doc_type, path):
    assert not parse(path).find(getattr(index, doc_type))


@pytest.mark.parametrize('path', [
    'sample.portion.analyte.aliquot.read_group.submitted_unaligned_reads',
    'sample.portion.analyte.aliquot.read_group.submitted_unaligned_reads.alignment_workflow.aligned_reads',
])
def test_get_case_to_file_path_is_present(path):
    assert path.split('.') in get_case_to_file_paths()


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


@pytest.mark.parametrize('doc_type,path,count', [
    ('cases', '[*].project.project_id', 1),
    ('cases', '[*].samples.[*].sample_id', 2),
    ('cases', '[*].samples.[*].portions.[*].portion_id', 2),
    ('cases', '[*].samples.[*].portions.[*].analytes.[*].analyte_id', 5),
    ('cases', '[*].samples.[*].portions.[*].analytes.[*].aliquots.[*].aliquot_id', 11),
    ('files', '[*].(file_size | file_name | file_id)', 2 * 3),  # there should be two files
    ('files', '[*].uploaded_datetime', 0),
])
def test_path_count(index, doc_type, path, count):
    results = parse(path).find(getattr(index, doc_type))
    assert len(results) == count


@pytest.mark.parametrize('doc_type,path,expected,count', [
    ('projects', '[*].summary.[*].data_categories.[*].file_count', [1, 3], 2),
    ('projects', '[*].summary.[*].data_categories.[*].data_category', ['Simple Nucleotide Variation', 'Sequencing Data'], 2),
    ('cases', '[*].summary.[*].data_categories.[*].file_count', [1, 3], 2),
    ('cases', '[*].demographic.year_of_birth', [1951], 1),
    ('cases', '[*].diagnoses.[*].age_at_diagnosis', [47], 1),
    ('cases', '[*].diagnoses.[*].treatments.[*].treatment_or_therapy', ['unknown'], 1),
    ('cases', '[*].exposures.[*].cigarettes_per_day', [10], 1),
    ('cases', '[*].family_histories.[*].relationship_primary_diagnosis', ['Married'], 1),
    ('files', '[*].index_files.[*].file_name', ['index-file-2.bam.bai'], 1),
    ('files', '[*].analysis.[*].input_files.[*].data_category', ['Sequencing Data'], 1),
    ('files', '[*].downstream_analyses.[*].output_files.[*].data_category', ['Simple Nucleotide Variation'], 1),
    ('files', '[*].downstream_analyses.[*].output_files.[*].state', ['submitted'], 1),
    ('files', '[*].type.[*]', ['simple_somatic_mutation', 'aligned_reads'], 2),
])
def test_path_value_in(index, doc_type, path, expected, count):
    results = parse(path).find(getattr(index, doc_type))
    assert len([r.value for r in results]) == count
    for actual in results:
        assert actual.value in expected


def test_submitted_aligned_reads_no_analysis(graph, index):
    f_ids = {n.node_id for n in graph.nodes(md.SubmittedAlignedReads).all()}
    docs = [d for d in index.files if d['file_id'] in f_ids]
    for doc in docs:
        assert 'analysis' not in doc


def test_submitted_aligned_reads_has_downstream_analyses(graph, index):
    f_ids = {n.node_id for n in graph.nodes(md.SubmittedAlignedReads).all()}
    docs = [d for d in index.files if d['file_id'] in f_ids]
    for doc in docs:
        assert doc.get('downstream_analyses')
        assert doc['downstream_analyses'].get('output_files')


def test_aligned_reads_analysis_input_files(index, simple_somatic_mutations):
    for doc in simple_somatic_mutations:
        assert doc['analysis'].get('input_files')
        assert len(doc['analysis']['input_files']) == 1
        for f in doc['analysis']['input_files']:
            assert f['file_name']
            assert f['data_format']


def test_aligned_reads_analysis_read_group(index, aligned_reads):
    for doc in aligned_reads:
        assert doc['analysis'].get('metadata')
        assert doc['analysis']['metadata']['read_groups']
        for rg in doc['analysis']['metadata']['read_groups']:
            assert rg['read_group_id']


def test_project_file_counts(index, builder, monkeypatch):
    monkeypatch.setattr(builder, 'error', raise_test_error)
    for project in index.projects:
        builder.validate_project_file_counts(project, index.files)


def test_data_category_count(index, builder, monkeypatch):
    monkeypatch.setattr(builder, 'error', raise_test_error)
    for case in index.cases:
        builder.verify_data_category_count(case)
