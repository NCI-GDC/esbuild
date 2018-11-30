from indexclient.client import IndexClient
from esbuild.gdc_elasticsearch import GDCElasticsearch
from parsers import (
    ParserBuilder,
    EsbuildUserArgs,
    EsbuildPrivateArgs,
)


def main(converter, indexd_args, index_alias):

    indexd_client = IndexClient(**indexd_args)
    parser = ParserBuilder.build([EsbuildUserArgs, EsbuildPrivateArgs])
    args = parser.parse_args()

    if args.projects:
        if not args.index_name and not args.skip_es:
            raise Exception('Provide --index <index_name> when using '
                            'partial build mode')

    gdc_es = GDCElasticsearch(
        indexd_client=indexd_client,
        converter_class=converter,
        build_projects=args.projects,
        build_awg=args.build_awg,
        index_name=args.index_name,
        index_alias=index_alias,
        skip_es=args.skip_es,
        selective_caching=args.selective_caching,
    )
    if args.delete:
        if not args.json_delete:
            gdc_es.go(roll_alias=not args.no_roll,
                      delete_nodes=args.delete,
                      cleanup_indices=not args.no_cleanup,
                      skip_build=args.test_delete)
        else:
            nodes_to_delete = []
            with open(args.json_delete, 'r') as in_file:
                for line in in_file:
                    nodes_to_delete.append(line.strip('\n'))
            gdc_es.delete_nodes(to_delete=nodes_to_delete,
                                cleanup_indices=not args.no_cleanup,
                                delete_nodes=args.delete)
    else:
        gdc_es.go(roll_alias=not args.no_roll,
                  delete_nodes=args.delete,
                  skip_build=args.test_delete)
