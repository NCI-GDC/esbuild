import argparse
from esbuild.gdc_elasticsearch import GDCElasticsearch


def main(converter, index_base):
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--no-roll', action="store_true",
        help='if passed, do not roll the alias and delete old indices')
    parser.add_argument(
        '--no-cleanup', action="store_true",
        help='if passed, do not delete old indices')
    parser.add_argument(
        '--delete', action="store_true",
        help='if passed, delete the nodes in the json file passed with --json_delete')
    parser.add_argument(
        '--skip_es', action="store_true",
        help='if passed, skip any actual action on es, just build json')
    parser.add_argument(
        '--json_delete',
        help='file to use to delete nodes')
    parser.add_argument(
        '--test_delete', action='store_true',
        help='Test the deletion (skip load & build of index)')
    parser.add_argument(
        '--projects', nargs='*',
        help='Partial build. Takes list of projects',
        required=False)
    parser.add_argument(
        '--upsert-to', help='Index name to upsert projects to')
    parser.add_argument(
        '--selective-caching', action='store_true',
        help='If set, only caches nodes for projects needed. '
        'WARNING: Will skip nodes that do not have project_id',
        default=False)

    args = parser.parse_args()

    if args.projects:
        if not args.skip_es:
            if not args.upsert_to:
                raise Exception('Provide --upsert-to <index_name> when using '
                                'partial build mode')

    gdc_es = GDCElasticsearch(
        converter_class=converter,
        build_projects=args.projects,
        index_name=args.upsert_to,
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
