# -*- coding: utf-8 -*-
"""
esbuild.graph.common.util
----------------------------------

Common utilities for things like logging

"""

from sqlalchemy.ext.declarative.api import DeclarativeMeta
from psqlgraph import Node

from datadog import statsd

from progressbar import (
    ProgressBar,
    Percentage,
    Bar,
    ETA,
)


def upsert_file_into_dict(files, file_doc):
    """Merge this file document into all other relevant file documents (or
    just add it if none exist)

    TODO: make this more descriptive

    """

    did = file_doc['file_id']

    if did not in files:
        files[did] = file_doc
        return

    for case in file_doc['cases']:
        case_id = case['case_id']

        existing_ids = {
            case['case_id']
            for case in files[did]['cases']
        }

        if case_id not in existing_ids:
            files[did]['cases'] += file_doc['cases']


def get_node_class(entity):
    if isinstance(entity, DeclarativeMeta):
        return entity

    try:
        return Node.get_subclass(entity.label())
    except TypeError:
        return Node.get_subclass(entity.label)


def get_file_to_case_paths(cls, file_to_case_paths):
    """Given a node, return the paths the lead monotonically up to case"""

    parent_labels = {
        link['dst_type'].label
        for link in get_node_class(cls)._pg_links.values()
    }

    return (
        path
        for path in file_to_case_paths
        if path and path[0] in parent_labels
    )

def reverse_paths(paths, starting_label):
    """Reverse the paths and add starting label to end of reversed paths"""

    return [
        list(reversed(l))[1:]+[starting_label]
        for l in paths
    ]


def remove_index_files(files, index_file_extensions):
    """Returns a set of files that are not index files"""

    return {
        file_ for file_ in files
        if not is_index_file(file_, index_file_extensions)
    }


def is_index_file(node, index_file_extensions):
    """Given a node, return whether it is considerend an 'index file'

    :returns: bool

    """

    # Active index files
    if node._dictionary['category'] == 'index_file':
        return True

    # Legacy index files
    elif node.label == 'file':
        for extension in index_file_extensions:
            if node._props.get('file_name', '').endswith(extension):
                return True

    else:
        return False


def log_warning(logger, title, text, tags=[], *args, **kwargs):
    """Log a warning to logger and statsd"""

    logger.warning("{}: {}".format(title, text))
    statsd.event(
        title,
        text,
        source_type_name="esbuild",
        alert_type="warning",
        tags=tags,
    )


def log_error(logger, title, text, tags=[], *args, **kwargs):
    """Log an error to logger and statsd"""

    logger.error("{}: {}".format(title, text))
    statsd.event(
        title,
        text,
        source_type_name="esbuild",
        alert_type="error",
        tags=tags,
    )


def truncate_path(path, label):
    """
    Given a path (a list of node labels), "truncate" it from the left
    such that it starts with the given label, or return [], e.g.:

    truncate_path(["a", "b", "c"], "a") -> ["b", "c"]
    truncate_path(["c", "d"], "b") -> []

    """
    for i, currlabel in enumerate(path):
        if currlabel == label:
            return path[i+1:]
    return []


def get_pbar(title, maxval):
    """Create and initialize a custom progressbar

    :param str title: The text of the progress bar
    :param int maxval: The maximumum value of the progress bar

    """
    maxval = maxval or 1  # prevent maxal of 0
    pbar = ProgressBar(widgets=[
        title, Percentage(), ' ',
        Bar(marker='#', left='[', right=']'), ' ',
        ETA(), ' '], maxval=maxval)
    pbar.update(0)
    return pbar
