from unittest import mock

import more_itertools

from esbuild.graph.common import path_tools


def test__find_paths__simple_path() -> None:
    """Test a simple path w/o loops or excluded paths.

    Given:
        Graph:
            grand_parent -> parent -> child

    When:
        find_paths(source=child, destinations=(grand_parent,))

    Then:
        ("parent", "grand_parent")
    """
    grand_parent = mock.MagicMock(label="grand_parent", _pg_backrefs={})
    parent = mock.MagicMock(
        label="parent", _pg_backrefs={"grand-parent-parent": {"src_type": grand_parent}}
    )
    child = mock.MagicMock(
        label="child",
        _pg_backrefs={"parent-child": {"src_type": parent}},
    )

    paths = tuple(path_tools.find_paths(source=child, destinations=(grand_parent,)))

    assert len(paths) == 1
    assert ("parent", "grand_parent") == paths[0]


def test__find_paths__circular_path() -> None:
    """Test that a circular path is not followed.

    Given:
        Graph:
            grand_parent -> parent -> child;
            parent -> grand_parent;

    When:
        find_paths(source=child, destinations=(grand_parent,))

    Then:
        ("parent", "grand_parent")
    """
    grand_parent = mock.MagicMock(label="grand_parent")
    parent = mock.MagicMock(
        label="parent", _pg_backrefs={"grand-parent-parent": {"src_type": grand_parent}}
    )
    grand_parent._pg_backrefs = {
        "parent-grand-parent": {"src_type": parent}
    }  # Circular path we need to avoid.
    child = mock.MagicMock(
        label="child",
        _pg_backrefs={"parent-child": {"src_type": parent}},
    )

    paths = tuple(path_tools.find_paths(source=child, destinations=(grand_parent,)))

    assert len(paths) == 1
    assert ("parent", "grand_parent") == paths[0]


def test__find_paths__exclude_path() -> None:
    """Test graph with a path that needs to be excluded.

    Given:
        Graph:
            grand_parent -> parent -> child;
            grand_parent -> bad_node -> child;

    When:
        find_paths(
            source=child,
            destinations=(grand_parent,),
            excluded_paths=(bad_node,),
        )

    Then:
        ("parent", "grand_parent")
    """
    grand_parent = mock.MagicMock(label="grand_parent", _pg_backrefs={})
    parent = mock.MagicMock(
        label="parent", _pg_backrefs={"grand-parent-parent": {"src_type": grand_parent}}
    )
    bad_node = mock.MagicMock(
        label="bad", _pg_backrefs={"parent-bad": {"src_type": parent}}
    )  # a path to be excluded.
    child = mock.MagicMock(
        label="child",
        _pg_backrefs={
            "parent-child": {"src_type": parent},
            "bad-child": {"src_type": bad_node},
        },
    )

    paths = tuple(
        path_tools.find_paths(
            source=child,
            destinations=(grand_parent,),
            excluded_paths=frozenset((bad_node,)),
        )
    )

    assert len(paths) == 1
    assert ("parent", "grand_parent") == paths[0]


def test__get_entity_paths__collect_valid_paths() -> None:
    file_paths = (
        ("case", "sample", "file"),
        ("case", "sample", "aliquot", "file"),
        ("case", "sample", "portion", "analyte", "aliquot", "file"),
        ("case", "file"),  # excluded as contains
    )
    entities = frozenset(("sample", "aliquot", "portion"))

    entity_paths = path_tools.get_entity_paths(entities, file_paths)

    assert len(entity_paths) == 1 and "file" in entity_paths
    assert more_itertools.ilen(entity_paths["file"]) == 2
    assert entity_paths["file"] == frozenset((("sample",), ("aliquot",)))
