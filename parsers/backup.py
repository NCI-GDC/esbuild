from base import BaseParser


class BackupArgs(BaseParser):
    """
    Backup arguments
    """

    @property
    def group(self):
        return dict(
            title='Backup arguments',
            description='ES index backup using repository-s3',
        )

    @property
    def arguments(self):
        return {
            'restore-from-snapshot': dict(help='Name of a snapshot to restore index from'),
            'store-to-snapshot': dict(help='Name of a snapshot to store index to'),
        }
