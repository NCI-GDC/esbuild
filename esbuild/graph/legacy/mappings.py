# -*- coding: utf-8 -*-
"""esbuild.graph.legacy.mappings
----------------------------------

Defines the Elasticsearch mappings for the main GDC graph index.

.. _hierarchy-format:

    The hierarchies defined below will contain a tuple (CORR, name),
    where CORR is the expected correlation and ``name`` is what key to
    nest the child documents under

"""

from gdcdatamodel import models  # noqa

from ..common.mappings import (
    ESMapper,
)


class LegacyESMapper(ESMapper):
    pass
