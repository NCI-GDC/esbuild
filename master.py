import os

import yaml
from cdislogging import get_logger
from elasticsearch import Elasticsearch
from queueclient.depot import DepotQueueClient

from bin.base_build import esbuild_argparser as base_parser
from esbuild.export.s3_repository import BackupHelper
from esbuild.utils import ES_CONFIG

logger = get_logger('esbuild_master')

root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, 'config.yml'), 'r').read())


def esbuild_argparser(parser=None):
    """
    Esbuild argument parser
    """
    if not parser:
        parser = base_parser()

    depot_args = parser.add_argument_group(title='Depot server arguments',
                                           description='Depot server address '
                                           'and queue_id to listen to')
    depot_args.add_argument('--depot-host',
                            default='depot.service.consul',
                            help='Depot server host')
    depot_args.add_argument('--depot-port',
                            type=int,
                            default=80,
                            help='Depot server port')
    depot_args.add_argument('--queue-id', type=str,
                            help='Depot queue id. Has to be a UUID string')
    depot_args.add_argument('--queue-clear',
                            help='Clears esbuild queue',
                            action='store_true',
                            default=False)

    es_args = parser.add_argument_group(title='Esbuild arguments',
                                        description='Esbuild related settings')
    es_args.add_argument('--num-jobs',
                         help='How many jobs to create',
                         type=int)
    es_args.add_argument('--build-type',
                         choices=['active', 'legacy'],
                         help='Choose "active" or "legacy"')
    es_args.add_argument('--split-by-program',
                         action='store_true',
                         help='If set, splits all projects into groups by program',
                         default=False)
    es_args.add_argument('--skip-projects',
                         nargs='*',
                         help='Set of projects to skip')

    backup_args = parser.add_argument_group(title='Backup arguments',
                                            description='ES index backup using repository-s3')
    backup_args.add_argument('--restore-from-snapshot',
                             help='Name of a snapshot to restore index from')
    backup_args.add_argument('--store-to-snapshot',
                             help='Name of a snapshot to store index to')
    return parser


def parse_args():
    """ Parses arguments, checks for sanity """

    args = esbuild_argparser(base_parser()).parse_args()
    if not any([args.queue_clear, args.store_to_snapshot,
                args.restore_from_snapshot]):
        if (any([args.index, args.num_jobs, args.build_type]) and
                not all([args.index, args.num_jobs, args.build_type])):
            raise Exception('Provide esbuild arguments to delegate jobs.\n'
                            'Run `python master.py -h` for more info')

    return args


def split_projects(project_list, n, split_by_program=False):
    """Splits list of projects into n parts"""

    if n == 1:
        return [project_list]

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
    es_client = Elasticsearch(timeout=9999, **ES_CONFIG)

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
        if args.queue_id:
            depot = DepotQueueClient(
                args.queue_id,
                host=args.depot_host,
                port=args.depot_port,
            )
            if args.queue_clear:
                logger.info(depot.clear())
            else:
                if not args.num_jobs:
                    raise Exception('--num-jobs not provided')
                if not args.index:
                    raise Exception('--index not provided')
                if not args.build_type:
                    raise Exception('--build-type not provided')

                if args.projects is None:
                    projects = config['{}_projects'.format(args.build_type)]
                else:
                    projects = args.projects

                # Skip some projects, if skip-projects argument is set
                if args.skip_projects:
                    projects = [p for p in projects if p not in args.skip_projects]

                logger.info("\n\n\tDelegating {} build with {} jobs\n\tES index: {}"
                            .format(args.build_type.upper(), args.num_jobs, args.index))

                # Delegate a job for each project group:
                for group in split_projects(projects, args.num_jobs,
                                            split_by_program=args.split_by_program):
                    job_json = {
                        'index': args.index,
                        'replicas': args.replicas,
                        'shards': args.shards,
                        'no-roll': args.no_roll,
                        'no-cleanup': args.no_cleanup,
                        'skip-es': args.skip_es,
                        'projects': ' '.join(group),
                        'selective-caching': args.selective_caching,
                        'build-awg': args.build_awg,
                        'build-type': args.build_type,
                        'cache-versioned': args.cache_versioned,
                    }
                    logger.info('Adding work: {}'.format(job_json))
                    depot.enqueue(msg=job_json)
