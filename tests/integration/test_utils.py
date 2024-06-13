import pytest

from esbuild import utils
from esbuild.graph.common import builder
from tests.integration import es_data


def test_get_projects_list(test_index_data):
    es, index_name = test_index_data
    helper = utils.ReleaseHelper(es, "foo")

    projects = {d["project_id"] for d in es_data.DOCS["project"]}

    assert projects == helper.get_project_ids(index_name)


def validate_file_metadata(key, value):
    """
    Errors if file metadata key is taken from graph instead of indexd (has erroneous value)
    """
    if key == "analysis":
        # Look deeper into .input_files
        input_files = value.get("input_files", [])
        for subkey in input_files:
            validate_file_metadata(subkey, input_files)
        return

    if key in ["index_files", "metadata_files"]:
        # Check inside special files arrays
        for subkey in value:
            validate_file_metadata(subkey, value)
        return

    if key == "downstream_analyses":
        # Look deeper into .output_files
        for analysis in value:
            output_files = analysis.get("output_files", [])
            for subkey in output_files:
                validate_file_metadata(subkey, output_files)
        return

    if key in builder.DATA_FILE_INDEXD_FIELDS:
        error_msg = f'"{key}" is loaded from graph instead of indexd'
        if isinstance(value, str):
            assert value != "error", error_msg
        elif isinstance(value, list):
            assert "error" not in value, key
        elif isinstance(value, int):
            assert value != -1, error_msg
        else:
            raise Exception(
                "Can not process file metadata key of type {}: {}={}".format(
                    type(value), key, value
                )
            )


def test_projects_deleted(es_after_deletion):
    es, index_name, projects_before, deleted_projects = es_after_deletion
    helper = utils.ReleaseHelper(es, audit_index="build_metadata_test")
    expected_projects = {p for p in projects_before if p not in deleted_projects}
    assert helper.get_project_ids(index_name) == expected_projects


def test_delete_project_docs(es_after_deletion):
    """Check that correct docs are deleted"""
    es, index_prefix, _, deleted_projects = es_after_deletion

    path_to_id = {
        "project": "project_id",
        "case": "project.project_id",
        "file": "cases.project.project_id",
        "annotation": "project.project_id",
    }

    index_names = utils.get_index_names(index_prefix, path_to_id.keys())

    # Check files
    projects = set()
    file_data = es.search(index=index_names["file"], size=10000)["hits"]["hits"]
    for f in file_data:
        projects.update([c["project"]["project_id"] for c in f["_source"]["cases"]])
    assert {p for p in projects if p in deleted_projects} == set()

    # Check everything else
    def get_value_at_path(tree, path):
        if len(path) == 1:
            return tree[path[0]]
        for step in path:
            return get_value_at_path(tree[path[0]], path[1:])

    for index_type, path in path_to_id.items():
        if index_type == "file":
            continue

        data = es.search(index=index_names[index_type], size=10000)["hits"]["hits"]
        projects = set()
        for doc in data:
            project_id = get_value_at_path(doc["_source"], path.split("."))
            projects.update(project_id)
        assert {x for x in projects if x in deleted_projects} == set()


@pytest.mark.parametrize(
    "namespace, expectation",
    [
        ("aliquots", "43ad68c3-15fe-4d2a-b038-2b5795dfaddd"),
        ("analytes", "816442b7-0b40-4c24-abee-9e6bb4dcf483"),
        ("slides", "d11ce424-081d-47fe-8287-7ed86056b9eb"),
    ],
)
def test_get_uuid_namespace(namespace, expectation):
    u = builder.get_uuid_namespace(namespace)
    assert expectation == str(u)


@pytest.mark.parametrize(
    "namespace, seed, expectation",
    [
        (
            "aliquots",
            "89ddc3c8-e2ad-560b-aa1c-934f7c8a238e",
            "6dec5bd1-5db4-5a49-a5c4-b7ac5f6fab83",
        ),
        (
            "analytes",
            "89ddc3c8-e2ad-560b-aa1c-934f7c8a238e",
            "a24d0977-b65a-55eb-a5ce-2749adf5d3a4",
        ),
        (
            "slides",
            "89ddc3c8-e2ad-560b-aa1c-934f7c8a238e",
            "826fc9b4-537f-5caa-8dbb-1e4b3f44c07d",
        ),
    ],
)
def test_get_namespaced_uuid(namespace, seed, expectation):
    u = builder.get_namespaced_uuid(namespace, seed)
    assert expectation == str(u)
