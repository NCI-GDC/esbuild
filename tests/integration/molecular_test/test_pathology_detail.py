from collections import Counter

import pytest
from jsonpath_rw import parse


@pytest.mark.parametrize(
    "index_type, path, expectations",
    [
        (
            "cases",
            "[*].follow_ups.[*].submitter_id",
            {
                "mt_follow_up_1": 1,
            },
        ),
        (
            "files",
            "[*].cases.[*].follow_ups.[*].submitter_id",
            {
                "mt_follow_up_1": 1,
            },
        ),
    ],
)
def test_molecular_test_counts(molecular_test_index, index_type, path, expectations):
    results = parse(path).find(getattr(molecular_test_index, index_type))
    counts = Counter(r.value for r in results)

    for value, count in expectations.items():
        assert counts[value] == count, counts
