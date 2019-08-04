import argparse
from indexclient.client import IndexClient
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
    parser.add_argument(
        '--save_doc_path',
        help='Where to save docs (if necessary)',
        default='/var/log/esbuild')

    return parser


def main(converter=None,
         indexd_args=None,
         index_base=None,
         work=None):

    indexd_client = IndexClient(**indexd_args)

    if work.get('projects'):
        if not work.get('index') and not work.get('skip_es'):
            raise Exception('Provide --index <index_name> when using '
                            'partial build mode')

    gdc_es = GDCElasticsearch(
        indexd_client=indexd_client,
        converter_class=converter,
        build_projects=list(work.get('projects').split()),
        build_awg=work.get('build-awg'),
        index_name=work.get('index'),
        index_base=index_base,
        skip_es=work.get('skip-es'),
        selective_caching=work.get('selective-caching'),
    )
    gdc_es.go(roll_alias=not work.get('no-roll'),
              cleanup_indices=not work.get('no-cleanup'),
              skip_build=work.get('test-delete'))
