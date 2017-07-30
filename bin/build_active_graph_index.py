#!/usr/bin/env python

from base_build import main
from esbuild.graph.active.builder import ActiveGraphIndexBuilder


if __name__ == "__main__":
    main(ActiveGraphIndexBuilder, index_base='gdc_from_graph')
