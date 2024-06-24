import functools
from collections.abc import Collection, Container, Iterable, Iterator, Sequence, Set
from typing import Mapping

import more_itertools
from gdcdatamodel2 import models


def _get_entity_path(
    entities: Container[str], file_path: Sequence[str]
) -> Sequence[str]:
    specimen_path: Iterable[str] = reversed(file_path[:-1])
    specimen_path = more_itertools.takewhile_inclusive(
        lambda p: p not in entities, specimen_path
    )

    return tuple(specimen_path)


def get_entity_paths(
    entities: Collection[str], file_paths: Iterable[Sequence[str]]
) -> Mapping[str, Iterable[Sequence[str]]]:
    """Build a mapping of a file to all paths to the given entities.

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
