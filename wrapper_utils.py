import os
import json
import argparse
import requests

from elasticsearch import Elasticsearch
from psqlgraph import PsqlGraphDriver
from gdcdatamodel import models as md
from esbuild.export.s3_upload import add_s3_args, connect_to_s3


class ElasticsearchUtil(object):

    def __init__(self, **es_args):
        self.es = Elasticsearch(
            host=es_args.get('es_host', os.getenv('ES_HOST')),
            port=es_args.get('es_port', os.getenv('ES_PORT')),
            http_auth=(
                es_args.get('es_user', os.getenv('ES_USER')),
                es_args.get('es_pass', os.getenv('ES_PASS')),
            ),
        )

    def alias(self, index, alias_name='gdc_from_graph'):
        self.es.indices.put_alias(index=index, name=alias_name)


def depot_call(action, args, json=None):
    """
    Calls depot api
    """

    url = 'http://{}:{}/v0/{}/{}'.format(
        args.depot_host, args.depot_port, action, args.queue_id
    )

    method = 'put'
    if action == 'status':
        method = 'get'

    return getattr(requests, method)(url, json=json)


def user_confirm(prompt_string, logger):
    """
    Prompt user confirmation to proceed
    """
    while True:
        logger.info(prompt_string)
        ans = raw_input().lower()
        if ans in ['y', 'yes']:
            return
        elif ans in ['n', 'no']:
            raise Exception('User refused to continue')
        else:
            logger.error('Invalid answer: {}'.format(ans))


def get_release_candidate_info():
    """
    Lookup release candidate name and version in postgres
    """
    postgres_driver = PsqlGraphDriver(
        os.environ["PG_HOST"],
        os.environ["PG_USER"],
        os.environ["PG_PASS"],
        os.environ["PG_NAME"],
    )

    with postgres_driver.session_scope():
        release_node = (postgres_driver.nodes(md.DataRelease)
                                       .props(released=False).first())

    release_name = release_node.name
    release_version = [release_node.major_version, release_node.minor_version]
    return release_name, release_version


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


def put_manifest(json_manifest, file_name):
    """
    Create or update release manifest json file on s3
    """
    # Get old manifest list from file in s3
    bucket = get_manifest_bucket()
    key = bucket.get_key(file_name)
    if key is None:
        key = bucket.new_key(file_name)
        manifest_list = []
    else:
        manifest_list = json.loads(key.get_contents_as_string())

    # Update manifest file with new entry
    manifest_list.append(json_manifest)
    key.set_contents_from_string(json.dumps(manifest_list))


def split_projects(project_list, n, split_by_program=False, split_by_project=False):
    """
    Splits project list into n parts
    """

    if n == 1:
        return [project_list]

    if split_by_project:
        return [[p] for p in project_list]

    # Check input
    if not isinstance(n, int) or n < 1:
        raise ValueError('Number of parts should be positive integer. Got: {}'.format(n))
    if n > len(project_list):
        raise ValueError('Can not split list to {} > len(list) parts'.format(n))

    def get_program(project_id):
        return project_id.split('-', 1)[0]

    # Split-by-program mode
    if split_by_program:
        programs = set([get_program(p) for p in project_list])
        project_groups = []
        for program in programs:
            project_groups.append([x for x in project_list if get_program(x) == program])
        return project_groups

    # Regular mode
    else:
        group_lengths = [1 for _ in range(n)]
        i = 0
        while sum(group_lengths) != len(project_list):
            group_lengths[i] += 1
            i += 1
            if i == len(group_lengths):
                i = 0

        project_groups = []
        i = 0
        for length in group_lengths:
            project_groups.append(project_list[i:i+length])
            i = i + length
        return project_groups
