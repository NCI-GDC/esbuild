"""A module for tools to modify elasticsearch documents which will be indexed."""

import dataclasses
import functools
import hashlib
import itertools
import logging
import uuid
from collections.abc import Iterable, Sequence
from typing import Union

import more_itertools

logger = logging.getLogger(__name__)


UUID_NAMESPACES: dict[str, uuid.UUID] = {}


@dataclasses.dataclass(frozen=True)
class DocumentNode:
    """A node with in a nested dictionary/document object."""

    name: str
    id_property: str
    _is_removed: bool = False

    @property
    def is_removed(self) -> bool:
        """Flag marking that the node is removed when traversing the parent document."""
        return self._is_removed

    def remove(self) -> "DocumentNode":
        """Mark the node in a path as one that should be removed when it is traversed.

        Returns:
            A copy of the node but marked for removal.
        """
        return DocumentNode(self.name, self.id_property, _is_removed=True)


def _get_uuid_namespace(label: str) -> uuid.UUID:
    """Retrieve the namespace UUID associated with the given node label.

    Args:
        label: The label for a namespace. E.g. aliquots

    Returns:
        A UUID v4 based on the given label's hash.
    """
    if label in UUID_NAMESPACES:
        return UUID_NAMESPACES[label]

    label_hash = hashlib.sha1(bytes(label, "utf-8"), usedforsecurity=False).hexdigest()
    namespace_uuid = uuid.UUID(hex=label_hash[:32], version=4)

    return UUID_NAMESPACES.setdefault(label, namespace_uuid)


def _get_namespaced_uuid(label: str, seed: str) -> str:
    """Create a UUID v5 based on the label's namespace and the given seed value.

    Args:
        label: The label associated with the namespace for the uuid.
        seed: The seed value for creating the new uuid.

    Returns:
        The resulting UUID.
    """
    return str(uuid.uuid5(_get_uuid_namespace(label), seed))


def _walk_path(
    roots: Union[dict, Iterable[dict]], path: Iterable[DocumentNode]
) -> Iterable[dict]:
    def take_step(docs: Iterable[dict], node: DocumentNode) -> Iterable[dict]:
        """Load the nodes in the document with the name of the node.

        Args:
            docs: The documents to be traversed.
            node: The node describing the single path to be traversed.

        Returns:
            The collection of children encountered in step.
        """

        def step(doc: dict) -> Iterable[dict]:
            return doc.pop(node.name, ()) if node.is_removed else doc.get(node.name, ())

        children = tuple(itertools.chain.from_iterable(map(step, docs)))

        if node.is_removed:
            logger.info(
                f"Moving nodes: %s", tuple(n[node.id_property] for n in children)
            )

        return children

    roots = more_itertools.always_iterable(roots, base_type=dict)

    return functools.reduce(take_step, path, roots)


def _generate_ids(
    doc: dict, source_node: DocumentNode, path: Sequence[DocumentNode]
) -> dict[str, str]:
    """Generate all IDs required for creating the given path.

    Args:
        doc: The document containing the source data.
        source_node: The document node describing the source node.
        path: The path to the destination_node (excluding the destination node itself).
    """
    ids = {}
    node_id = doc[source_node.id_property]
    node_name = source_node.name

    for node in reversed(path):
        ids[node.name] = _get_namespaced_uuid(node_name, node_id)
        node_id, node_name = ids[node.name], node.name

    return ids


def _move_document_node(
    root: dict, doc: dict, destination_path: Sequence[DocumentNode]
) -> None:
    """Put the data in doc at the destination path in the root.

    This function will generate new nodes for intermediary nodes in the destination
    path.

    Args:
        root: The document in which the data should be places.
        doc: The data which will be placed at the destination
        destination_path: The path describing the location in the root where the data in
            doc should be placed.
    """
    destination_node = destination_path[-1]
    destination_path = destination_path[:-1]
    generated_ids = _generate_ids(doc, destination_node, destination_path)

    def generate_node(parent: dict, node: DocumentNode) -> dict:
        """Generate a new node within the given parent node.

        Args:
            parent: The parent node that will have a node of with the indicated name
                added.
            node: The document node that needs to be added to the parent.

        Returns:
            The newly created node.
        """
        doc = {node.id_property: generated_ids[node.name]}

        parent.setdefault(node.name, []).append(doc)

        return doc

    parent = functools.reduce(generate_node, destination_path, root)

    parent.setdefault(destination_node.name, []).append(doc)


def _move_document_nodes(
    roots: Iterable[dict],
    source_path: Sequence[DocumentNode],
    destination_path: Sequence[DocumentNode],
) -> None:
    """Put data in the source path in the roots at the node in the destination path.

    See public function for more details.

    Args:
        roots: The dictionaries containing the paths described in which the data will
            be moved.
        source_path: The path of document nodes where the terminus node contains the
            data to be copied.
        destination_path: The path to the new document node where the data should be
            copied.
    """
    destination_node = destination_path[-1]
    current_ids = frozenset(
        d[destination_node.id_property] for d in _walk_path(roots, destination_path)
    )
    source_node = source_path[-1]
    sources = ((r, d) for r in roots for d in _walk_path(r, source_path))

    for root, source in sources:
        if source[source_node.id_property] not in current_ids:
            _move_document_node(root, source, destination_path)


def move_document_nodes(
    doc: dict,
    source_path: Sequence[DocumentNode],
    destination_path: Sequence[DocumentNode],
) -> None:
    """Put data from the node at the end of the source path at the destination path.

    This modifies the given document by carrying out the given process. The data is only
    copied unless a node with in the specified source path has a node marked for removal
    via DocumentNode(...).remove().

    Notes:
        - If any nodes are missing from the destination path, then a dummy node is
        created with an ID based on their child node's ID.
        - If the source node has an ID that already exists in the destination then the
        data will not be copied.

    Args:
        doc: The dictionary containing the paths described in which the data will be
            moved.
        source_path: The path of document nodes where the terminus node contains the
            data to be copied.
        destination_path: The path to the new document node where the data should be
            copied.

    Example:
        Nodes:
            samples: DocumentNode("samples", "sample_id")
            portions: DocumentNode("portions", "portion_id")
            analytes: DocumentNode("analytes", "analyte_id")
            aliquots: DocumentNode("aliquots", "aliquot_id")
        Paths:
            source_path: (samples, aliquots.remove())  # we want to remove aliquot node.
            destination_path: (samples, portions, analytes, aliquots)
        Doc: {
            "samples": [
                {
                    "sample_id": "sample-0",
                    "aliquots: [
                        {"aliquot_id": "aliquot-0"}
                    ]
                }
            ]
        }

        move_document_nodes(doc, source_path, destination_path)

        Result: {
            "samples": [
                {
                    "sample_id": "sample-0",
                    "portions": [
                        {
                            "portion_id": uuid(analyte_id),
                            "analytes: [
                                {
                                    "analyte_id": uuid("aliquot-0"),
                                    "aliquots": [
                                        {
                                            "aliquot_id": "aliquot-0"
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                }
            ]
        }


    """
    common_path = tuple(
        map(
            more_itertools.first,
            itertools.takewhile(
                lambda n: n[0].name == n[1].name, zip(source_path, destination_path)
            ),
        )
    )
    source_path = source_path[len(common_path) :]
    destination_path = destination_path[len(common_path) :]
    # find all common roots for sources/destinations
    roots = tuple(_walk_path(doc, common_path))

    _move_document_nodes(roots, source_path, destination_path)
