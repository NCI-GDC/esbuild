# -*- coding: utf-8 -*-
"""
esbuild.graph.active.mimic
----------------------------------

Mimics the isolation of functionality such as filtering nodes from the
index.

"""

from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.graph.common.mimic import CommonMimic


class ActiveMimic(CommonMimic, ActiveGraphIndexBuilder):
    pass
