from base import BaseParser


class BackupArgs(BaseParser):
    """
    Backup arguments
    """
    group = dict(
        title='Backup arguments',
        description='ES index backup using repository-s3',
    )

    arguments = {
        'restore-from-snapshot': dict(help='Name of a snapshot to restore index from'),
        'store-to-snapshot': dict(help='Name of a snapshot to store index to'),
    }
