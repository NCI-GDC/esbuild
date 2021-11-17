import argparse
import os
from typing import Any, Iterable, Optional

import yaml
from cdislogging import get_logger
from elasticsearch import Elasticsearch

from esbuild.export.s3_repository import BackupHelper
from esbuild.utils import ES_CONFIG, get_queue_client

logger = get_logger("esbuild_master", log_level="info")

root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, "config.yml"), "r").read())


def esbuild_argparser():
    """
    Returns argument parser for esbuild
    """
    parser = argparse.ArgumentParser(
        description="Parameters to control esbuild runs",
    )
    parser.add_argument(
        "--no-roll",
        action="store_true",
        help="If passed, do not roll the alias and delete old indices",
    )
    parser.add_argument(
        "--no-cleanup", action="store_true", help="If passed, do not delete old indices"
    )

    parser.add_argument(
        "--index",
        help="Index name to upsert projects to. Must set when building subset of projects",
    )
    parser.add_argument(
        "--alias",
        help="Index alias to use for index swap",
    )
    parser.add_argument(
        "--replicas",
        help="Number of replicas to set when creating an index (default: 0)",
        type=int,
        default=0,
    )
    parser.add_argument(
        "--shards",
        help="Number of shards to set when creating an index (default: 1)",
        type=int,
        default=1,
    )
    parser.add_argument(
        "--selective-caching",
        action="store_true",
        help="If set, only caches nodes for projects needed. "
        "WARNING: Will skip nodes that do not have project_id",
        default=False,
    )
    parser.add_argument(
        "--build-awg",
        action="store_true",
        help="If set, will build in AWG mode. "
        "Will pick up only projects flagged as awg_review = true and "
        "nodes that are part of these projects and are in any of allowed states",
        default=False,
    )
    parser.add_argument(
        "--cache-versioned",
        action="store_true",
        help="Collect differences for versioned unreleased files",
    )
    parser.add_argument(
        "--config",
        help="A path to a yaml configruation file for overriding default configurations.",
        type=str,
    )
    parser.add_argument(
        "--gencode-version",
        help="set desired gencode_version for indexing, 'neutral' nodes are always included."
        "if not set, all available nodes will be included. ",
        type=str,
        default="all",
        choices=["v22", "v36", "all"]
    )

    projects = parser.add_mutually_exclusive_group()
    projects.add_argument(
        "--project-group",
        help="The name for the specific group of projects from the configuration "
        "file to be built. Defaults to the complete 'active' or 'legacy' list of "
        "projects based on the build-type argument. Cannot be used with the "
        "projects argument.",
        type=str,
    )
    projects.add_argument(
        "--projects",
        nargs="*",
        help="If set, builds only set of projects specified (space-separated). Cannot "
        "be used with the project-group argument.",
    )

    es_args = parser.add_argument_group(
        title="Esbuild arguments", description="Esbuild related settings"
    )
    es_args.add_argument(
        "--queue-type",
        choices=["depot", "rabbitmq"],
        default="rabbitmq",
        help="Type of queue backend to use for scheduling" "(defaults to 'rabbitmq'",
    )
    es_args.add_argument(
        "--queue-clear", help="Clear current job queue", action="store_true"
    )
    es_args.add_argument(
        "--num-jobs",
        help="How many jobs to create (defaults to 1)",
        type=int,
        default=1,
    )
    es_args.add_argument(
        "--build-type",
        choices=["active", "legacy"],
        default="active",
        help='Choose "active" or "legacy" (defaults to "active")',
    )
    es_args.add_argument(
        "--split-by-program",
        action="store_true",
        help="If set, splits all projects into groups by program",
    )
    es_args.add_argument("--skip-projects", nargs="*", help="Set of projects to skip")

    backup_args = parser.add_mutually_exclusive_group()
    backup_args.add_argument(
        "--bucket", help="S3 bucket with ESBuild backups/snapshots"
    )
    backup_args.add_argument(
        "--restore-from-snapshot", help="Name of a snapshot to restore index from"
    )
    backup_args.add_argument(
        "--store-to-snapshot", help="Name of a snapshot to store index to"
    )
    return parser


def parse_args():
    """Parses arguments, checks for sanity"""

    args = esbuild_argparser().parse_args()
    return args


def split_projects(project_list, n, split_by_program=False):
    """Splits list of projects into n parts"""

    if n == 1:
        return [project_list]

    # Check input
    if not isinstance(n, int) or n < 1:
        raise ValueError(
            "Number of parts should be positive integer. Got: {}".format(n)
        )

    if n > len(project_list):
        raise ValueError("Can not split list to {} > len(list) parts".format(n))

    # Split-by-program mode
    if split_by_program:
        programs = set([p.split("-", 1)[0] for p in project_list])
        if n != len(programs):
            raise Exception(
                "Number of workers should equal number of programs ({})".format(
                    len(programs)
                )
            )
        result = []
        for program in programs:
            result.append([x for x in project_list if x.split("-", 1)[0] == program])
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
            result.append(project_list[i : i + length])
            i = i + length
        return result


def backup_wrapper(snapshot_name, index_name, mode, s3_bucket=None):
    """
    Executes backup or restore procedure with BackupHelper
    """
    es_client = Elasticsearch(**ES_CONFIG)

    bucket = s3_bucket or os.getenv("S3_BUCKET")

    if not bucket:
        raise ValueError("Snapshot bucket wasn't provided.")

    backup_helper = BackupHelper(
        es_client,
        os.environ["S3_HOST"],
        os.environ["S3_ACCESS_KEY"],
        os.environ["S3_SECRET_KEY"],
        bucket,
    )

    if mode == "backup":
        logger.info("Saving {} to snapshot {}".format(index_name, snapshot_name))
        backup_helper.store_snapshot(
            "esbuild-snapshots",
            snapshot_name,
            indices=[index_name],
            wait_for_completion=True,
        )
        logger.info("Index {} saved".format(index_name))
    elif mode == "restore":
        if index_name in es_client.indices.get_alias():
            raise Exception("Index {} already exists.".format(index_name))

        logger.info("Restoring {} from snapshot {}".format(index_name, snapshot_name))
        backup_helper.restore_from_snapshot(
            "esbuild-snapshots",
            snapshot_name,
            indices=[index_name],
            wait_for_completion=True,
        )
        logger.info("Index {} restored".format(index_name))
    else:
        raise Exception("Unknown mode: {}".format(mode))


def load_user_configuration(path: Optional[str]) -> dict:
    if not path:
        return {}

    if not os.path.exists(path):
        raise FileNotFoundError(
            "The provided configuration file does not exist: {}".format(path)
        )

    with open(path, "r") as f:
        return yaml.safe_load(f)


def get_default_projects(args: Any, user_config: dict) -> Iterable[str]:
    project_group = args.project_group or "{}_projects".format(args.build_type)
    projects = user_config.get(project_group) or config.get(project_group)

    if not projects:
        raise Exception(
            "No configuration was found for projects: {} in the configuration file: {}".format(
                project_group, args.config or "DEFAULT"
            )
        )

    return projects


if __name__ == "__main__":
    args = parse_args()

    if not args.index:
        logger.info("No 'index' was provided, no job will be scheduled")
        exit(1)

    # Backup args.index to S3 snapshot repository
    if args.store_to_snapshot:
        backup_wrapper(args.store_to_snapshot, args.index, "backup", args.bucket)
        exit(0)

    user_config = load_user_configuration(args.config)

    # Get RabbitMQ queue client
    queue_client = get_queue_client(args.queue_type)

    # Cleanup the queue
    if args.queue_clear:
        payload = queue_client.dequeue()

        while payload:
            payload = queue_client.dequeue()

    # Restore index from S3 snapshot repository
    if args.restore_from_snapshot:
        backup_wrapper(args.restore_from_snapshot, args.index, "restore", args.bucket)

    projects = args.projects
    if not projects:
        logger.info(
            "No 'projects' have been provided, defaulting to '{}' projects from config: {}".format(
                args.build_type, args.config or "DEFAULT"
            )
        )
        projects = get_default_projects(args, user_config)

    # Skip some projects, if skip-projects argument is set
    if args.skip_projects:
        logger.info("Skipping projects: {}".format(args.skip_projects))
        projects = [p for p in projects if p not in args.skip_projects]

    logger.info(
        "\n\n\tDelegating {} build with {} jobs\n\tES index: {}".format(
            args.build_type.upper(), args.num_jobs, args.index
        )
    )

    # Delegate a job for each project group:
    for group in split_projects(
        projects, args.num_jobs, split_by_program=args.split_by_program
    ):
        job_json = {
            "index": args.index,
            "alias": args.alias,
            "replicas": args.replicas,
            "shards": args.shards,
            "no-roll": args.no_roll,
            "no-cleanup": args.no_cleanup,
            "projects": " ".join(group),
            "selective-caching": args.selective_caching,
            "build-awg": args.build_awg,
            "build-type": args.build_type,
            "cache-versioned": args.cache_versioned,
            "gencode-version": args.gencode_version,
        }
        logger.info("Adding work: {}".format(job_json))
        queue_client.enqueue(msg=job_json)
