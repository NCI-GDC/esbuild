from pprint import pprint

import pytest
from gdcdatamodel import models as md
from gdcmodels import get_es_models

from esbuild.graph.active.builder import (
    ActiveGraphIndexBuilder,
    list_product,
    subtree_paths_to_file,
)
from tests.unit.utils import get_dict_paths


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


# TODO: relocate test to unit
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


@pytest.fixture(scope="session")
def mappings():
    mapper = ActiveGraphIndexBuilder.mapper
    return {
        "file": mapper.get_file_es_mapping().to_dict(),
        "annotation": mapper.get_annotation_es_mapping().to_dict(),
        "case": mapper.get_case_es_mapping().to_dict(),
        "project": mapper.get_project_es_mapping().to_dict(),
    }


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
