import os
import datetime

import config as conf
from indexclient.client import IndexClient

from esbuild.gdc_elasticsearch import GDCElasticsearch
from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder
from parsers import ParserBuilder


def get_indexd():
    """
    Instancieates IndexClient
    """
    indexd_args = {'baseurl': os.environ.get('INDEXD_HOST'),
                   'auth': (os.environ.get('INDEXD_USER'),
                            os.environ.get('INDEXD_PASS'))}
    indexd_client = IndexClient(**indexd_args)
    return indexd_client


def get_args():
    """
    Parses and returns esbuild arguments
    """
    parser = ParserBuilder.build(conf.ESBUILD_PARSERS)

    args = parser.parse_args() 
    return args


def get_converter(index_type):
    if index_type == 'active':
        return ActiveGraphIndexBuilder
    elif index_type == 'legacy':
        return LegacyGraphIndexBuilder
    else:
        raise ValueError('No builder for {}'.format(index_type))


def main(args=None):
    """
    Main entry point for esbuild
    The build settings are controlled with user-provided args
    """
    start_time = datetime.datetime.now()
    indexd_client = get_indexd()
    if args is None:
        args = get_args()
    converter = get_converter(args.index_type)

    if args.build_projects:
        if not args.index_name:
            raise Exception('Provide --index <index_name> when using '
                            'partial build mode')

    gdc_es = GDCElasticsearch(converter, indexd_client, args)

    if args.delete:
        if not args.json_delete:
            gdc_es.go(delete_nodes=args.delete,
                      skip_build=args.test_delete)
        else:
            nodes_to_delete = []
            with open(args.json_delete, 'r') as in_file:
                for line in in_file:
                    nodes_to_delete.append(line.strip('\n'))
            gdc_es.delete_nodes(to_delete=nodes_to_delete,
                                delete_nodes=args.delete)
    else:
        gdc_es.go(delete_nodes=args.delete,
                  skip_build=args.test_delete)

    return start_time, datetime.datetime.now()


if __name__ == "__main__":
    main()
