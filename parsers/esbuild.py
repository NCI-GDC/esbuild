from base import BaseArgs


class EsbuildArgs(BaseArgs):
    args = {
        'no_roll',
        'no_cleanup',
        'delete',
        'skip_es',
        'json_delete',
        'test_delete',
        'projects',
        'index_name',
        'selective_caching',
    }

    def add_args(self, parser):
        """
        Add esbuild arguments to parser
        """
        esbuild_args = parser.add_argument_group(
            title='Esbuild arguments',
            description='Esbuild worker settings',
        )

        esbuild_args.add_argument(
            '--no-roll', action="store_true",
            help='If passed, do not roll the alias and delete old indices',
        )
        esbuild_args.add_argument(
            '--no-cleanup', action="store_true",
            help='If passed, do not delete old indices',
        )
        esbuild_args.add_argument(
            '--delete', action="store_true",
            help='If passed, delete the nodes in the json file passed with --json_delete',
        )
        esbuild_args.add_argument(
            '--skip_es', action="store_true",
            help='If passed, skip any actual action on es, just build json',
        )
        esbuild_args.add_argument(
            '--json_delete',
            help='File to use to delete nodes',
        )
        esbuild_args.add_argument(
            '--test_delete', action='store_true',
            help='Test the deletion (skip load & build of index)',
        )
        esbuild_args.add_argument(
            '--projects', nargs='*',
            help='If set, builds only set of projects specified (space-separated)',
        )
        esbuild_args.add_argument(
            '--index-name', help='Index name to upsert projects to. '
            'Must set when building subset of projects',
        )
        esbuild_args.add_argument(
            '--selective-caching', action='store_true',
            help='If set, only caches nodes for projects needed. '
            'WARNING: Will skip nodes that do not have project_id',
            default=False,
        )

        return parser
