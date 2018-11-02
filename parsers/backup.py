from base import BaseArgs


class BackupArgs(BaseArgs):
    """
    Backup arguments
    """
    args = {
        'restore_from_snapshot',
        'store_to_snapshot',
    }

    def add_args(self, parser):
        backup_args = parser.add_argument_group(
            title='Backup arguments',
            description='ES index backup using repository-s3'
        )
        backup_args.add_argument('--restore-from-snapshot',
                                 help='Name of a snapshot to restore index from')
        backup_args.add_argument('--store-to-snapshot',
                                 help='Name of a snapshot to store index to')
        return parser
