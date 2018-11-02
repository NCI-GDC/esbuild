from base import BaseArgs


class MasterArgs(BaseArgs):
    """
    Arguments for esbuild build master controller
    """
    args = {
        'build_type',
        'index_type',
        'label',
        'version',
        'n_workers',
        'skip_projects',
        'split_by_program',
    }

    def add_args(self, parser):
        es_args = parser.add_argument_group(
            title='Esbuild master arguments',
            description='Settings related to esbuild orchestration',
        )
        es_args.add_argument(
            '--n-workers', help='Number of workers to split esbuild between',
            type=int,
            required=True,
        )
        es_args.add_argument(
            '--index-type', help='Type of index to build',
            choices=['active', 'legacy', 'awg'],
            required=True,
        )
        es_args.add_argument(
            '--build-type', help='Indicates if the build meant for the release. '
            'If release, other arguments\' values are restricted',
            choices=['release', 'test'],
            required=True,
        )
        es_args.add_argument(
            '--label', help='Label for the index. '
            'Must match the name in the release node if build-type=="release"',
            required=True,
        )
        es_args.add_argument(
            '--version',
            help='Version number (e.g. "13 4" for release or "2" for test). '
            'Must match release version in the release node if build-type=="release"',
            nargs='*',
            type=int,
            required=True,
        )
        es_args.add_argument('--split-by-program', action='store_true',
                             help='If set, splits all projects into groups by program',
                             default=False)
        es_args.add_argument('--skip-projects', nargs='*',
                             help='Set of projects to skip')

        return parser
