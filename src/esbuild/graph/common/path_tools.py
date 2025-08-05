"""A module for finding and manipulating paths within the GDC graph."""

import functools
from collections.abc import (
    Collection,
    Container,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    Set,
)

import more_itertools
from gdcdatamodel2 import models


def _get_entity_path(
    entities: Container[str], file_path: Sequence[str]
) -> Sequence[str]:
    """Get the first valid entity path from given file_path.

    NOTE: this function assumes that the file path contains at least one of the given
    entities

    Args:
        entities: The entities to be searched for as a source for the new path.
        file_path: A super path from a some entity to the file which includes one of the
            given entities.

    Returns:
        The path from the file to one of the given entities.
    """
    entity_path: Iterable[str] = reversed(file_path[:-1])
    entity_path = more_itertools.takewhile_inclusive(
        lambda p: p not in entities, entity_path
    )

    return tuple(entity_path)


def get_entity_paths(
    entities: Collection[str], file_paths: Iterable[Sequence[str]]
) -> Mapping[str, Iterable[Sequence[str]]]:
    """Build a mapping of a file to all unique paths to the given entities.

    Args:
        entities: The entities that should be found at the end of the resulting paths.
        file_paths: The paths from the case node to the files.

    Returns:
        A mapping of file labels and their associated paths to the desired entities.
    """
    file_paths = filter(lambda p: any(e in p for e in entities), file_paths)

    return more_itertools.map_reduce(
        file_paths,
        keyfunc=more_itertools.last,
        valuefunc=functools.partial(_get_entity_path, entities),
        reducefunc=frozenset,
    )


def find_paths(
    source: type[models.Node],
    destinations: Container[type[models.Node]],
    excluded_paths: Set[type[models.Node]] = frozenset(),
    visited: Sequence[type[models.Node]] = (),
) -> Iterator[Sequence[str]]:
    """Find all paths from the source to all destination nodes in the graph.

    Args:
        source: The source node at which all paths should begin.
        destinations: The nodes for which the paths to them should be yielded.
        excluded_paths: A set of nodes which if a path passes through should be excluded
            from the result.
        visited: A sequence of nodes which has already been encountered leading up to
            the source node. NOTE: In general, this is for internal use of the function.

    Yields:
        Paths from the given source node to any of the encountered destinations.
    """
    if source in destinations:
        yield tuple(n.label for n in visited)

    children: Iterable[type[models.Node]] = (
        br["src_type"] for br in source._pg_backrefs.values()
    )
    children = filter(lambda c: c not in visited and c not in excluded_paths, children)

    for child in children:
        yield from find_paths(
            child,
            destinations,
            excluded_paths,
            visited=(*visited, child),
        )
