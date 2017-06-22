#!/usr/bin/env python

from base_build import main
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder


if __name__ == "__main__":
    main(LegacyGraphIndexBuilder)
