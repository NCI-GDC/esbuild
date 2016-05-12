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
)

# ======================================================================
# Fixtures

@pytest.fixture(scope='module')
def index():
    builder = ActiveGraphIndexBuilder(_graph)
    builder.cache_database()
    index = builder.denormalize_all()
    return Index._make(index)


@pytest.fixture
def cached_builder(scope='module'):
    builder = ActiveGraphIndexBuilder(_graph)
    builder.cache_database()
    return builder


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
    ('case', '_meta.descriptions'),
    ('case', '_meta.descriptions."cases.samples.portions.analytes.a260_a280_ratio"'),
    ('case', 'properties.submitter_id.fields.analyzed.index'),
    ('project', 'properties.name.fields.analyzed.index'),
    ('project', '_meta.descriptions'),
    ('annotation', 'properties.entity_id.fields.analyzed.index'),
    ('annotation', '_meta.descriptions'),
])
def test_mapping_contains(mappings, mapping, path):
    results = parse(path).find(mappings[mapping])
    assert len([r.value for r in results]) == 1


@pytest.mark.parametrize('mapping,path', [
    ('file', 'properties.uploaded_datetime'),
    ('file', 'properties.project_id'),
    ('file', 'properties.cases.properties.samples.properties.project_id'),
    ('case', 'properties.project_id'),
    ('case', 'properties.metadata_files'),
    ('case', 'properties.samples.properties.aliquots'),
    ('case', 'properties.samples.properties.portions.properties.project_id'),
    ('annotation', 'properties.creator'),
    ('annotation', 'properties.project_id'),
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
def test_case_to_file_paths_is_absent(path):
    assert path not in ActiveGraphIndexBuilder.case_to_file_paths


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
    assert path.split('.') in ActiveGraphIndexBuilder.case_to_file_paths


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
    ] in ActiveGraphIndexBuilder.case_to_file_paths


@pytest.mark.parametrize('doc_type,path,count', [
    ('cases', '[*].project.project_id', 1),
    ('cases', '[*].project_id', 0),
    ('cases', '[*].metadata_files', 0),
    ('cases', '[*].samples.[*].project_id', 0),
    ('cases', '[*].samples.[*].portions.[*].analytes.[*].aliquots.[*].project_id', 0),
    ('cases', '[*].samples.[*].sample_id', 2),
    ('cases', '[*].samples.[*].portions.[*].portion_id', 2),
    ('cases', '[*].samples.[*].portions.[*].analytes.[*].analyte_id', 5),
    ('cases', '[*].samples.[*].portions.[*].analytes.[*].aliquots.[*].aliquot_id', 12),
    ('files', '[*].(file_size | file_name | file_id)', 7 * 3),  # there should be 7 files
    ('files', '[*].uploaded_datetime', 0),
    ('files', '[*].project_id', 0),
    ('files', '[*].cases.[*].project_id', 0),
    ('annotations', '[*].project_id', 0),
    ('annotations', '[*].annotation_id', 1),
    ('files', '[*].associated_entities.[*].entity_type', 7),
])
def test_path_count(index, doc_type, path, count):
    results = parse(path).find(getattr(index, doc_type))
    assert len(results) == count


@pytest.mark.parametrize('doc_type,path,count,expected', [
    ('projects', '[*].summary.[*].data_categories.[*].file_count',
     5, {1, 3}),
    ('projects', '[*].summary.[*].data_categories.[*].data_category',
     5, {'Simple Nucleotide Variation',
         'Sequencing Data',
         'Biospecimen',
         'Clinical',
         'Copy Number Variation'}),
    ('cases', '[*].summary.[*].data_categories.[*].file_count',
     5, {1, 3}),
    ('cases', '[*].demographic.year_of_birth',
     1, {1951}),
    ('cases', '[*].diagnoses.[*].age_at_diagnosis',
     1, {47}),
    ('cases', '[*].diagnoses.[*].treatments.[*].treatment_or_therapy',
     1, {'unknown'}),
    ('cases', '[*].exposures.[*].cigarettes_per_day',
     1, {10}),
    ('cases', '[*].family_histories.[*].relationship_primary_diagnosis',
     1, {'Married'}),
    ('cases', '[*].files.[*].analysis.[*].metadata.[*].read_groups.[*].read_group_id',
     5, {'64f66bc3-1cee-41d7-ae86-cb443e84f30e',
         'bd4d1c78-c448-4bbf-8348-a77f3786c648'}),
    ('files', '[*].index_files.[*].file_name',
     1, {'index-file-2.bam.bai'}),
    ('files', '[*].analysis.[*].input_files.[*].data_category',
     3, {'Sequencing Data', 'Simple Nucleotide Variation'}),
    ('files', '[*].downstream_analyses.[*].output_files.[*].access',
     3, {'controlled'}),
    ('files', '[*].analysis.[*].input_files.[*].access',
     3, {'controlled'}),
    ('files', '[*].downstream_analyses.[*].output_files.[*].data_category',
     3, {'Simple Nucleotide Variation'}),
    ('files', '[*].downstream_analyses.[*].output_files.[*].state',
     3, {'submitted'}),
    ('files', '[*].type.[*]',
     7, {'simple_somatic_mutation',
         'aligned_reads',
         'biospecimen_supplement',
         'clinical_supplement',
         'copy_number_segment',
         'annotated_somatic_mutation'}),
])
def test_path_value_set_equals(index, doc_type, path, expected, count):
    results = parse(path).find(getattr(index, doc_type))
    actual = {r.value for r in results}
    assert actual == expected
    assert len(results) == count


def test_no_submitted_aligned_reads(graph, index):
    f_ids = {n.node_id for n in graph.nodes(md.SubmittedAlignedReads).all()}
    assert not [d for d in index.files if d['file_id'] in f_ids]


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


def test_case_summary_data_category_counts(index):
    for case in index.cases:
        actual_counts = {}
        for f in case['files']:
            category = f['data_category']
            actual_counts[category] = actual_counts.get(category, 0) + 1

        for entry in case['summary']['data_categories']:
            category, count = entry['data_category'], entry['file_count']
            assert category in actual_counts
            assert actual_counts[category] == count, category


def test_case_summary_file_counts(index):
    for case in index.cases:
        actual_count = len([
            f for f in index.files
            if f['cases'][0]['case_id'] == case['case_id']
        ])
        assert actual_count == case['summary']['file_count']


@pytest.mark.parametrize('label,path', [
    ('submitted_aligned_reads', ['read_group']),
    ('aligned_reads', ['alignment_workflow', 'submitted_aligned_reads', 'read_group']),
])
def test_file_to_read_group_paths(label, path):
    assert path in ActiveGraphIndexBuilder.file_to_read_group_paths[label]


def test_get_file_read_groups(graph, index):
    f_ids = {n.node_id for n in graph.nodes(md.SubmittedAlignedReads).all()}
    assert not [d for d in index.files if d['file_id'] in f_ids]


@pytest.mark.parametrize('cls,count', [
    (md.AlignmentWorkflow, 1),
    (md.SomaticMutationCallingWorkflow, 1),
])
def test_get_analysis_read_groups(graph, cached_builder, cls, count):
    for workflow in graph.nodes(cls).all():
        read_groups = list(cached_builder.get_analysis_read_groups(workflow))
        assert len(read_groups) == count
        for read_group in read_groups:
            assert read_group.label == 'read_group'


@pytest.mark.parametrize('cls,count', [
    (md.AlignedReads, 1),
    (md.CopyNumberSegment, 1),
    (md.RunMetadata, 1),
    (md.ExperimentMetadata, 1),
])
def test_get_file_associated_entities(graph, cached_builder, cls, count):
    for node in graph.nodes(cls).all():
        if cached_builder.is_file_indexed(node):
            entities = list(cached_builder.get_file_associated_entities(node))
            assert len(entities) == count


@pytest.mark.parametrize('cls,count', [
    (md.BiospecimenSupplement, 0),
    (md.ClinicalSupplement, 0),
], scope='module')
def test_add_related_files(graph, cached_builder, cls, count):
    for node in graph.nodes(cls).all():
        if cached_builder.is_file_indexed(node):
            doc = {}
            cached_builder.add_related_files(node, doc)
            assert len(doc.get('metadata_files', [])) == count


@pytest.mark.parametrize('cls,has_archive', [
    (md.BiospecimenSupplement, True),
    (md.ClinicalSupplement, True),
    (md.AlignedReads, False),
    (md.CopyNumberSegment, False),
], scope='module')
def test_add_archive(graph, cached_builder, cls, has_archive):
    for node in graph.nodes(cls).all():
        if cached_builder.is_file_indexed(node):
            doc = {}
            cached_builder.add_archives(node, doc)
            assert ('archive' in doc) == has_archive


def test_aligned_reads_associated_entities(graph, index):
    aligned_reads_docs = [f for f in index.files if f['type'] == 'aligned_reads']
    assert aligned_reads_docs
    for f in aligned_reads_docs:
        assert len(f['associated_entities']) == 1
