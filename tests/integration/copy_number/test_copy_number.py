import jsonpath_ng
from jsonpath_ng import ext

from tests.integration import conftest


def test_copy_number_estimate(copy_number_estimate_index: conftest.Index) -> None:
    """
    Make sure that CopyNumberSegment and CopyNumberEstimate nodes are picked up
    """
    file_results = jsonpath_ng.parse("[*].submitter_id").find(
        copy_number_estimate_index.files
    )
    file_submitter_ids = frozenset(r.value for r in file_results)

    # 8 additional files: 2 CNE, 2 CNS, 2 ARs, 2 SGA
    expected_submitter_ids = frozenset(
        {
            "cn_cne_1",
            "cn_cne_2",
            "cn_cns_1",
            "cn_cns_2",
            "cn_ar_1",
            "cn_ar_2",
            "cn_sga_1",
            "cn_sga_2",
        }
    )

    assert (
        expected_submitter_ids < file_submitter_ids
    ), f"Missing: {expected_submitter_ids - file_submitter_ids}"


def test_copy_number_segment(copy_number_segment_index: conftest.Index) -> None:
    file_results = jsonpath_ng.parse("[*].submitter_id").find(
        copy_number_segment_index.files
    )
    file_ids = frozenset(r.value for r in file_results)
    expected_ids = frozenset(("gta_cns_1", "tcn_cns_1"))

    assert expected_ids < file_ids, expected_ids - file_ids

    genotyping_results = ext.parse(
        "$[?submitter_id=gta_cns_1].associated_entities.[*].entity_submitter_id"
    ).find(copy_number_segment_index.files)
    tangent_copy_number_results = ext.parse(
        "$[?submitter_id=tcn_cns_1].associated_entities.[*].entity_submitter_id"
    ).find(copy_number_segment_index.files)

    assert frozenset(("gta_aliquot_1",)) == frozenset(
        r.value for r in genotyping_results
    )
    assert frozenset(("tcn_aliquot_1",)) == frozenset(
        r.value for r in tangent_copy_number_results
    )
