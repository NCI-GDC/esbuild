from collections import Counter

from jsonpath_rw import parse
import pytest


@pytest.mark.parametrize("index_type, path, expected", [
    ("files", "[*].type.[*]", {
        "secondary_expression_analysis": 2,
    }),
    ("files", "[*].data_type.[*]", {
        "Differential Gene Expression": 1,
        "Single Cell Analysis": 1,
    }),
    ("files", "[*].submitter_id.[*]", {
        "sea_secondary_exp_0": 1,
        "sea_secondary_exp_1": 1,
    })
])
def test_secondary_expression_analysis_counts(index_type, path, expected, scenario_index):
    index = scenario_index("secondary_expression_analysis_scenario.yaml")

    results = parse(path).find(getattr(index, index_type))
    counts = Counter(r.value for r in results)

    for value, count in expected.items():
        assert counts[value] == count, counts
