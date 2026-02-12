from collections.abc import Iterable
from unittest import mock

import pytest

from esbuild.graph.active import builder


@pytest.mark.parametrize(
    "prefix",
    [
        ("sample", "aliquot", "read_group"),
        ("sample", "portion", "analyte", "aliquot", "read_group"),
    ],
)
def test_get_case_to_file_paths_contains_expected_path(prefix: Iterable[str]) -> None:
    assert (
        *prefix,
        "submitted_aligned_reads",
        "aligned_reads",
        "somatic_mutation_calling_workflow",
        "simple_somatic_mutation",
    ) in builder.ActiveGraphIndexBuilder(
        mock.MagicMock(), mock.MagicMock(), ""
    ).case_to_file_paths


@pytest.mark.parametrize(
    "path",
    (
        ("case", "sample", "portion", "analyte", "aliquot"),
        ("case", "sample", "aliquot"),
    ),
)
def test_case_to_file_paths_is_absent(path):
    assert (
        path
        not in builder.ActiveGraphIndexBuilder(
            mock.MagicMock(), mock.MagicMock(), ""
        ).case_to_file_paths
    )


@pytest.mark.parametrize(
    "path",
    (
        "sample.portion.analyte.aliquot.read_group.submitted_unaligned_reads",
        "sample.portion.analyte.aliquot.read_group.submitted_unaligned_reads.alignment_workflow.aligned_reads",
    ),
)
def test_get_case_to_file_path_is_present(path):
    assert (
        tuple(path.split("."))
        in builder.ActiveGraphIndexBuilder(
            mock.MagicMock(), mock.MagicMock(), ""
        ).case_to_file_paths
    )


@pytest.mark.parametrize(
    ("label", "path"),
    (
        ("submitted_aligned_reads", ("read_group",)),
        (
            "aligned_reads",
            ("alignment_workflow", "submitted_aligned_reads", "read_group"),
        ),
    ),
)
def test_file_to_read_group_paths(label, path):
    assert (
        path
        in builder.ActiveGraphIndexBuilder(
            mock.MagicMock(), mock.MagicMock(), ""
        )._file_to_read_group_paths[label]
    )
