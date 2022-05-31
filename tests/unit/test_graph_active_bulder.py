import pytest
from gdcdatamodel import models as md

from esbuild.graph.active.builder import (
    ActiveGraphIndexBuilder,
    list_product,
    subtree_paths_to_file,
)


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
