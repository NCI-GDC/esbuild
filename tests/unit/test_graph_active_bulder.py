from pprint import pprint

import pytest
from gdcdatamodel import models as md
from gdcmodels import get_es_models
from jsonpath_rw import parse

from esbuild.graph.active.builder import (
    ActiveGraphIndexBuilder,
    list_product,
    subtree_paths_to_file,
)
from tests.unit.utils import get_dict_paths


@pytest.fixture(scope="session")
def mappings():
    mapper = ActiveGraphIndexBuilder.mapper
    return {
        "file": mapper.get_file_es_mapping().to_dict(),
        "annotation": mapper.get_annotation_es_mapping().to_dict(),
        "case": mapper.get_case_es_mapping().to_dict(),
        "project": mapper.get_project_es_mapping().to_dict(),
    }


def test_include_switch():
    mapper = ActiveGraphIndexBuilder.mapper

    mapping = mapper.get_file_es_mapping(include_case=False)
    assert "cases" not in mapping["properties"]

    mapping = mapper.get_case_es_mapping(include_file=False)
    assert "files" not in mapping["properties"]


@pytest.mark.parametrize(
    "prefix",
    [
        ["sample", "aliquot", "read_group"],
        ["sample", "portion", "analyte", "aliquot", "read_group"],
    ],
)
def test_get_case_to_file_paths_contains_expected_path(prefix):
    assert (
        prefix
        + [
            "submitted_aligned_reads",
            "aligned_reads",
            "somatic_mutation_calling_workflow",
            "simple_somatic_mutation",
        ]
        in ActiveGraphIndexBuilder.case_to_file_paths
    )


@pytest.mark.parametrize(
    "a,b,expected",
    [
        (
            [["a", "b"], ["-", "#"]],
            [[0, 1], [2, 3], [4, 5, 6, 7]],
            [
                ["a", "b", 0, 1],
                ["a", "b", 2, 3],
                ["a", "b", 4, 5, 6, 7],
                ["-", "#", 0, 1],
                ["-", "#", 2, 3],
                ["-", "#", 4, 5, 6, 7],
            ],
        )
    ],
)
def test_list_product(a, b, expected):
    assert list_product(a, b) == expected


@pytest.mark.parametrize(
    "node,expected",
    [
        (md.RnaExpressionWorkflow, ["gene_expression"]),
        (
            md.ReadGroup,
            [
                "submitted_aligned_reads",
                "aligned_reads",
                "somatic_mutation_calling_workflow",
                "simple_somatic_mutation",
            ],
        ),
    ],
)
def test_subtree_paths_to_file_subset(node, expected):
    assert expected in subtree_paths_to_file(node)


def test_subtree_paths_to_file_expecting_empty():
    assert subtree_paths_to_file(md.Annotation) == []


@pytest.mark.parametrize(
    "path",
    [
        ["case", "sample", "portion", "analyte", "aliquot"],
        ["case", "sample", "aliquot"],
    ],
)
def test_case_to_file_paths_is_absent(path):
    assert path not in ActiveGraphIndexBuilder.case_to_file_paths


@pytest.mark.parametrize("index_type", ["project", "case", "file", "annotation"])
def test_mapping_full(mappings, index_type):
    """Compare mappings defined in mappings.py to gdc-models"""
    validate_mappings(mappings, index_type)


def validate_mappings(mappings, index_type):
    """Asserts that set of expected by gdc-models paths is equal
    to the mappings' paths set"""
    es_mapping = mappings[index_type]["properties"]
    true_mapping = get_es_models()["gdc_from_graph"][index_type]["_mapping"][
        "properties"
    ]

    es_paths = get_dict_paths(es_mapping)[0]
    true_paths = get_dict_paths(true_mapping)[0]

    missing_paths = set(true_paths) - set(es_paths)
    extra_paths = set(es_paths) - set(true_paths)

    if missing_paths:
        pprint({"index_type": index_type, "missing_paths": missing_paths})

    if extra_paths:
        pprint({"index_type": index_type, "extra_paths": extra_paths})

    # Set of missing paths must be empty:
    assert missing_paths == set()

    # Set of extra paths must be emty:
    assert extra_paths == set()


@pytest.mark.parametrize(
    "index_type,field,substring",
    [
        ("annotation", "annotations.analyte.project_id", "Unique ID for any specific"),
        ("annotation", "annotations.annotation.submitter_id", "project-specific"),
        ("annotation", "annotations.slide.section_location", "Tissue source"),
        ("case", "cases.case.created_datetime", "combination of date and time"),
        ("case", "cases.case.primary_site", "the primary site of disease"),
        ("case", "cases.diagnoses.morphology", "The third edition"),
        ("case", "cases.follow_ups.molecular_tests.intron", "Intron number"),
        ("case", "cases.project.code", "Project code"),
        ("file", "files.center.code", "Numeric code for the center"),
        ("file", "files.file.md5sum", "The 128-bit hash"),
        ("project", "projects.project.state", "The possible states"),
    ],
)
def test_mapping_descriptions(mappings, index_type, field, substring):
    """Spot-check the descriptions for some fields in the mappings.

    Confirm some is present in those descriptions, based on what was in the dictionary
    at the time this test was written.
    """
    description = mappings[index_type]["_meta"]["descriptions"].get(field)
    assert description is not None and substring in description


@pytest.mark.parametrize(
    "mapping,path",
    [
        (
            "file",
            "properties.analysis.properties.metadata.properties.read_groups.properties.read_group_qcs",
        ),
        ("file", "properties.analysis.properties.input_files.properties.data_category"),
        (
            "file",
            "properties.downstream_analyses.properties.output_files.properties.data_category",
        ),
        ("case", "_meta.descriptions"),
        (
            "case",
            '_meta.descriptions."cases.samples.portions.analytes.a260_a280_ratio"',
        ),
        ("project", "_meta.descriptions"),
        ("annotation", "_meta.descriptions"),
    ],
)
def test_mapping_contains(mappings, mapping, path):
    results = parse(path).find(mappings[mapping])
    assert len([r.value for r in results]) == 1


@pytest.mark.parametrize(
    "mapping,path",
    [
        ("file", "properties.uploaded_datetime"),
        ("file", "properties.project_id"),
        ("file", "properties.cases.properties.samples.properties.project_id"),
        ("case", "properties.project_id"),
        ("case", "properties.metadata_files"),
        ("case", "properties.samples.properties.aliquots"),
        ("case", "properties.samples.properties.portions.properties.project_id"),
        ("annotation", "properties.creator"),
        ("annotation", "properties.project_id"),
    ],
)
def test_mapping_does_not_contain(mappings, mapping, path):
    assert len(parse(path).find(mappings[mapping])) == 0


@pytest.mark.parametrize(
    "mapping,path,expected",
    [
        ("file", "properties.downstream_analyses.type", ["nested"]),
    ],
)
def test_mapping_value_in(mappings, mapping, path, expected):
    results = parse(path).find(mappings[mapping])
    for r in results:
        assert r.value in expected


@pytest.mark.parametrize(
    "path",
    [
        "sample.portion.analyte.aliquot.read_group.submitted_unaligned_reads",
        "sample.portion.analyte.aliquot.read_group.submitted_unaligned_reads.alignment_workflow.aligned_reads",
    ],
)
def test_get_case_to_file_path_is_present(path):
    assert path.split(".") in ActiveGraphIndexBuilder.case_to_file_paths


@pytest.mark.parametrize(
    "label,path",
    [
        ("submitted_aligned_reads", ["read_group"]),
        (
            "aligned_reads",
            ["alignment_workflow", "submitted_aligned_reads", "read_group"],
        ),
    ],
)
def test_file_to_read_group_paths(label, path):
    assert path in ActiveGraphIndexBuilder.file_to_read_group_paths[label]
