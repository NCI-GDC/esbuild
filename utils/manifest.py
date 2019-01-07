import os
import argparse
import json
from esbuild.export.s3_upload import add_s3_args, connect_to_s3


def get_manifest_bucket():
    s3_args = [
        '--s3-host', os.environ["S3_HOST"],
        '--s3-secret-key', os.environ["S3_SECRET_KEY"],
        '--s3-access-key', os.environ["S3_ACCESS_KEY"],
        '--s3-bucket', os.environ["S3_MANIFEST_BUCKET"],
    ]
    s3_args = add_s3_args(argparse.ArgumentParser()).parse_args(s3_args)
    conn = connect_to_s3(s3_args)
    bucket = conn.get_bucket(s3_args.s3_bucket)
    return bucket


def get_latest_manifest(bucket):
    """
    Return most recent manifest file contents
    """
    def get_json(key):
        return json.loads(key.get_contents_as_string())

    contents = list(bucket.list())
    latest = get_json(contents[0])
    for key in contents:
        m = get_json(key)
        if m[0]['started'] > latest[0]['started']:
            latest = m
    return latest


def get_initial_manifest():
    """
    Return initial json manifest for new release based on most recent old one

    NOTE: only supports one-index-per-project builds
    """
    bucket = get_manifest_bucket()
    manifest = get_latest_manifest(bucket)

    # Filter only rows corresponding to final project builds
    rows = {}  # project_id: manifest_row
    for row in manifest:
        projects = row['arguments']['build_projects']
        if len(projects) != 1:
            raise ValueError('Many projects per index not supported')
        project = projects[0]
        rows[project] = row

    return rows.values()


def put_manifest(json_manifest, file_name):
    """
    Create or update release manifest json file on s3

    If there is no manifest :file_name (new release case), will get most recent
    lines from most recent release manifest as starting point
    """
    # Get old manifest list from file in s3
    bucket = get_manifest_bucket()
    key = bucket.get_key(file_name)

    # If there is no corresponding manifest, initialize
    if key is None:
        # Create new key
        key = bucket.new_key(file_name)
        # If no old manifests, start with empty one
        if len(list(bucket.list())) == 0:
            manifest_list = []
        # Else use old most recent manifest to create a base for new one
        else:
            manifest_list = get_initial_manifest()
    # Else load existing manifest
    else:
        manifest_list = json.loads(key.get_contents_as_string())

    # Update manifest file with new entry
    manifest_list.append(json_manifest)
    key.set_contents_from_string(json.dumps(manifest_list))