import requests
import yaml
import argparse
import os

from elasticsearch import Elasticsearch

from esbuild.export.s3_repository import BackupHelper
from cdisutils.log import get_logger
logger = get_logger('esbuild_master')

root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, 'config.yml'), 'r').read())


def parse_args():
    """Parses arguments"""

    parser = argparse.ArgumentParser(description='Delegate Esbuild jobs '
                                     'to workers using depot server')

    depot_args = parser.add_argument_group(title='Depot server arguments',
                                           description='Depot server address '
                                           'and queue_id to listen to')
    depot_args.add_argument('--host',
                            help='Depot server host')
    depot_args.add_argument('--port',
                            type=int,
                            help='Depot server port')
    depot_args.add_argument('--queue-id', type=str,
                            help='Depot queue id. Has to be a UUID string')
    depot_args.add_argument('--queue-status',
                            help='Checks esbuild queue status',
                            action='store_true',
                            default=False)
    depot_args.add_argument('--queue-clear',
                            help='Clears esbuild queue', action='store_true',
                            default=False)

    es_args = parser.add_argument_group(title='Esbuild arguments',
                                        description='Esbuild related settings')
    es_args.add_argument('--index',
                         help='Name of elasticsearch index to upsert data into')
    es_args.add_argument('--n-workers',
                         help='Number of workers to split esbuild between',
                         type=int)
    es_args.add_argument('--build-type', choices=['active', 'legacy'],
                         help='Choose "active" or "legacy"')
    es_args.add_argument('--split-by-program', action='store_true',
                         help='If set, splits all projects into groups by program',
                         default=False)
    es_args.add_argument('--projects', default='ALL', nargs='*',
                         help='Set of projects to add to existing index.')
    es_args.add_argument('--skip-projects', nargs='*',
                         help='Set of projects to skip')
    es_args.add_argument('--selective-caching', action='store_true',
                         help='If set, only caches nodes for projects needed. '
                         'WARNING: Will skip nodes that do not have project_id',
                         default=False)

    backup_args = parser.add_argument_group(title='Backup arguments',
                                            description='ES index backup using repository-s3')
    backup_args.add_argument('--restore-from-snapshot',
                             help='Name of a snapshot to restore index from')
    backup_args.add_argument('--store-to-snapshot',
                             help='Name of a snapshot to store index to')

    args = parser.parse_args()
    if not any([args.queue_status, args.queue_clear, args.store_to_snapshot,
                args.restore_from_snapshot]):
        if (any([args.index, args.n_workers, args.build_type]) and 
            not all([args.index, args.n_workers, args.build_type])):
            raise Exception('Provide esbuild arguments to delegate jobs.\n'
                            'Run `python master.py -h` for more info')

    return args


def depot_call(action, host, port, queue_id, json=None):
    """Calls depot api"""

    url = 'http://{}:{}/v0/{}/{}'.format(host, port, action, queue_id)

    method = 'put'
    if action == 'status':
        method = 'get'

    return getattr(requests, method)(url, json=json)


def split_projects(project_list, n, split_by_program=False):
    """Splits list of projects into n parts"""

    # Check input
    if not isinstance(n, int) or n < 1:
        raise ValueError('Number of parts should be positive integer. Got: {}'.format(n))
    if n > len(project_list):
        raise ValueError('Can not split list to {} > len(list) parts'.format(n))

    # Split-by-program mode
    if split_by_program:
        programs = set([p.split('-', 1)[0] for p in project_list])
        if n != len(programs):
            raise Exception("Number of workers should equal number of programs ({})"
                            .format(len(programs)))
        result = []
        for program in programs:
            result.append([x for x in project_list if x.split('-', 1)[0] == program])
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


def backup_wrapper(snapshot_name, index_name, mode):
    """
    Executes backup or restore procedure with BackupHelper
    """
    es_client = Elasticsearch(
        hosts=[os.environ["ES_HOST"]],
        http_auth=(os.environ.get("ES_USER", ""),
                   os.environ.get("ES_PASSWORD", "")),
        timeout=9999,
    )
    backup_helper = BackupHelper(
        es_client,
        os.environ["S3_HOST"],
        os.environ["S3_ACCESS_KEY"],
        os.environ["S3_SECRET_KEY"],
        'esbuild-backup',
    )

    if mode == 'backup':
        logger.info("Saving {} to snapshot {}".format(index_name, snapshot_name))
        backup_helper.store_snapshot('esbuild-snapshots',
                                     snapshot_name, indices=[index_name],
                                     wait_for_completion=True)
        logger.info("Index {} saved".format(index_name))
    elif mode == 'restore':
        if index_name in es_client.indices.get_alias():
            raise Exception('Index {} already exists.'.format(index_name))
        logger.info("Restoring {} from snapshot {}".format(index_name, snapshot_name))
        backup_helper.restore_from_snapshot('esbuild-snapshots',
                                            snapshot_name, indices=[index_name],
                                            wait_for_completion=True)
        logger.info("Index {} restored".format(index_name))
    else:
        raise Exception('Unknown mode: {}'.format(mode))


if __name__ == "__main__":
    args = parse_args()

    if args.store_to_snapshot:
        # Backup args.index to S3 snapshot repository
        backup_wrapper(args.store_to_snapshot, args.index, 'backup')
    else:
        # Restore index from S3 snapshot repository
        if args.restore_from_snapshot:
            backup_wrapper(args.restore_from_snapshot, args.index, 'restore')
        # Delegate esbuild jobs to depot queue
        if args.host and args.port and args.queue_id:
            # Get queue status:
            status = depot_call('status', args.host, args.port, args.queue_id)
            if args.queue_clear:
                logger.info(depot_call('clear', args.host, args.port, args.queue_id).text)
            elif args.queue_status:
                logger.info(status.text)
            else:
                if not args.n_workers:
                    raise Exception('--n-workers not provided')
                if not args.index:
                    raise Exception('--index not provided')
                if not args.build_type:
                    raise Exception('--build-type not provided')

                if args.projects == 'ALL':
                    projects = config['{}_projects'.format(args.build_type)]
                else:
                    projects = args.projects

                # Skip some projects, if skip-projects argument is set
                if args.skip_projects:
                    projects = [p for p in projects if p not in args.skip_projects]

                logger.info("\n\n\tDelegating {} build with {} workers\n\tES index: {}"
                       .format(args.build_type.upper(), args.n_workers, args.index))

                if 'not found' in status.text:
                    logger.info("Creating new queue:")
                    logger.info(depot_call('new', args.host, args.port, args.queue_id).text)

                # Delegate a job for each project group:
                for group in split_projects(projects, args.n_workers,
                                            split_by_program=args.split_by_program):
                    arguments = ['--upsert-to {}'.format(args.index), '--no-roll']
                    if args.n_workers > 1:
                        arguments.append('--projects {}'.format(' '.join(group)))

                    if args.selective_caching:
                        arguments.append('--selective-caching')

                    job_json = {'arguments': arguments, 'build_type': args.build_type}
                    depot_call('delegate', args.host, args.port, args.queue_id,
                               json=job_json)
