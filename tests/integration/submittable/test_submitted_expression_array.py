import collections
from typing import Literal, Mapping

import jmespath
import pytest

from tests.integration import conftest


@pytest.mark.parametrize(
    "index_type, path, expectations",
    [
        pytest.param(
            "files",
            "[].submitter_id",
            {
                "ea_0": 1,
            },
            id="file-index",
        ),
        pytest.param(
            "cases",
            "[].files[].submitter_id",
            {
                "ea_0": 1,
            },
            id="case-index",
        ),
    ],
)
def test__submitted_expression_array__indexed_as_file(
    submitted_expression_array_index: conftest.Index,
    index_type: Literal["files", "cases"],
    path: str,
    expectations: Mapping[str, int],
):
    """Tests that the submitted gene expression arrays are indexed as files in both the
    file index as well as in the files node of the case index."""
    results = jmespath.search(
        path, getattr(submitted_expression_array_index, index_type)
    )
    counts = collections.Counter(results)

    for value, count in expectations.items():
        assert counts[value] == count, counts
