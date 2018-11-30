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
            'do-not-wait-for-completion': dict(
                help='If set, will not wait for esbuild completion. '
                'Will result in all jobs in the queue being run on the machine',
                action='store_true',
            ),
        }
