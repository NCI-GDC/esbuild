# -*- coding: utf-8 -*-
"""
esbuild.graph.common.fake_node
----------------------------------

Create a smaller, faster, serializable psqlgraph.Node replacement

"""


class FakeNode(object):

    def __init__(self, node):
        props = dict(node.props)
        sysan = dict(node._sysan)
        acl = list(node.acl)
        label = str(node.label)
        node_id = str(node.node_id)

        self._class_name = str(node.__class__.__name__)
        self.node_id = node_id
        self.acl = acl
        self.label = label

        self._props = props
        self.properties = props
        self.props = props

        self._sysan = sysan
        self.system_annotations = sysan
        self.sysan = sysan

        self.__pg_properties__ = node.__pg_properties__
        self._pg_links = node._pg_links
        self._pg_backrefs = node._pg_backrefs
        self._pg_edges = node._pg_edges
        self._dictionary = node._dictionary

        for key, value in props.iteritems():
            setattr(self, key, value)

    def __repr__(self):
        return '<{}({})>'.format(self._class_name, self.node_id)

    def __getitem__(self, key):
        return self.props[key]
