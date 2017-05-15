#!/usr/bin/env python

from esbuild.gdc_elasticsearch import GDCElasticsearch
from esbuild.graph.active.builder import ActiveGraphIndexBuilder

import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--no-roll', action="store_true",
        help='if passed, do not roll the alias and delete old indices')
    parser.add_argument(
        '--delete', action="store_true",
        help='if passed, delete the nodes marked "to_delete" after running, unless --json_delete is passed')
    parser.add_argument(
        '--json_delete',
        help='file to use to delete nodes and skip running esbuild')

    args = parser.parse_args()
    gdc_es = GDCElasticsearch(converter_class=ActiveGraphIndexBuilder)
    if args.delete:
        if not args.json_delete:
            gdc_es.go(roll_alias=not args.no_roll,
                      delete_nodes=args.delete,
                      skip_build=args.test_delete)
        else:
            nodes_to_delete=[]
            with open(args.json_delete, 'r') as in_file:
                for line in in_file:
                    nodes_to_delete.append(line.strip('\n'))
            gdc_es.delete_nodes(to_delete=nodes_to_delete,
                          delete_nodes=args.delete)
    else:
        gdc_es.go(roll_alias=not args.no_roll,
                  delete_nodes=args.delete,
                  skip_build=args.test_delete)

if __name__ == "__main__":
    main()
