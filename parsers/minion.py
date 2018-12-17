from base import BaseParser


class MinionArgs(BaseParser):
    """
    Arguments for esbuild build minion controller
    """

    @property
    def group(self):
        return dict(
            title='Esbuild minion arguments',
            description='Settings related to esbuild minion',
        )

    @property
    def arguments(self):
        return {
            'n-threads': dict(
                help='If set, will spawn multiple threads running minion.py',
                default=1,
            ),
        }
