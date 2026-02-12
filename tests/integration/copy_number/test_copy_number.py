import jmespath

from tests.integration import conftest


def test_copy_number_estimate(copy_number_estimate_index: conftest.Index) -> None:
    """Make sure that CopyNumberSegment and CopyNumberEstimate nodes are picked up."""
    file_submitter_ids = frozenset(
        jmespath.search("[].submitter_id", copy_number_estimate_index.files)
    )

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

    assert expected_submitter_ids < file_submitter_ids, (
        f"Missing: {expected_submitter_ids - file_submitter_ids}"
    )


def test_copy_number_segment(copy_number_segment_index: conftest.Index) -> None:
    file_ids = frozenset(jmespath.search("[].submitter_id", copy_number_segment_index.files))
    expected_ids = frozenset(("gta_cns_1", "tcn_cns_1"))

    assert expected_ids < file_ids, expected_ids - file_ids

    genotyping_results = jmespath.search(
        "[?submitter_id==`gta_cns_1`].associated_entities[].entity_submitter_id",
        copy_number_segment_index.files,
    )
    tangent_copy_number_results = jmespath.search(
        "[?submitter_id==`tcn_cns_1`].associated_entities[].entity_submitter_id",
        copy_number_segment_index.files,
    )

    assert frozenset(("gta_aliquot_1",)) == frozenset(genotyping_results)
    assert frozenset(("tcn_aliquot_1",)) == frozenset(tangent_copy_number_results)
