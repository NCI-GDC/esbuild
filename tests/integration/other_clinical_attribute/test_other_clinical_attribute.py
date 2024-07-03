import collections
from collections.abc import Mapping

import jmespath
import pytest


@pytest.mark.parametrize(
    ("index_type", "path", "expectations"),
    (
        (
            "cases",
            "[].follow_ups[].other_clinical_attributes[].submitter_id",
            {
                "oca_0": 1,
                "oca_1": 1,
            },
        ),
        (
            "files",
            "[].cases[].follow_ups[].other_clinical_attributes[].submitter_id",
            {
                "oca_0": 1,
                "oca_1": 1,
            },
        ),
    ),
)
def test_molecular_test_counts(
    other_clinical_attribute_scenario_index,
    index_type: str,
    path: str,
    expectations: Mapping[str, int],
) -> None:
    results = jmespath.search(
        path, getattr(other_clinical_attribute_scenario_index, index_type)
    )
    counts = collections.Counter(results)

    for value, count in expectations.items():
        assert counts[value] == count, counts
