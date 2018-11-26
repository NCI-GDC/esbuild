import yaml
import os
from datadog import statsd

from parsers import (
    Parser,
    DepotArgs,
    MasterArgs,
    EsbuildUserArgs,
    BackupArgs,
)
from wrapper_utils import (
    depot_call,
    user_confirm,
    split_projects,
    get_release_candidate_info,
)
from esbuild.export.s3_repository import BackupWrapper
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
    return Parser.build(
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
        - :label and :release_version_number will be overwritten by values on release node in postgres
        - name prefix 'release-' is added
    """
    prefix = ''
    label = args.label.replace('-', '_')
    version = args.version
    index_type = args.index_type

    # If release build, overwrite label and version to ones on DataRelease node
    # and add release- prefix
    if args.build_type == 'release':
        prefix = 'release'
        label, version = get_release_candidate_info()

    version = '_'.join(map(str, version))

    index_name = "-".join([label, version, index_type])
    if prefix:
        index_name = '-'.join([prefix, index_name])

    return index_name.lower()


def delegate_jobs(args):
    """
    Submit jobs to depot queue based on arguments provided
    """
    status = depot_call('status', args)
    if 'not found' in status.text:
        logger.info("Creating new queue:")
        response = depot_call('new', args)
        logger.info(response.text)

    index_name = get_index_name(args)
    project_groups = get_project_groups(args)
    logger.info("\n\n\tDelegating {} jobs to build {}:"
                .format(args.n_workers, index_name))
    user_confirm('Building {}, are you sure? (y/n):'.format(index_name), logger)
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
        depot_call('delegate', args, json=job_json)
        statsd.event(
            "Job delegated",
            "queue: {}\n job: {}".format(args.queue_id, job_json),
            source_type_name="esbuild-master",
            alert_type="info",
            tags=["es_index:{}".format(index_name), 'master'],
        )


if __name__ == "__main__":
    args = master_argparser().parse_args()
    Parser.log_args(args, ALL_PARSERS, logger)

    if args.restore_from_snapshot:
        # Restore index from S3 snapshot repository
        BackupWrapper(logger).restore(args.restore_from_snapshot, args.index_name)

    if args.queue_status:
        status = depot_call('status', args)
        logger.info(status.text)
    elif args.queue_clear:
        logger.info(depot_call('clear', args).text)
    else:
        # Delegate esbuild jobs to depot queue
        delegate_jobs(args)
