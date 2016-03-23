#!/usr/bin/env python

from esbuild.gdc_elasticsearch import GDCElasticsearch
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder

from esbuild.graph.legacy.mappings import (
    get_annotation_es_mapping,
    get_case_es_mapping,
    get_file_es_mapping,
    get_project_es_mapping,
)

import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--no-roll', action="store_true",
        help='if passed, do not roll the alias and delete old indices')

    args = parser.parse_args()

    gdc_es = GDCElasticsearch(
        converter_class=LegacyGraphIndexBuilder,
        annotation_mapping=get_annotation_es_mapping(),
        case_mapping=get_case_es_mapping(),
        file_mapping=get_file_es_mapping(),
        project_mapping=get_project_es_mapping(),
    )

    gdc_es.go(roll_alias=not args.no_roll)

if __name__ == "__main__":
    main()
