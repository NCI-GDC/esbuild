# -*- coding: utf-8 -*-
"""
esbuild.graph.common.mimic
----------------------------------

Mimics the isolation of functionality such as filtering nodes from the
index.

"""
from collections.abc import Iterable

import logging

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class CommonMimic(object):
    """Mixin for mimic classes"""

    def neighbors_labeled(self, node, labels, *args, **kwargs):
        """For a given node, return an iterator with generates neighbors to
        that node that are in a list of labels.  `label` can be either a
        string or list of strings.

        .. note::
            This is mocked to use association proxies as a workaround
            to the assumption that the real builder will have the
            entire graph cached.

        """

        if isinstance(labels, Iterable) and not isinstance(labels, str):
            labels = set(labels)
        else:
            labels = {labels}

        return [
            edge.dst
            for edge in node.edges_out
            if edge.dst.label in labels
        ] + [
            edge.src
            for edge in node.edges_in
            if edge.src.label in labels
        ]
