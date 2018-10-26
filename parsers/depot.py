from base import BaseArgs


class DepotArgs(BaseArgs):
    args = {
        'host',
        'port',
        'queue_id',
        'queue_status',
        'queue_clear',
    }

    def add_args(self, parser):
        depot_args = parser.add_argument_group(
            title='Depot server arguments',
            description='Arguments related to Depot job queue service'
        )
        depot_args.add_argument(
            '--host', help='Depot server host',
            required=True,
        )
        depot_args.add_argument(
            '--port', type=int, help='Depot server port',
            required=True,
        )
        depot_args.add_argument(
            '--queue-id', type=str, help='Depot queue id. Has to be a UUID string',
            required=True,
        )
        depot_args.add_argument(
            '--queue-status', help='Checks esbuild queue status', action='store_true',
            default=False,
        )
        depot_args.add_argument(
            '--queue-clear', help='Clears esbuild queue', action='store_true',
            default=False,
        )
        return parser
