#!/usr/bin/env python

from esbuild.gdc_elasticsearch import GDCElasticsearch
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder

import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--no-roll', action="store_true",
        help='if passed, do not roll the alias and delete old indices')

    args = parser.parse_args()
    gdc_es = GDCElasticsearch(
        converter_class=LegacyGraphIndexBuilder,
        index_base="gdc_legacy_graph",
    )
    gdc_es.go(roll_alias=not args.no_roll)

if __name__ == "__main__":
    main()
