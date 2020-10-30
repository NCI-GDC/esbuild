from collections import Counter

import pytest
from jsonpath_rw import parse


@pytest.mark.parametrize("index_type, path, expectations", [
    ("files", "[*].type.[*]", {
        "pathology_report": 2,
    }),
    ("files", "[*].data_type.[*]", {
        "Pathology Report": 2,
    }),
    ("files", "[*].submitter_id.[*]", {
        "pr_pathology_1": 1,
        "pr_pathology_2": 1,
    }),
    ("cases", "[*].files.[*].type.[*]", {
        "pathology_report": 2,
    })
])
def test_pathology_report_counts(pathology_index, index_type, path, expectations):
    results = parse(path).find(getattr(pathology_index, index_type))
    counts = Counter(r.value for r in results)

    for value, count in expectations.items():
        assert counts[value] == count, counts
