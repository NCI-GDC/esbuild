from esbuild.graph.common import document_tools


def test__move_document_nodes__direct_child() -> None:
    sample = {"sample_id": "sample-0"}
    doc = {"samples": [sample]}
    samples = document_tools.DocumentNode("samples", "sample_id")
    parent = document_tools.DocumentNode("parents", "parent_id")

    document_tools.move_document_nodes(
        doc, source_path=(samples.remove(),), destination_path=(parent, samples)
    )

    assert "samples" not in doc
    assert "parents" in doc and len(doc["parents"]) == 1
    assert doc["parents"][0]["parent_id"]
    assert doc["parents"][0]["samples"] == [sample]


def test__move_document_nodes__nested_children() -> None:
    aliquot = {"aliquot_id": "aliquot-0"}
    samples = document_tools.DocumentNode("samples", "sample_id")
    portions = document_tools.DocumentNode("portions", "portion_id")
    analytes = document_tools.DocumentNode("analytes", "analyte_id")
    aliquots = document_tools.DocumentNode("aliquots", "aliquot_id")
    final_path = (samples, portions, analytes, aliquots)
    doc: dict = {"samples": [{"sample_id": "sample-0", "aliquots": [aliquot]}]}

    document_tools.move_document_nodes(
        doc, source_path=(samples, aliquots.remove()), destination_path=final_path
    )

    for node in final_path:
        assert node.name in doc
        assert len(doc[node.name]) == 1

        doc = doc[node.name][0]

        assert node.id_property in doc

    assert doc == aliquot


def test__move_document_nodes__distinct_paths() -> None:
    molecular_test = {"molecular_test_id": "molecular-test-0"}
    diagnoses = document_tools.DocumentNode("diagnoses", "diagnosis_id")
    follow_ups = document_tools.DocumentNode("follow_ups", "follow_up_id")
    molecular_tests = document_tools.DocumentNode("molecular_tests", "molecular_test_id")
    doc = {
        "diagnoses": [{"diagnosis_id": "diagnosis-0", "molecular_tests": [molecular_test]}],
    }

    document_tools.move_document_nodes(
        doc,
        source_path=(diagnoses, molecular_tests.remove()),
        destination_path=(follow_ups, molecular_tests),
    )

    assert "diagnoses" in doc and "follow_ups" in doc
    assert len(doc["diagnoses"]) == 1
    assert "molecular_tests" not in doc["diagnoses"][0]
    assert len(doc["follow_ups"]) == 1
    assert "molecular_tests" in doc["follow_ups"][0]
    assert doc["follow_ups"][0]["molecular_tests"] == [molecular_test]


def test__move_document_nodes__existing_child() -> None:
    sample = {"sample_id": "sample-0"}
    doc: dict = {
        "samples": [sample],
        "parents": [{"parent_id": "parent-0", "samples": [sample]}],
    }
    samples = document_tools.DocumentNode("samples", "sample_id")
    parent = document_tools.DocumentNode("parents", "parent_id")

    document_tools.move_document_nodes(
        doc, source_path=(samples.remove(),), destination_path=(parent, samples)
    )

    assert "samples" not in doc
    assert "parents" in doc and len(doc["parents"]) == 1
    assert doc["parents"][0]["parent_id"] == "parent-0"
    assert len(doc["parents"][0]["samples"]) == 1
