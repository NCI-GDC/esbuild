from collections import Counter

import jmespath
import pytest


@pytest.mark.parametrize(
    "index_type, path, expectations",
    [
        (
            "files",
            "[].type",
            {
                "masked_methylation_array": 4,
                "methylation_beta_value": 3,  # 1 from data.py 2 from methylation_array_scenario.yaml
                "raw_methylation_array": 0,
            },
        ),
        (
            "files",
            "[].data_type",
            {
                "Masked Intensities": 4,
                "Methylation Beta Value": 3,
                "Raw Intensities": 0,
            },
        ),
        (
            "files",
            "[].submitter_id",
            {
                "mbv_0": 1,
                "mbv_1": 1,
            },
        ),
        (
            "files",
            "[].channel",
            {
                "Red": 2,
                "Green": 2,
            },
        ),
        (
            "cases",
            "[].files[].data_type",
            {
                "Masked Intensities": 4,
                "Methylation Beta Value": 3,
                "Raw Intensities": 0,
            },
        ),
    ],
)
def test_methylation_array_counts(methylation_index, index_type, path, expectations):
    results = jmespath.search(path, getattr(methylation_index, index_type))
    counts = Counter(results)

    for value, count in expectations.items():
        assert counts[value] == count, counts
