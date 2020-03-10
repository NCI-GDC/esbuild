from collections import Counter

import pytest
from jsonpath_rw import parse


@pytest.mark.parametrize('doc_type, path, expectations', [
    ('files', '[*].type.[*]', {
        'methylation_beta_value': 3,  # 1 from data.py 2 from methylation_array_scenario.yaml
    }),
    ('files', '[*].data_type.[*]', {
        'Methylation Beta Value': 3,
    }),
    ('files', '[*].submitter_id.[*]', {
        'mbv_0': 1,
        'mbv_1': 1,
    }),
    ('cases', '[*].files.[*].data_type.[*]', {
        'Methylation Beta Value': 3,
    }),
])
def test_methylation_array_counts(methylation_index, doc_type, path, expectations):
    results = parse(path).find(getattr(methylation_index, doc_type))
    counts = Counter(r.value for r in results)

    for value, count in expectations.items():
        assert counts[value] == count, counts
