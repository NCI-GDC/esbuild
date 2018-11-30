#!/usr/bin/env python

import os

from base_build import main
from esbuild.graph.active.builder import ActiveGraphIndexBuilder


if __name__ == "__main__":
    indexd_args = {'baseurl': os.environ.get('INDEXD_HOST'),
                   'auth': (os.environ.get('INDEXD_USER'),
                            os.environ.get('INDEXD_PASS'))}
    main(ActiveGraphIndexBuilder, indexd_args, index_alias='gdc_from_graph')
