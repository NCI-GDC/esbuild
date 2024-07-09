import collections
from typing import Literal, Mapping

import jmespath
import pytest

from tests.integration import conftest


@pytest.mark.parametrize(
    "index_type, path, expectations",
    [
        (
            "files",
            "[].type",
            {
                "submitted_expression_array": 1,
            },
        ),
        (
            "files",
            "[].submitter_id",
            {
                "ea_0": 1,
            },
        ),
        (
            "cases",
            "[].files[].type",
            {
                "submitted_expression_array": 1,
            },
        ),
    ],
)
def test_submitted_expression_array_counts(
    submitted_expression_array_index: conftest.Index,
    index_type: Literal["files", "cases"],
    path: str,
    expectations: Mapping[str, int],
):
    results = jmespath.search(
        path, getattr(submitted_expression_array_index, index_type)
    )
    counts = collections.Counter(results)

    for value, count in expectations.items():
        assert counts[value] == count, counts
