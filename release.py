import pprint
import argparse
import logging
from elasticsearch import TransportError
from utils.es import ElasticsearchUtil
from utils.backup import BackupUtil
from utils.release import ReleaseManifestUtil

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def argparser():
    parser = argparse.ArgumentParser("Release helper utility")
    subparsers = parser.add_subparsers(help="Operation modes")

    list_parser = subparsers.add_parser("list", help="List all release manifests")
    list_parser.set_defaults(action='list')

    read_parser = subparsers.add_parser("read", help="Read release manifest")
    read_parser.set_defaults(action='read')
    read_parser.add_argument("--manifest-name", required=True)
    read_parser.add_argument("--simple-view", action='store_true')

    alias_parser = subparsers.add_parser("alias", help="Alias indices corresponding to release manifests")
    alias_parser.set_defaults(action='alias')
    alias_parser.add_argument("--manifest-name", required=True)
    alias_parser.add_argument("--alias-name", default='gdc_from_graph')

    backup_parser = subparsers.add_parser("backup", help="Backup/restore indices")
    backup_parser.set_defaults(action='backup')
    backup_parser.add_argument(
        '--mode', help="Save/restore/list release indices in s3-repository snapshot.\n"
        "NOTE: When 'save', will automatically generate snapshot name based on latest release manifest",
        choices=['save', 'restore', 'list'], required=True,
    )
    backup_parser.add_argument('--snapshot-name', help="Snapshot name to restore_from/see_more_details_about")
    s3_parser = subparsers.add_parser("bucket_manage", help="Manually manage manifest bucket")
    s3_parser.set_defaults(action='bucket_manage')

    return parser


class BaseActionHandler(object):
    """
    Handles actions based on parsed :args
    """

    def __init__(self, args):
        self.args = args

    def handle(self):
        """
        Execute handler corresponding to :args.action
        """
        handler = getattr(self, '_{}'.format(self.args.action))
        handler()


class ReleaseActionHandler(BaseActionHandler):

    def __init__(self, args):
        super(ReleaseActionHandler, self).__init__(*args)
        self.manifest = ReleaseManifestUtil()
        self.es = ElasticsearchUtil()

    def _list(self):
        manifests = ['\n\t- ' + k.name for k in self.manifest.list_manifests()]
        log.info("Release Manifests:{}".format(''.join(manifests)))
        if len(manifests) == 0:
            log.warning('Nothing found')

    def _read(self):
        manifest = self.manifest.read_manifest(self.args.manifest_name,
                                               simple_view=self.args.simple_view)
        log.info("Manifest {}:\n{}".format(self.args.manifest_name,
                                           pprint.pformat(manifest)))

    def _alias(self):
        indices = self.manifest.get_indices(self.args.manifest_name)
        log.info(
            "Indices to alias from {}:\n{}".format(self.args.manifest_name,
                                                   pprint.pformat(indices))
        )
        self.es.delete_alias('_all', alias_name=self.args.alias_name)
        log.info("Removed old aliases to {}".format(self.args.alias_name))
        for pid, index in indices.items():
            try:
                self.es.alias(index, alias_name=self.args.alias_name)
                log.info('{} aliased'.format(index))
            except TransportError as err:
                log.warning('{} failed to alias: {}'.format(index, err))

    def _backup(self):
        args = self.args
        args.action = args.mode  # assign subparser's action to args.mode
        BackupActionHandler(args).handle()

    def _bucket_manage(self):
        log.info("Manually manipulate manifest bucket:")
        bucket = self.manifest.manifest_bucket
        import pdb; pdb.set_trace()


class BackupActionHandler(BaseActionHandler):

    def __init__(self, args):
        super(BackupActionHandler, self).__init__(*args)
        self.backup = BackupUtil()
        self.manifest = ReleaseManifestUtil()
        self.snapshot_pattern = 'release-{release_name}-active'

    def _save(self):
        """
        Saves indices corresponding to latest manifest to repository
        """
        snapshot_name = self.snapshot_pattern.format(release_name=self.manifest.release_name)
        indices = self.manifest.get_indices(self.manifest.manifest_name).values()
        self.backup.backup(snapshot_name, indices)

    def _restore(self):
        """
        Restores all indices from snapshot --snapshot-name

        If --snapshot-name is not provided, restores most recent one
        """
        # Get snapshot name
        snapshot = args.snapshot_name
        if snapshot is None:
            snapshot = self.snapshot_pattern.format(release_name=self.manifest.release_name)

        # Restore all indices from the snapshot
        self.backup.restore(snapshot, '_all')

    def _list(self):
        """
        List all snapshots corresponding to release manifests
        """
        # Get list results
        res = self.backup.list(args.snapshot_name)

        # Prettify and display
        if args.snapshot_name is None:
            prettystr = ''.join(
                ['\n\t- ' + r for r in res if r.startswith('release-')]
            )
            log.info('\nRelease snapshots found:\n{}'.format(prettystr))
        else:
            prettystr = pprint.pformat(res)
            log.info('\nSnapshot {} details:\n{}'
                     .format(args.snapshot_name, prettystr))


if __name__ == "__main__":
    args = argparser().parse_args()
    r = ReleaseActionHandler(args)
    r.handle()
