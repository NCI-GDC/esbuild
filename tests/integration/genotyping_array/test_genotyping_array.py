import jsonpath_ng

from tests.integration import conftest


def test__submitted_genotyping_array__files(
    genotyping_array_index: conftest.Index,
) -> None:
    file_results = jsonpath_ng.parse("[*].submitter_id").find(
        genotyping_array_index.files
    )
    case_results = jsonpath_ng.parse("[*].cases.[*].submitter_id").find(
        genotyping_array_index.files
    )
    file_submitter_ids = frozenset(r.value for r in file_results)
    case_submitter_ids = frozenset(r.value for r in case_results)

    assert "gta_sgta0" in file_submitter_ids
    assert "gta_c0" in case_submitter_ids


def test__submitted_genotyping_array__cases(
    genotyping_array_index: conftest.Index,
) -> None:
    case_results = jsonpath_ng.parse("[*].submitter_id").find(
        genotyping_array_index.cases
    )
    file_results = jsonpath_ng.parse("[*].files.[*].submitter_id").find(
        genotyping_array_index.cases
    )
    case_submitter_ids = frozenset(r.value for r in case_results)
    file_submitter_ids = frozenset(r.value for r in file_results)

    assert "gta_c0" in case_submitter_ids
    assert "gta_sgta0" in file_submitter_ids


def test__simple_germline_variation__files(
    genotyping_array_index: conftest.Index,
) -> None:
    file_results = jsonpath_ng.parse("[*].submitter_id").find(
        genotyping_array_index.files
    )
    input_file_results = jsonpath_ng.parse("[*].analysis.input_files.[*].submitter_id").find(
        genotyping_array_index.files
    )
    case_results = jsonpath_ng.parse("[*].cases.[*].submitter_id").find(
        genotyping_array_index.files
    )
    file_submitter_ids = frozenset(r.value for r in file_results)
    input_file_submitter_ids = frozenset(r.value for r in input_file_results)
    case_submitter_ids = frozenset(r.value for r in case_results)


    assert "gta_sgv0" in file_submitter_ids
    assert "gta_sgta0" in input_file_submitter_ids
    assert "gta_c0" in case_submitter_ids


def test__simple_germline_variation__cases(
    genotyping_array_index: conftest.Index,
) -> None:
    case_results = jsonpath_ng.parse("[*].submitter_id").find(
        genotyping_array_index.cases
    )
    file_results = jsonpath_ng.parse("[*].files.[*].submitter_id").find(
        genotyping_array_index.cases
    )
    case_submitter_ids = frozenset(r.value for r in case_results)
    file_submitter_ids = frozenset(r.value for r in file_results)

    assert "gta_c0" in case_submitter_ids
    assert "gta_sgv0" in file_submitter_ids
