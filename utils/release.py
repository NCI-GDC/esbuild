import json
from manifest import get_manifest_bucket


class ReleaseManifestUtil(object):
    """
    Helps with Release Manifest management:
        - Lists all release manifests
        - Reads contents of particular manifest
        - Fetches indices to alias corresonding to the manifest
    """

    def __init__(self, quiet=False):
        self.bucket = get_manifest_bucket()

    def list_manifests(self):
        """
        Returns list of existing release manifests
        """
        keys = [_ for _ in self.bucket.list()]
        return keys

    def read_manifest(self, manifest_name, simple_view=False):
        """
        Returns JSON contents of particular manifest
        """
        key = self.bucket.get_key(manifest_name)
        manifest = json.loads(key.get_contents_as_string())
        if simple_view:
            manifest = [
                {
                 'index_name': r['arguments']['index_name'],
                 'projects': r['arguments']['build_projects'],
                 'duration': r['duration'],
                 }
                for r in manifest
            ]
        return manifest

    def get_indices(self, manifest_name):
        """
        Returns dictionary {project_id: index_name} containing indices to alias
        corresponding to release manifest
        NOTE:
            Order of manifest entries matters - if one project was built twice,
            will only keep the latest one
        """
        manifest = self.read_manifest(manifest_name)
        indices = {}  # {project_id: index_name}
        for entry in manifest:
            args = entry['arguments']
            index_name = args['index_name']
            projects = args['build_projects']
            for pid in projects:
                indices[pid] = index_name

        return indices
