import argparse
from indexclient.client import IndexClient
from esbuild.gdc_elasticsearch import GDCElasticsearch


def esbuild_argparser():
    """
    Returns argument parser for esbuild
    """
    parser = argparse.ArgumentParser(
        description='Parameters to control esbuild runs',
    )
    parser.add_argument(
        '--no-roll', action="store_true",
        help='If passed, do not roll the alias and delete old indices')
    parser.add_argument(
        '--no-cleanup', action="store_true",
        help='If passed, do not delete old indices')
    parser.add_argument(
        '--skip_es', action="store_true",
        help='If passed, skip any actual action on es, just build json')
    parser.add_argument(
        '--projects', nargs='*',
        help='If set, builds only set of projects specified (space-separated)',
        required=False)
    parser.add_argument(
        '--index', help='Index name to upsert projects to. '
        'Must set when building subset of projects')
    parser.add_argument(
        "--alias", help="Index alias to use for index swap",
    )
    parser.add_argument(
        '--replicas',
        help='Number of replicas to set when creating an index (default: 0)',
        type=int,
        default=0,
    )
    parser.add_argument(
        '--shards',
        help='Number of shards to set when creating an index (default: 1)',
        type=int,
        default=1,
    )
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
        '--cache-versioned',
        action='store_true',
        help='Collect differences for versioned unreleased files',
    )

    return parser


def main(converter=None,
         indexd_args=None,
         index_alias=None,
         work=None,
         es5=False):

    indexd_client = IndexClient(**indexd_args)

    if work is None:
        raise ValueError("Received empty work")

    if work.get('projects'):
        if not work.get('index') and not work.get('skip_es'):
            raise Exception('Provide --index <index_name> when using '
                            'partial build mode')

    gdc_es = GDCElasticsearch(
        indexd_client=indexd_client,
        converter_class=converter,
        build_projects=list(work.get('projects').split()),
        build_awg=work.get('build-awg'),
        index_prefix=work.get('index'),
        index_replicas=work.get('replicas'),
        index_shards=work.get('shards'),
        index_alias_prefix=index_alias,
        skip_es=work.get('skip-es'),
        selective_caching=work.get('selective-caching'),
        cache_versioned=work.get('cache-versioned'),
        save_doc_path=work.get('save-doc-path'),
        es5=es5,
    )
    gdc_es.go(roll_alias=not work.get('no-roll'))
