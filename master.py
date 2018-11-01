import yaml
import os

from parsers import (
    Parser,
    DepotArgs,
    MasterArgs,
    EsbuildUserArgs,
    BackupArgs,
)
from wrapper_utils import (
    log_args,
    depot_call,
    split_projects,
    get_release_candidate_info,
    BackupWrapper,
)
from cdisutils.log import get_logger
logger = get_logger('esbuild_master')

root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, 'config.yml'), 'r').read())

ALL_PARSERS = [
    MasterArgs,
    EsbuildUserArgs,
    DepotArgs,
    BackupArgs,
]


def master_argparser():
    return Parser.build_parser(
        ALL_PARSERS,
        description='Esbuild master arguments parser',
    )


def get_project_groups(args):
    """
    Return list of project groups - one for each worker to build
    """
    if args.projects is None:
        projects = config['{}_projects'.format(args.index_type)]
    else:
        projects = args.projects

    # Skip some projects, if skip-projects argument is set
    if args.skip_projects:
        projects = [p for p in projects if p not in args.skip_projects]

    project_groups = split_projects(projects, args.n_workers,
                                    split_by_program=args.split_by_program)

    return project_groups


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


def delegate_jobs(args):
    """
    Submit jobs to depot queue based on arguments provided
    """
    status = depot_call('status', args.host, args.port, args.queue_id)
    if 'not found' in status.text:
        logger.info("Creating new queue:")
        response = depot_call('new', args.host, args.port, args.queue_id)
        logger.info(response.text)

    index_name = get_index_name(args)
    project_groups = get_project_groups(args)

    logger.info("\n\n\tDelegating {} jobs to build {}:"
                .format(args.n_workers, index_name))
    for i, group in enumerate(project_groups):
        logger.info("Project group #{}:\n{}".format(i + 1, group))
        esbuild_args = [
            '--projects', '{}'.format(' '.join(group)),
            '--index-name', index_name,
        ]
        if args.index_type == 'awg':
            esbuild_args.append('--build-awg')
        if args.selective_caching:
            esbuild_args.append('--selective-caching')

        job_json = {
            'esbuild_args': esbuild_args,
            'index_type': args.index_type,
        }
        depot_call('delegate', args.host, args.port, args.queue_id,
                   json=job_json)


if __name__ == "__main__":
    parser = master_argparser()
    args = parser.parse_args()
    log_args(args, ALL_PARSERS, logger)

    if args.restore_from_snapshot:
        # Restore index from S3 snapshot repository
        BackupWrapper(logger).restore(args.restore_from_snapshot, args.index_name)

    if args.queue_status:
        status = depot_call('status', args.host, args.port, args.queue_id)
        logger.info(status.text)
    elif args.queue_clear:
        logger.info(depot_call('clear', args.host, args.port, args.queue_id).text)
    else:
        # Delegate esbuild jobs to depot queue
        delegate_jobs(args)
