import requests
import yaml
import os

from elasticsearch import Elasticsearch
from psqlgraph import PsqlGraphDriver
from gdcdatamodel import models as md

from parsers import (
    Parser,
    DepotArgs,
    EsbuildMasterArgs,
    EsbuildArgs,
    BackupArgs,
)
from esbuild.export.s3_repository import BackupHelper
from cdisutils.log import get_logger
logger = get_logger('esbuild_master')

root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, 'config.yml'), 'r').read())


def master_argparser():
    return Parser.build_parser([
        DepotArgs,
        EsbuildMasterArgs,
        EsbuildArgs,
        BackupArgs,
    ], description='Esbuild master arguments parser')


def depot_call(action, host, port, queue_id, json=None):
    """Calls depot api"""

    url = 'http://{}:{}/v0/{}/{}'.format(host, port, action, queue_id)

    method = 'put'
    if action == 'status':
        method = 'get'

    return getattr(requests, method)(url, json=json)


def split_projects(project_list, n, split_by_program=False):
    """
    Splits list into n parts
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
        result = []
        for program in programs:
            result.append([x for x in project_list if get_program(x) == program])
        return result

    # Regular mode
    else:
        group_lengths = [1 for _ in range(n)]
        i = 0
        while sum(group_lengths) != len(project_list):
            group_lengths[i] += 1
            i += 1
            if i == len(group_lengths):
                i = 0

        result = []
        i = 0
        for length in group_lengths:
            result.append(project_list[i:i+length])
            i = i + length
        return result


class BackupWrapper:
    """
    Wrapper around BackupHelper
    Helps to store and restore snapshots reading creds from env variables
    """

    def __init__(self, es_client=None):
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
        logger.info("Saving {} to snapshot {}".format(index_name, snapshot_name))
        self.backup_helper.store_snapshot('esbuild-snapshots',
                                          snapshot_name, indices=[index_name],
                                          wait_for_completion=True)
        logger.info("Index {} saved".format(index_name))

    def restore(self, snapshot_name, index_name):
        if index_name in self.es_client.indices.get_alias():
            raise Exception('Index {} already exists.'.format(index_name))
        logger.info("Restoring {} from snapshot {}".format(index_name, snapshot_name))
        self.backup_helper.restore_from_snapshot(
            'esbuild-snapshots',
            snapshot_name, indices=[index_name],
            wait_for_completion=True
        )
        logger.info("Index {} restored".format(index_name))


def get_projects(args):
    """
    Return list of projects to build based on arguments passed
    """
    if args.projects is None:
        projects = config['{}_projects'.format(args.index_type)]
    else:
        projects = args.projects

    # Skip some projects, if skip-projects argument is set
    if args.skip_projects:
        projects = [p for p in projects if p not in args.skip_projects]

    return projects


def get_index_name(args):
    """
    Return output index name based on arguments provided
    Naming pattern depending on build_type == 'release' or 'test':
    {release/NONE}-{label}-{version}-{index_type}

    If build_type == 'release':
        - :label and :release_version_number must match release node in postgres
        - name prefix 'release-' is added
    """
    index_name = "{label}-{version}-{index_type}".format(
        label=args.label.replace('-', '_'),
        version='_'.join(map(str, args.version)),
        index_type=args.index_type,
    )
    if args.build_type == 'release':
        index_name = 'release-' + index_name
        release, version = get_release_candidate_info()
        if args.label != release:
            raise Exception(
                '--label should match release node: {}'.format(release)
            )
        if args.version != version:
            raise Exception(
                '--version should match release node: {}'.format(version)
            )

    return index_name.lower()


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

    release_name = 'marvin'  # FIXME: DataRelease node should have "name" parameter
    release_version = [release_node.major_version, release_node.minor_version]
    return release_name, release_version


def delegate_jobs(args):
    """
    Submit jobs to depot queue based on arguments provided
    """
    index_name = get_index_name(args)
    logger.info("\n\n\tBuilding index {}".format(index_name))
    args_to_print = [
        arg for arg in args._get_kwargs() if arg[0] in EsbuildMasterArgs.args
    ]
    logger.info("Delegating esbuild jobs according to args:")
    for name, value in args_to_print:
        logger.info('{}={}'.format(name, value))

    status = depot_call('status', args.host, args.port, args.queue_id)
    if 'not found' in status.text:
        logger.info("Creating new queue:")
        response = depot_call('new', args.host, args.port, args.queue_id)
        logger.info(response.text)

    projects = get_projects(args)
    project_groups = split_projects(projects, args.n_workers,
                                    split_by_program=args.split_by_program)
    # Delegate a job for each project group:
    for group in project_groups:
        esbuild_args = [
            '--projects', '{}'.format(' '.join(group)),
            '--index-name', index_name
        ]
        if args.selective_caching:
            esbuild_args.append('--selective-caching')

        job_json = {
            'esbuild_args': esbuild_args,
            'index_type': args.index_type,
        }
        depot_call('delegate', args.host, args.port, args.queue_id,
                   json=job_json)


if __name__ == "__main__":
    args = master_argparser().parse_args()
    if args.restore_from_snapshot:
        # Restore index from S3 snapshot repository
        BackupWrapper().restore(args.restore_from_snapshot, args.index_name)

    if args.queue_status:
        status = depot_call('status', args.host, args.port, args.queue_id)
        logger.info(status.text)
    elif args.queue_clear:
        logger.info(depot_call('clear', args.host, args.port, args.queue_id).text)
    else:
        # Delegate esbuild jobs to depot queue
        delegate_jobs(args)
