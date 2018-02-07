import argparse
from esbuild.gdc_elasticsearch import GDCElasticsearch


def esbuild_argparser():
    """
    Returns argument parser for esbuild
    """
    parser = argparse.ArgumentParser(description='Parameters to control esbuild runs')
    parser.add_argument(
        '--no-roll', action="store_true",
        help='If passed, do not roll the alias and delete old indices')
    parser.add_argument(
        '--no-cleanup', action="store_true",
        help='If passed, do not delete old indices')
    parser.add_argument(
        '--delete', action="store_true",
        help='If passed, delete the nodes in the json file passed with --json_delete')
    parser.add_argument(
        '--skip_es', action="store_true",
        help='If passed, skip any actual action on es, just build json')
    parser.add_argument(
        '--json_delete',
        help='File to use to delete nodes')
    parser.add_argument(
        '--test_delete', action='store_true',
        help='Test the deletion (skip load & build of index)')
    parser.add_argument(
        '--projects', nargs='*',
        help='If set, builds only set of projects specified (space-separated)',
        required=False)
    parser.add_argument(
        '--index', help='Index name to upsert projects to. '
        'Must set when building subset of projects')
    parser.add_argument(
        '--selective-caching', action='store_true',
        help='If set, only caches nodes for projects needed. '
        'WARNING: Will skip nodes that do not have project_id',
        default=False)
    parser.add_argument(
        '--build-awg', action='store_true',
        help='If set, will build in AWG mode. '
        'Will pick up only projects flagged as awg_review = true and '
        'nodes that are part of these projects and are in any of allowed states',
        default=False)

    return parser


def main(converter, index_base):

    args = esbuild_argparser().parse_args()

    if args.projects:
        if not args.index and not args.skip_es:
            raise Exception('Provide --index <index_name> when using '
                            'partial build mode')

    gdc_es = GDCElasticsearch(
        converter_class=converter,
        build_projects=args.projects,
        build_awg=args.build_awg,
        index_name=args.index,
        index_base=index_base,
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
                  cleanup_indices=not args.no_cleanup,
                  skip_build=args.test_delete)
