import os
import json

from s3 import S3Util


class ReleaseManifestUtil(object):
    """
    Helps with Release Manifest management:
        - Lists all release manifests
        - Reads contents of particular manifest
        - Fetches indices to alias corresonding to the manifest
    """

    def __init__(self, quiet=False):
        self.s3 = S3Util()

    @property
    def bucket(self):
        """
        S3 bucket with release manifests
        """
        return self.s3.conn.get_bucket(os.environ['S3_MANIFEST_BUCKET'])

    @property
    def manifest_name(self):
        """
        Most recent manifest name
        """
        return self.get_latest_manifest()['name']

    @property
    def release_name(self):
        """
        Most recent release name
        """
        return self.manifest_name.replace('.json', '')

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

    def get_latest_manifest(self):
        """
        Return most recent manifest file contents
        """
        def get_json(key):
            return json.loads(key.get_contents_as_string())

        contents = list(self.bucket.list())
        latest_name = contents[0].name
        latest_content = get_json(contents[0])
        for key in contents:
            m = get_json(key)
            if m[0]['started'] > latest_content[0]['started']:
                latest_content = m
                latest_name = key.name
        return {'name': latest_name, 'json': latest_content}

    def get_initial_manifest(self):
        """
        Return initial json manifest for new release based on most recent old one

        NOTE: only supports one-index-per-project builds
        """
        manifest = self.get_latest_manifest(self.bucket)['json']

        # Filter only rows corresponding to final project builds
        rows = {}  # project_id: manifest_row
        for row in manifest:
            projects = row['arguments']['build_projects']
            if len(projects) != 1:
                raise ValueError('Many projects per index not supported')
            project = projects[0]
            rows[project] = row

        return rows.values()

    def put_manifest(self, json_manifest, file_name):
        """
        Create or update release manifest json file on s3

        If there is no manifest :file_name (new release case), will get most recent
        lines from most recent release manifest as starting point
        """
        # Get old manifest list from file in s3
        key = self.bucket.get_key(file_name)

        # If there is no corresponding manifest, initialize
        if key is None:
            # Create new key
            key = self.bucket.new_key(file_name)
            # If no old manifests, start with empty one
            if len(list(self.bucket.list())) == 0:
                manifest_list = []
            # Else use old most recent manifest to create a base for new one
            else:
                manifest_list = self.get_initial_manifest()
        # Else load existing manifest
        else:
            manifest_list = json.loads(key.get_contents_as_string())

        # Update manifest file with new entry
        manifest_list.append(json_manifest)
        key.set_contents_from_string(json.dumps(manifest_list))
