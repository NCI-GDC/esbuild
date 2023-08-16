import pprint

import gdcmodels
import jmespath
import pytest
from gdcdatamodel import models

from esbuild.graph.active import builder, mappings
from tests.unit import utils


@pytest.fixture(scope="session")
def index_mappings():
    mapper = mappings.ActiveESMapper()
    return {
        "file": mapper.get_file_es_mapping().to_dict(),
        "annotation": mapper.get_annotation_es_mapping().to_dict(),
        "case": mapper.get_case_es_mapping().to_dict(),
        "project": mapper.get_project_es_mapping().to_dict(),
    }


def test_include_switch():
    mapper = mappings.ActiveESMapper()

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
        in builder.ActiveGraphIndexBuilder.case_to_file_paths
    )


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    (
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
        ),
    ),
)
def test_list_product(a, b, expected):
    assert builder.list_product(a, b) == expected


@pytest.mark.parametrize(
    ("node", "expected"),
    (
        (models.RnaExpressionWorkflow, ["gene_expression"]),
        (
            models.ReadGroup,
            [
                "submitted_aligned_reads",
                "aligned_reads",
                "somatic_mutation_calling_workflow",
                "simple_somatic_mutation",
            ],
        ),
    ),
)
def test_subtree_paths_to_file_subset(node, expected):
    assert expected in builder.subtree_paths_to_file(node)


def test_subtree_paths_to_file_expecting_empty():
    assert builder.subtree_paths_to_file(models.Annotation) == []


@pytest.mark.parametrize(
    "path",
    (
        ["case", "sample", "portion", "analyte", "aliquot"],
        ["case", "sample", "aliquot"],
    ),
)
def test_case_to_file_paths_is_absent(path):
    assert path not in builder.ActiveGraphIndexBuilder.case_to_file_paths


@pytest.mark.parametrize("index_type", ("project", "case", "file", "annotation"))
def test_mapping_full(index_mappings, index_type):
    """Compare mappings defined in mappings.py to gdc-models"""
    validate_mappings(index_mappings, index_type)


def validate_mappings(index_mappings, index_type):
    """Asserts that set of expected by gdc-models paths is equal
    to the mappings' paths set"""
    es_mapping = index_mappings[index_type]["properties"]
    true_mapping = gdcmodels.get_es_models()["gdc_from_graph"][index_type]["_mapping"][
        "properties"
    ]

    es_paths = frozenset(utils.get_dict_paths(es_mapping))
    true_paths = utils.get_dict_paths(true_mapping)

    # We currently only want to insure that the mapping is a subset of the 'true'
    # one.
    extra_paths = es_paths.difference(true_paths)

    # Set of extra paths must be empty:
    assert not extra_paths, f"Mapping contains extra paths: {extra_paths}"


@pytest.mark.parametrize(
    ("index_type", "field", "substring"),
    (
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
    ),
)
def test_mapping_descriptions(index_mappings, index_type, field, substring):
    """Spot-check the descriptions for some fields in the mappings.

    Confirm some is present in those descriptions, based on what was in the dictionary
    at the time this test was written.
    """
    description = index_mappings[index_type]["_meta"]["descriptions"].get(field)
    assert description is not None and substring in description


@pytest.mark.parametrize(
    ("mapping", "path"),
    (
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
    ),
)
def test_mapping_contains(index_mappings, mapping, path):
    assert jmespath.search(path, index_mappings[mapping])


@pytest.mark.parametrize(
    ("mapping", "path"),
    (
        ("file", "properties.uploaded_datetime"),
        ("file", "properties.project_id"),
        ("file", "properties.cases.properties.samples.properties.project_id"),
        ("case", "properties.project_id"),
        ("case", "properties.metadata_files"),
        ("case", "properties.samples.properties.aliquots"),
        ("case", "properties.samples.properties.portions.properties.project_id"),
        ("annotation", "properties.creator"),
        ("annotation", "properties.project_id"),
    ),
)
def test_mapping_does_not_contain(index_mappings, mapping, path):
    assert not jmespath.search(path, index_mappings[mapping])


@pytest.mark.parametrize(
    "mapping,path,expected",
    [
        ("file", "properties.downstream_analyses.type", "nested"),
    ],
)
def test_mapping_value_in(index_mappings, mapping, path, expected):
    assert jmespath.search(path, index_mappings[mapping]) == expected


@pytest.mark.parametrize(
    "path",
    (
        "sample.portion.analyte.aliquot.read_group.submitted_unaligned_reads",
        "sample.portion.analyte.aliquot.read_group.submitted_unaligned_reads.alignment_workflow.aligned_reads",
    ),
)
def test_get_case_to_file_path_is_present(path):
    assert path.split(".") in builder.ActiveGraphIndexBuilder.case_to_file_paths


@pytest.mark.parametrize(
    ("label", "path"),
    (
        ("submitted_aligned_reads", ["read_group"]),
        (
            "aligned_reads",
            ["alignment_workflow", "submitted_aligned_reads", "read_group"],
        ),
    ),
)
def test_file_to_read_group_paths(label, path):
    assert path in builder.ActiveGraphIndexBuilder.file_to_read_group_paths[label]
