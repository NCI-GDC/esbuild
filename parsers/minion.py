from base import BaseArgs


class MinionArgs(BaseArgs):
    """
    Arguments for esbuild build minion controller
    """
    args = {
        'do_not_wait_for_completion',
    }

    def add_args(self, parser):
        parser.add_argument(
            '--do-not-wait-for-completion', action='store_true',
            help='If set, will not wait for esbuild completion. '
            'Will result in all jobs in the queue being run on the machine'
        )
        return parser
