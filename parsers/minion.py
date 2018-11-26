from base import Parser


class MinionArgs(Parser):
    """
    Arguments for esbuild build minion controller
    """
    group = dict(
        title='Esbuild minion arguments',
        description='Settings related to esbuild minion',
    )

    arguments = {
        'do-not-wait-for-completion': dict(
            help='If set, will not wait for esbuild completion. '
            'Will result in all jobs in the queue being run on the machine',
            action='store_true',
        ),
    }
