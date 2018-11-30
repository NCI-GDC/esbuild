from base import BaseParser


class MasterArgs(BaseParser):
    """
    Arguments for esbuild build master controller
    """

    @property
    def group(self):
        return dict(
            title='Esbuild master arguments',
            description='Settings related to esbuild orchestration',
        )

    @property
    def arguments(self):
        return {
            'n-workers': dict(
                help='Number of workers to split esbuild between',
                required=True,
                type=int,
            ),
            'index-type': dict(
                help='Type of index to build',
                choices=['active', 'legacy', 'awg', 'test'],
                required=True,
            ),
            'build-type': dict(
                help='Indicates if the build meant for the release. '
                'If release, other arguments\' values are restricted',
                choices=['release', 'develop'],
                required=True,
            ),
            'label': dict(
                help='Label for the index (will be automatically assigned to the value in '
                'DataRelease node for release candidate if --build-type == "release")',
                default='esbuild',
            ),
            'version': dict(
                help='Version number (will be automatically assigned to the value in '
                'DataRelease node for release candidate if --build-type == "release")',
                nargs=1,
                type=int,
                default=[0],
            ),
            'split-by-program': dict(
                action='store_true',
                help='If set, splits all projects into groups by program',
                default=False,
            ),
            'skip-projects': dict(
                nargs='*',
                help='Set of projects to skip',
            ),
        }
