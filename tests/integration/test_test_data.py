import pytest

from esbuild.graph.common import builder
from tests.integration import data


@pytest.fixture(scope="session")
def file_nodes():
    return [
        nd
        for nd in data.NODES
        if nd._dictionary.get("category") in data.DATA_FILE_CATEGORIES
    ]


def test_file_nodes_patched(file_nodes):
    """
    Checks that all file nodes' indexd fields are patched with error values
    """
    for node in file_nodes:
        for key in builder.DATA_FILE_INDEXD_FIELDS:
            key_value = getattr(node, key, None)
            if not key_value:
                continue

            if isinstance(key_value, str):
                assert getattr(node, key) == "error"
            elif isinstance(key_value, list):
                assert getattr(node, key) == ["error" for _ in getattr(node, key)]
            elif isinstance(key_value, int):
                assert getattr(node, key) == -1
            else:
                raise Exception("Unknown file field:", key, key_value)


def test_indexd_data(init_indexd, file_nodes):
    """
    Test that indexd data corresponds to graph data
    """
    # Check that indexd data count == number of file nodes
    assert len(data.INDEXD) == len(file_nodes)

    # Check that indexd uuids == file nodes uuids
    assert {r["node_id"] for r in data.INDEXD} == {
        getattr(n, "node_id") for n in file_nodes
    }

    # Check that all DATA_FILE_INDEXD_FIELDS are in all indexd records
    for node in file_nodes:
        record = init_indexd.get(node.node_id).to_json()
        for key in builder.DATA_FILE_INDEXD_FIELDS:
            if key not in record and key in node.to_json():
                assert key in record["metadata"]
