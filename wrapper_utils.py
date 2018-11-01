import os
import requests

from elasticsearch import Elasticsearch
from psqlgraph import PsqlGraphDriver
from gdcdatamodel import models as md

from esbuild.export.s3_repository import BackupHelper


def depot_call(action, host, port, queue_id, json=None):
    """
    Calls depot api
    """

    url = 'http://{}:{}/v0/{}/{}'.format(host, port, action, queue_id)

    method = 'put'
    if action == 'status':
        method = 'get'

    return getattr(requests, method)(url, json=json)


def log_args(args, parsers, logger):
    """
    Logs arguments and values provided by user
    """
    for parser in parsers:
        args_to_print = [
            arg for arg in args._get_kwargs() if arg[0] in parser.args
        ]
        logger.info("\t{}:".format(parser.__name__))
        for name, value in args_to_print:
            logger.info('{}={}'.format(name, value))


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

    release_name = 'marvin'  # FIXME: add "name" parameter to DataRelease PG node
    release_version = [release_node.major_version, release_node.minor_version]
    return release_name, release_version


class BackupWrapper:
    """
    Wrapper around BackupHelper
    Helps to store and restore snapshots reading creds from env variables
    """

    def __init__(self, logger, es_client=None):
        self.logger = logger
        self.es_client = Elasticsearch(
            hosts=[os.environ["ES_HOST"]],
            http_auth=(os.environ.get("ES_USER", ""),
                       os.environ.get("ES_PASSWORD", "")),
            timeout=9999,
        )
        self.backup_helper = BackupHelper(
            self.es_client,
            os.environ["S3_HOST"],
            os.environ["S3_ACCESS_KEY"],
            os.environ["S3_SECRET_KEY"],
            'esbuild-backup',
        )

    def backup(self, snapshot_name, index_name):
        self.logger.info("Saving {} to snapshot {}".format(index_name, snapshot_name))
        self.backup_helper.store_snapshot('esbuild-snapshots',
                                          snapshot_name, indices=[index_name],
                                          wait_for_completion=True)
        self.logger.info("Index {} saved".format(index_name))

    def restore(self, snapshot_name, index_name):
        if index_name in self.es_client.indices.get_alias():
            raise Exception('Index {} already exists.'.format(index_name))
        self.logger.info("Restoring {} from snapshot {}".format(index_name, snapshot_name))
        self.backup_helper.restore_from_snapshot(
            'esbuild-snapshots',
            snapshot_name, indices=[index_name],
            wait_for_completion=True,
        )
        self.logger.info("Index {} restored".format(index_name))


def split_projects(project_list, n, split_by_program=False):
    """
    Splits project list into n parts
    """

    if n == 1:
        return [project_list]

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
        if n != len(programs):
            raise Exception("Number of workers should equal number of programs ({})"
                            .format(len(programs)))
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
