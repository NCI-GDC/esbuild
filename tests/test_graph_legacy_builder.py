# -*- coding: utf-8 -*-
"""
test_graph_index.py
----------------------------------

Test the builder for graph ES index

"""

from conftest import Index, _graph
from data import fuzzed
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder
from gdcdatamodel import models as md
from jsonpath_rw import parse

import pytest


def build_index(graph):
    builder = LegacyGraphIndexBuilder(graph)
    builder.cache_database()
    index = builder.denormalize_all()
    return Index._make(index)


# ======================================================================
# Fixtures

@pytest.fixture(scope="module")
def index():
    return build_index(_graph)


# ======================================================================
# Tests


def test_annotation_case_submitter_id(graph):
    case = fuzzed(md.Case)
    annotation = fuzzed(md.Annotation, category='Item flagged DNU')
    with graph.session_scope() as s:
        f = graph.nodes(md.File).ids('live-file').first()
        case.projects = [graph.nodes(md.Project).first()]
        case.files = [f]
        case.annotations = [annotation]
        s.merge(case)

    index = build_index(graph)
    for annotation in index.annotations:
        if annotation['entity_type'] == 'case':
            assert annotation['case_id'] == annotation['entity_id']
            assert annotation['case_submitter_id'] == case.submitter_id


@pytest.mark.parametrize('doc_type,path,count', [
    ('cases', '[*].project.project_id', 1),
    ('cases', '[*].samples.[*].sample_id', 2),
    ('cases', '[*].samples.[*].portions.[*].portion_id', 2),
    ('cases', '[*].samples.[*].portions.[*].analytes.[*].analyte_id', 5),
    ('cases', '[*].samples.[*].portions.[*].analytes.[*].aliquots.[*].aliquot_id', 11),
    ('files', '[*].file_size', 2),
])
def test_path_counts(index, doc_type, path, count):
    results = parse(path).find(getattr(index, doc_type))
    assert len(results) == count



@pytest.mark.parametrize('doc_type,path,expected,count', [
    ('cases', '[*].demographic.year_of_birth', [1951], 1),
    ('cases', '[*].diagnoses.[*].age_at_diagnosis', [47], 1),
    ('cases', '[*].diagnoses.[*].treatments.[*].treatment_or_therapy', ['unknown'], 1),
    ('cases', '[*].exposures.[*].cigarettes_per_day', [10], 1),
    ('cases', '[*].family_histories.[*].relationship_primary_diagnosis', ['Married'], 1),
    ('files', '[*].index_files.[*].file_name', ['test_file.bam.bai'], 1),
    ('files', '[*].type.[*]', ['file'], 2),
])
def test_path_value_in(index, doc_type, path, expected, count):
    results = parse(path).find(getattr(index, doc_type))
    assert len([r.value for r in results]) == count
    for actual in results:
        assert actual.value in expected


def test_omitted_projects(graph):
    builder = LegacyGraphIndexBuilder(graph)
    builder.omitted_projects.add(('TCGA', 'BRCA'))
    builder.cache_database()
    index = Index._make(builder.denormalize_all())
    assert index.cases == []


def test_basic_suppression(graph):
    case = fuzzed(md.Case)
    with graph.session_scope() as s:
        case.projects = [graph.nodes(md.Project).first()]
        file_ = graph.nodes(md.File).subq_path('aliquots').first()
        case.files = [file_]
        case.annotations = [fuzzed(
            md.Annotation,
            classification='Redaction',
            category='General',
        )]
        s.merge(case)

    index = build_index(graph)

    assert case.node_id not in [c["case_id"] for c in index.cases]
    assert 'redacted-file' not in [f["file_id"] for f in index.files]


def test_non_case_suppression(graph):
    annotation = fuzzed(md.Annotation, classification='Redaction')
    with graph.session_scope() as s:
        portion_id = '5b2a99b7-e1a8-4739-acaf-d5f75cc47021'
        portion = graph.nodes(md.Portion).ids(portion_id).one()
        portion.annotations = [annotation]
        sample = portion.samples[0]
        case = sample.cases[0]
        analyte = portion.analytes[0]
        aliquot = analyte.aliquots[0]
        redacted1 = fuzzed(md.File, node_id="redact1", state="live")
        redacted1.portions = [portion]
        redacted2 = fuzzed(md.File, node_id="redact2", state="live")
        redacted2.aliquots = [aliquot]
        s.add(redacted1)
        s.add(redacted2)
    index = build_index(graph)
    case_doc = [c for c in index.cases if c["case_id"] == case.node_id][0]
    sample_doc = [s for s in case_doc["samples"] if s["sample_id"] == sample.node_id][0]
    assert portion.node_id not in [p["portion_id"] for p in sample_doc["portions"]]
    assert "redact1" not in [f["file_id"] for f in index.files]
    assert "redact2" not in [f["file_id"] for f in index.files]


def test_subject_withdrew_consent_is_not_suppressed(graph):
    with graph.session_scope() as s:
        case = graph.nodes(md.Case).props(submitter_id='TCGA-AR-A1AR').one()
        case.annotations = [fuzzed(
            md.Annotation,
            classification='Redaction',
            category='Subject withdrew consent',
        )]

        index = build_index(graph)
        # the case should be there
        assert case.node_id in [c["case_id"] for c in index.cases]
        # the file should be there
        assert "live-file" in [f["file_id"] for f in index.files]


def test_duplicate_classification_only_results_in_warning(graph):
    with graph.session_scope():
        live_file = graph.nodes(md.File).ids('live-file').one()
        exp = (graph.nodes(md.ExperimentalStrategy)
               .prop_in('name', ["WXS", "VALIDATION"]).all())
        live_file.experimental_strategies = exp
    index = build_index(graph)
    # the file should be there
    assert live_file.node_id in [f["file_id"] for f in index.files]


def test_derived_files(graph):
    with graph.session_scope() as s:
        live_file = graph.nodes(md.File).ids('live-file').one()
        fake_center = fuzzed(md.Center)
        live_file.centers = [fake_center]
        related_to_live = live_file.related_files[1]
        derived_file = fuzzed(
            md.File,
            state="live",
            file_name="derived_file.bam",
        )
        derived_file.sysan["source"] = "tcga_exome_alignment"
        live_file.derived_files = [derived_file]
        related_to_derived = fuzzed(
            md.File,
            state="live",
            file_name="derived_file.bam.txt",
        )
        related_to_derived.sysan["source"] = "tcga_exome_alignment"
        derived_file.related_files = [related_to_derived]

    index = build_index(graph)

    # derived_file should be a doc in it's own right, and should
    # have the single correct related file
    derived_file_docs = [
        f for f in index.files
        if f["file_id"] == derived_file.node_id
    ]
    assert len(derived_file_docs) == 1
    derived_file_doc = derived_file_docs[0]
    assert len(derived_file_doc["metadata_files"]) == 1

    assert (
        related_to_derived.node_id in
        [f["file_id"] for f in derived_file_doc["metadata_files"]]
    )
    # ,live_file should just have the one correct related_file
    live_file_doc = [f for f in index.files
                     if f["file_id"] == live_file.node_id][0]
    assert len(live_file_doc["metadata_files"]) == 1
    assert (
        related_to_live.node_id in
        [f["file_id"] for f in live_file_doc["metadata_files"]]
    )
    # test origins are correct
    assert live_file_doc["origin"] == "migrated"
    assert derived_file_doc["origin"] == "harmonized"
    # centers and associated_entities should be the same
    assert live_file_doc["center"] == derived_file_doc["center"]
    assert live_file_doc["associated_entities"] == derived_file_doc["associated_entities"]


def test_non_live_related_files_dont_cause_source_files_in_related(graph):
    with graph.session_scope() as s:
        live_file = graph.nodes(md.File).ids('live-file').one()

        related_to_live = live_file.related_files[1]
        derived_file = fuzzed(
            md.File,
            state="live",
            file_name="derived_file.bam",
        )
        derived_file.sysan["source"] = "tcga_exome_alignment"
        live_file.derived_files = [derived_file]
        related_to_derived = fuzzed(
            md.File,
            state="uploaded",
            file_name="derived_file.txt",
        )
        related_to_derived.sysan["source"] = "tcga_exome_alignment"
        derived_file.related_files = [related_to_derived]

    index = build_index(graph)

    # derived_file should be a doc in it's own right, and should
    # have the single correct related file
    derived_file_docs = [
        f for f in index.files
        if f["file_id"] == derived_file.node_id
    ]
    assert len(derived_file_docs) == 1
    derived_file_doc = derived_file_docs[0]
    assert derived_file_doc.get("metadata_files") is None

    # live_file should just have the one correct related_file
    live_file_docs = [
        f for f in index.files
        if f["file_id"] == live_file.node_id
    ]
    assert len(live_file_docs) == 1
    live_file_doc = live_file_docs[0]
    assert len(live_file_doc["metadata_files"]) == 1

    assert (
        related_to_live.node_id in
        [f["file_id"] for f in live_file_doc["metadata_files"]]
    )
    # test origins are correct
    assert live_file_doc["origin"] == "migrated"
    assert derived_file_doc["origin"] == "harmonized"
