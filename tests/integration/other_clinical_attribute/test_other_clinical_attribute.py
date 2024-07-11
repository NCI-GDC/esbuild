import collections
from collections.abc import Mapping

import jmespath
import pytest

from tests.integration import conftest


@pytest.mark.parametrize(
    ("index_type", "path", "expectations"),
    (
        pytest.param(
            "cases",
            "[].follow_ups[].other_clinical_attributes[].submitter_id",
            {
                "oca_0": 1,
                "oca_1": 1,
            },
            id="case-index-other-clinical-attributes-indexed",
        ),
        pytest.param(
            "files",
            "[].cases[].follow_ups[].other_clinical_attributes[].submitter_id",
            {
                "oca_0": 1,
                "oca_1": 1,
            },
            id="file-index-other-clinical-attributes-indexed",
        ),
    ),
)
def test_molecular_test_counts(
    other_clinical_attribute_scenario_index: conftest.Index,
    index_type: str,
    path: str,
    expectations: Mapping[str, int],
) -> None:
    """Each test insures that other clinical attributes from the graph are indexed in
    the case/file index nested under the follow_ups/cases.follow_ups respectively.
    """
    results = jmespath.search(
        path, getattr(other_clinical_attribute_scenario_index, index_type)
    )
    counts = collections.Counter(results)

    for value, count in expectations.items():
        assert counts[value] == count, counts
