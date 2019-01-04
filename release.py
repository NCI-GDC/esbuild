import json
import pprint
import argparse

from wrapper_utils import (
    ElasticsearchUtil,
    get_manifest_bucket,
)


def argparser():
    parser = argparse.ArgumentParser("Release helper utility")
    subparsers = parser.add_subparsers(help="Operation modes")

    list_parser = subparsers.add_parser("list", help="List all release manifests")
    list_parser.set_defaults(action='list')

    read_parser = subparsers.add_parser("read", help="Read release manifest")
    read_parser.set_defaults(action='read')
    read_parser.add_argument("--manifest-name", required=True)

    alias_parser = subparsers.add_parser("alias", help="Alias indices corresponding to release manifests")
    alias_parser.set_defaults(action='alias')
    alias_parser.add_argument("--manifest-name", required=True)

    s3_parser = subparsers.add_parser("bucket_manage", help="Manually manage manifest bucket")
    s3_parser.set_defaults(action='bucket_manage')

    return parser


class ReleaseManifestUtil(object):
    """
    Helps with Release Manifest management:
        - Lists all release manifests
        - Reads contents of particular manifest
        - Fetches indices to alias corresonding to the manifest
    """

    def __init__(self, quiet=False):
        self.bucket = get_manifest_bucket()

    def list(self):
        """
        Returns list of existing release manifests
        """
        keys = [_ for _ in self.bucket.list()]
        return keys

    def read(self, manifest_name):
        """
        Returns JSON contents of particular manifest
        """
        key = self.bucket.get_key(manifest_name)
        return json.loads(key.get_contents_as_string())

    def alias(self, manifest_name):
        """
        Returns list of indices to alias corresponding to release manifest
        NOTE:
            Order of manifest entries matters - if one project was built twice,
            will only keep the latest one
        """
        manifest = self.read(manifest_name)
        indices = {}  # {project_id: index_name}
        for entry in manifest:
            args = entry['arguments']
            index_name = args['index_name']
            projects = args['build_projects']
            for pid in projects:
                indices[pid] = index_name

        return indices


def manage_release(args):
    """
    Uses util classes to explore release manifests and alias corresponding indices
    """
    action = args.action

    r = ReleaseManifestUtil()
    e = ElasticsearchUtil()

    if action == 'list':
        manifests = ['\n\t- ' + k.name for k in r.list()]
        print "Release Manifests:{}".format(''.join(manifests))
        if len(manifests) == 0:
            print '\tNothing found'
    elif action == 'read':
        manifest = r.read(args.manifest_name)
        print "Manifest {}:\n{}".format(
            args.manifest_name, pprint.pformat(manifest)
        )
    elif action == 'alias':
        indices = r.alias(args.manifest_name)
        print "Indices to alias from {}:\n{}".format(
            args.manifest_name, pprint.pformat(indices)
        )
        for pid, index in indices.items():
            try:
                e.alias(index, alias_name='gdc_from_graph')
                print '{} aliased'.format(index)
            except Exception as err:
                print '{} failed to alias: {}'.format(index, err)
    elif action == 'bucket_manage':
        print "Manipulate manifest bucket:"
        bucket = r.bucket
        import pdb; pdb.set_trace()


if __name__ == "__main__":
    args = argparser().parse_args()
    manage_release(args)
