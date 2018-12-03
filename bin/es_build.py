import os

from indexclient.client import IndexClient

from esbuild.gdc_elasticsearch import GDCElasticsearch
from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder
from parsers import (
    ParserBuilder,
    EsbuildUserArgs,
    EsbuildPrivateArgs,
)


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
    parser = ParserBuilder.build([EsbuildUserArgs, EsbuildPrivateArgs])

    args = parser.parse_args()
    return args


def get_converter(index_type):
    if index_type == 'active':
        return ActiveGraphIndexBuilder
    elif index_type == 'legacy':
        return LegacyGraphIndexBuilder
    else:
        raise ValueError('No builder for {}'.format(index_type))


def main():
    """
    Main entry point for esbuild
    The build settings are controlled with user-provided args
    """

    indexd_client = get_indexd()
    args = get_args()
    converter = get_converter(args.index_type)

    if args.projects:
        if not args.index_name and not args.skip_es:
            raise Exception('Provide --index <index_name> when using '
                            'partial build mode')

    gdc_es = GDCElasticsearch(
        converter_class=converter,
        indexd_client=indexd_client,
        build_projects=args.projects,
        build_awg=args.build_awg,
        index_name=args.index_name,
        skip_es=args.skip_es,
        selective_caching=args.selective_caching,
    )
    if args.delete:
        if not args.json_delete:
            gdc_es.go(roll_alias=not args.no_roll,
                      delete_nodes=args.delete,
                      skip_build=args.test_delete)
        else:
            nodes_to_delete = []
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
