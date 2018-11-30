#!/usr/bin/env python

import os

from base_build import main
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder


if __name__ == "__main__":
    indexd_args = {'baseurl': os.environ.get('INDEXD_HOST'),
                   'auth': (os.environ.get('INDEXD_USER'),
                            os.environ.get('INDEXD_PASS'))}
    main(LegacyGraphIndexBuilder, indexd_args, index_alias='gdc_legacy_graph')
