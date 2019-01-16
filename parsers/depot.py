from base import BaseParser


class DepotArgs(BaseParser):
    """
    Arguments to interact with Depot queue service
    """

    @property
    def group(self):
        return dict(
            title='Depot server arguments',
            description='Arguments related to Depot job queue service',
        )

    @property
    def arguments(self):
        return {
            'depot-host': dict(
                help='Depot server host',
                required=True,
            ),
            'depot-port': dict(
                help='Depot server port',
                required=True,
                type=int,
            ),
            'queue-id': dict(
                help='Depot queue id. Has to be a UUID string',
                required=True,
                type=str,
            ),
           'queue-status': dict(
                help='Checks esbuild queue status',
                action='store_true',
                default=False,
            ),
            'queue-clear': dict(
                help='Clears esbuild queue',
                action='store_true',
                default=False,
            ),
        }
