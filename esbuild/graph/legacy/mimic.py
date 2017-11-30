# -*- coding: utf-8 -*-
"""
esbuild.graph.legacy.mimic
----------------------------------

Mimics the isolation of functionality such as filtering nodes from the
index.

"""

from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder
from esbuild.graph.common.mimic import CommonMimic


class LegacyMimic(CommonMimic, LegacyGraphIndexBuilder):
    pass
