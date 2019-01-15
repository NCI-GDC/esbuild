import os
import config as conf
from datadog import statsd
from parsers import (
    ParserBuilder,
    EsbuildUserArgs,
    ESArgs,
)
from utils.misc import (
    depot_call,
    user_confirm,
    split_projects,
)
from utils.postgres import PostgresUtil
from cdisutils.log import get_logger
logger = get_logger('esbuild_master')

root_dir = os.path.dirname(os.path.abspath(__file__))


def master_argparser():
    return ParserBuilder.build(
        conf.MASTER_PARSERS,
        description='Esbuild master arguments parser',
    )


def get_project_groups(args):
    """
    Returns {index_name: project_group}
    where project_group = [project1, project2, ...] - list of projects for one
    worker to build
    """
    if args.build_projects is None:
        projects = getattr(conf, '{}_PROJECTS'.format(args.index_type.upper()))
    else:
        projects = args.build_projects

    # Skip some projects, if skip-projects argument is set
    if args.skip_projects:
        projects = [p for p in projects if p not in args.skip_projects]

    project_groups = split_projects(projects, args.n_jobs,
                                    split_by_project=args.split_by_project,
                                    split_by_program=args.split_by_program)

    result = []
    for projects in project_groups:
        args.build_projects = projects
        index_name = get_index_name(args, split_by_project=args.split_by_project)
        result.append({'index_name': index_name, 'projects': projects})
    return result


def get_index_name(args, split_by_project=False):
    """
    Return output index name based on arguments provided
    Naming pattern depending on build_type == 'release' or 'test':
    {release/NONE}-{label}-{version}-{index_type}

    If build_type == 'release':
        - :label will be prefixed with DataRelease.name read from postgres
        - :release_version_number will be overwritten by values on release node
          in postgres
        - name prefix 'release-' is added
    """
    label = args.build_label
    version = args.build_version
    index_type = args.index_type
    is_release = args.build_type == 'release'

    # If release build, overwrite label and version to ones on DataRelease node
    # and add release- prefix
    if is_release:
        pg = PostgresUtil()
        release_name, version = pg.get_release_candidate_info()
        label = 'release-{}'.format(release_name)

    # If split by project (len(projects) == 1), add project name to label
    if split_by_project:
        label = '{}-{}'.format(label, args.build_projects[0])

    # Version string
    version = '_'.join(map(str, version))

    index_name = "-".join([label, version, index_type])

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

    project_groups = get_project_groups(args)
    index_names = [g['index_name'] for g in project_groups]
    user_confirm('Will build indices:\n\t{}, are you sure? (y/n):'
                .format('\t'.join(index_names)), logger)

    for group in project_groups:
        index_name = group['index_name']
        projects = group['projects']
        logger.info("Project group [{}]:\n{}".format(index_name, projects))

        # Change projects set to a subset
        args.build_projects = projects

        # programmatically add all args and values to a command
        esbuild_args = ParserBuilder.get_cmd_list(
            args,
            [EsbuildUserArgs, ESArgs]
        )

        # Add private esbuild args manually
        esbuild_args.extend(['--index-name', index_name])
        if args.index_type == 'awg':
            esbuild_args.append('--awg-mode')

        # Validate args
        ParserBuilder.build(conf.ESBUILD_PARSERS).parse_args(esbuild_args)
        job_json = {
            'esbuild_args': esbuild_args,
            'build_type': args.build_type,
        }

        depot_call('delegate', args, json=job_json)
        statsd.event(
            "Job delegated",
            "queue: {}\n job: {}".format(args.queue_id, job_json),
            source_type_name="esbuild-master",
            alert_type="info",
            tags=["es_index:{}".format(index_name), 'master'],
        )


def main(args):
    # Check that n_jobs provided if not split by project or program
    if not args.n_jobs:
        if not args.split_by_project and not args.split_by_program:
            raise ValueError(
                "Provide correct --n-jobs. Found: {}".format(args.n_jobs)
            )

    # If build_projects not provided, add all
    if args.build_projects == []:
        args.build_projects = conf.ACTIVE_PROJECTS

    ParserBuilder.log_args(args, conf.MASTER_PARSERS, logger)
    delegate_jobs(args)


if __name__ == "__main__":
    args = master_argparser().parse_args()
    main(args)
