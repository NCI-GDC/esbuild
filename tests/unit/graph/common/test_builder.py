from typing import Any, Optional
from unittest import mock

import more_itertools
import psqlgraph
from indexclient import client

from esbuild.graph.common import builder, mappings


class TestIndexBuilder(builder.GraphIndexBuilder):
    def __init__(
        self,
        psqlgraph_driver: psqlgraph.PsqlGraphDriver,
        indexd_client: client.IndexClient,
        index_prefix: Optional[str] = "",
        mapper: Optional[mappings.ESMapper] = None,
        case_to_file_paths=(),
        file_labels=frozenset(()),
        **kwargs: Any
    ) -> None:
        self.mapper = mapper or mock.MagicMock()
        self.case_to_file_paths = case_to_file_paths
        self.file_labels = file_labels

        super().__init__(psqlgraph_driver, indexd_client, index_prefix, **kwargs)


def test__denormalize_annotations__no_annotations() -> None:
    graph = mock.MagicMock()
    annotations = ()
    index_builder = TestIndexBuilder(graph, mock.MagicMock(), "")

    result = index_builder.denormalize_annotations(annotations=annotations)

    assert result == []


def test__denormalize_annotations__annotated_case_node() -> None:
    case = mock.MagicMock(node_id="c-0", label="case", submitter_id="s-c-0")
    annotation = mock.MagicMock(
        label="annotation",
        node_id="a-0",
        edges_out=(mock.MagicMock(dst=case),),
        _dictionary={"category": "non-analysis"},
        _props={},
    )
    annotation_edge = mock.MagicMock(label="annotates", src=annotation, dst=case)
    graph = mock.MagicMock()
    graph.edges.return_value = graph
    graph.filter.return_value = (annotation_edge,)
    index_builder = TestIndexBuilder(graph, mock.MagicMock(), "")

    result = index_builder.denormalize_annotations(annotations=(annotation,))

    assert len(result) == 1

    result_doc = more_itertools.one(result)
    key_diff = result_doc.keys() ^ frozenset(
        {
            "entity_id",
            "entity_type",
            "entity_submitter_id",
            "case_id",
            "case_submitter_id",
            "annotation_id",
            "project",
        }
    )

    assert not key_diff
    assert result_doc["entity_id"] == "c-0"
    assert result_doc["entity_type"] == "case"
    assert result_doc["entity_submitter_id"] == "s-c-0"
    assert result_doc["case_id"] == "c-0"
    assert result_doc["case_submitter_id"] == "s-c-0"
    assert result_doc["annotation_id"] == "a-0"
    assert result_doc["project"] is None


def test__denormalize_annotations__annotated_workflow_with_linked_case() -> None:
    case = mock.MagicMock(node_id="c-0", label="case", submitter_id="s-c-0")
    workflow = mock.MagicMock(
        node_id="w-0",
        label="workflow",
        submitter_id="s-w-0",
        edges_out=(mock.MagicMock(dst=case),),
    )
    annotation = mock.MagicMock(
        label="annotation",
        node_id="a-0",
        edges_out=(mock.MagicMock(dst=workflow),),
        _dictionary={"category": "non-analysis"},
        _props={},
    )
    annotation_edge = mock.MagicMock(label="annotates", src=annotation, dst=workflow)
    graph = mock.MagicMock()
    graph.edges.return_value = graph
    graph.filter.return_value = (annotation_edge,)
    index_builder = TestIndexBuilder(graph, mock.MagicMock(), "")

    result = index_builder.denormalize_annotations(annotations=(annotation,))
    result_doc = more_itertools.one(result)
    key_diff = result_doc.keys() ^ frozenset(
        {
            "entity_id",
            "entity_type",
            "entity_submitter_id",
            "case_id",
            "case_submitter_id",
            "annotation_id",
            "project",
        }
    )

    assert not key_diff
    assert result_doc["entity_id"] == "w-0"
    assert result_doc["entity_type"] == "workflow"
    assert result_doc["entity_submitter_id"] == "s-w-0"
    assert result_doc["case_id"] == "c-0"
    assert result_doc["case_submitter_id"] == "s-c-0"
    assert result_doc["annotation_id"] == "a-0"
    assert result_doc["project"] is None


def test__denormalize_annotations__annotated_workflow_without_linked_case() -> None:
    workflow = mock.MagicMock(
        node_id="w-0",
        label="workflow",
        submitter_id="s-w-0",
        edges_out=(),
    )
    annotation = mock.MagicMock(
        label="annotation",
        node_id="a-0",
        edges_out=(mock.MagicMock(dst=workflow),),
        _dictionary={"category": "non-analysis"},
        _props={},
    )
    annotation_edge = mock.MagicMock(label="annotates", src=annotation, dst=workflow)
    graph = mock.MagicMock()
    graph.edges.return_value = graph
    graph.filter.return_value = (annotation_edge,)
    index_builder = TestIndexBuilder(graph, mock.MagicMock(), "")

    result = index_builder.denormalize_annotations(annotations=(annotation,))
    result_doc = more_itertools.one(result)
    key_diff = result_doc.keys() ^ frozenset(
        {
            "entity_id",
            "entity_type",
            "entity_submitter_id",
            "case_id",
            "case_submitter_id",
            "annotation_id",
            "project",
        }
    )

    assert not key_diff
    assert result_doc["entity_id"] == "w-0"
    assert result_doc["entity_type"] == "workflow"
    assert result_doc["entity_submitter_id"] == "s-w-0"
    assert result_doc["case_id"] is None
    assert result_doc["case_submitter_id"] is None
    assert result_doc["annotation_id"] == "a-0"
    assert result_doc["project"] is None
