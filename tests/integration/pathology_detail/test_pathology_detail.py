from collections import Counter

import pytest
from jsonpath_rw import parse


@pytest.mark.parametrize(
    "index_type, path, expectations",
    [
        (
            "files",
            "[*].cases.[*].diagnoses.[*].pathology_details.[*].submitter_id",
            {"pd_pathology_1": 1, "pd_pathology_2": 1,},
        ),
        (
            "cases",
            "[*].diagnoses.[*].pathology_details.[*].submitter_id",
            {"pd_pathology_1": 1, "pd_pathology_2": 1,},
        ),
    ],
)
def test_pathology_detail_counts(
    pathology_detail_index, index_type, path, expectations
):
    results = parse(path).find(getattr(pathology_detail_index, index_type))
    counts = Counter(r.value for r in results)

    for value, count in expectations.items():
        assert counts[value] == count, counts
