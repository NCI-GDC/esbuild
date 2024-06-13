from collections.abc import Iterable, Sequence
from unittest import mock

import pytest
from gdcdatamodel2 import models

from esbuild.graph.active import builder


@pytest.mark.parametrize(
    "prefix",
    (
        ("sample", "aliquot", "read_group"),
        ("sample", "portion", "analyte", "aliquot", "read_group"),
    ),
)
def test_get_case_to_file_paths_contains_expected_path(prefix: Sequence[str]) -> None:
    assert (
        *prefix,
        "submitted_aligned_reads",
        "aligned_reads",
        "somatic_mutation_calling_workflow",
        "simple_somatic_mutation",
    ) in builder.ActiveGraphIndexBuilder(
        psqlgraph_driver=mock.MagicMock(),
        indexd_client=mock.MagicMock(),
        index_prefix="",
        build_projects=(),
        build_awg=False,
        selective_caching=False,
        versioned_files={},
        allowed_gencode_versions=frozenset(("neutral", "v36")),
    ).case_to_file_paths


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    (
        (
            (("a", "b"), ("-", "#")),
            ((0, 1), (2, 3), (4, 5, 6, 7)),
            (
                ("a", "b", 0, 1),
                ("a", "b", 2, 3),
                ("a", "b", 4, 5, 6, 7),
                ("-", "#", 0, 1),
                ("-", "#", 2, 3),
                ("-", "#", 4, 5, 6, 7),
            ),
        ),
    ),
)
def test_list_product(
    a: Iterable[Sequence[str]],
    b: Iterable[Sequence[str]],
    expected: Iterable[Sequence[str]],
) -> None:
    assert builder._path_product(a, b) == expected


@pytest.mark.parametrize(
    ("node", "expected"),
    (
        (models.RnaExpressionWorkflow, ("gene_expression",)),
        (
            models.ReadGroup,
            (
                "submitted_aligned_reads",
                "aligned_reads",
                "somatic_mutation_calling_workflow",
                "simple_somatic_mutation",
            ),
        ),
    ),
)
def test_subtree_paths_to_file_subset(
    node: type[models.Node], expected: Sequence[str]
) -> None:
    assert expected in builder._subtree_paths_to_file(node)


def test_subtree_paths_to_file_expecting_empty() -> None:
    assert tuple(builder._subtree_paths_to_file(models.Annotation)) == ()


@pytest.mark.parametrize(
    "path",
    (
        ("case", "sample", "portion", "analyte", "aliquot"),
        ("case", "sample", "aliquot"),
    ),
)
def test_case_to_file_paths_is_absent(path: tuple[str, ...]):
    assert (
        path
        not in builder.ActiveGraphIndexBuilder(
            psqlgraph_driver=mock.MagicMock(),
            indexd_client=mock.MagicMock(),
            index_prefix="",
            build_projects=(),
            build_awg=False,
            selective_caching=False,
            versioned_files={},
            allowed_gencode_versions=frozenset(("neutral", "v36")),
        ).case_to_file_paths
    )


@pytest.mark.parametrize(
    "path",
    (
        "sample.portion.analyte.aliquot.read_group.submitted_unaligned_reads",
        "sample.portion.analyte.aliquot.read_group.submitted_unaligned_reads.alignment_workflow.aligned_reads",
    ),
)
def test_get_case_to_file_path_is_present(path: str) -> None:
    assert (
        tuple(path.split("."))
        in builder.ActiveGraphIndexBuilder(
            psqlgraph_driver=mock.MagicMock(),
            indexd_client=mock.MagicMock(),
            index_prefix="",
            build_projects=(),
            build_awg=False,
            selective_caching=False,
            versioned_files={},
            allowed_gencode_versions=frozenset(("neutral", "v36")),
        ).case_to_file_paths
    )
