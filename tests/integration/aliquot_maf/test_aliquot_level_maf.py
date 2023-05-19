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
                "masked_somatic_mutation": 2,
                "simple_somatic_mutation": 6,  # 2 from data.py and 4 from maf data
                "aggregated_somatic_mutation": 3,  # 1 from data.py and 2 from maf data
                "annotated_somatic_mutation": 6,  # 2 from data.py and 4 from maf data
            },
        ),
        (
            "files",
            "[].data_type",
            {
                "Masked Somatic Mutation": 2,
                "Aggregated Somatic Mutation": 3,  # 1 from data.py and 2 from maf data
                "Annotated Somatic Mutation": 6,
            },
        ),
        (
            "cases",
            "[].files[].data_type",
            {
                "Masked Somatic Mutation": 2,
                "Aggregated Somatic Mutation": 3,
                "Annotated Somatic Mutation": 6,
            },
        ),
    ],
)
def test_aliquot_level_maf_build_counts(
    maf_index, index_type, path, expectations, pg_driver
):
    results = jmespath.search(path, getattr(maf_index, index_type))

    counts = Counter(results)
    for value, count in expectations.items():
        assert counts[value] == count, (value, counts[value])
