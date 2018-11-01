import requests
import time
import yaml
import os
import subprocess
from datadog import statsd

from parsers import (
    Parser,
    DepotArgs,
    EsbuildUserArgs,
    EsbuildPrivateArgs,
    MinionArgs,
)
from cdisutils.log import get_logger
logger = get_logger('esbuild_minion')

root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, 'config.yml'), 'r').read())

TIMEDELTA = config['timedelta']


def minion_argparser():
    """
    Returns arguments parser for esbuild minion
    """
    return Parser.build_parser([
        DepotArgs,
        MinionArgs,
        EsbuildUserArgs,
        EsbuildPrivateArgs,
    ], description='Esbuild minion arguments parser')


def get_job(args):
    """
    Get job from depot queue
    """
    # Get job from depot api:
    job = requests.get('http://{}:{}/v0/work/{}'
                       .format(args.host, args.port, args.queue_id))
    try:
        job = job.json()
        esbuild_args = job['esbuild_args']
    except Exception as err:
        logger.error("Invalid job: {}\nError: {}".format(job, err))
        return

    if job.get('status') == 'No job found':
        return

    statsd.event(
        "Job received",
        "job: {}".format(job),
        source_type_name="esbuild-minion",
        alert_type="info",
        tags=["es_index:{}".format(args.index_name), 'minion'],
    )
    # Make sure that arguments are valid:
    esbuild_parser = Parser.build_parser([EsbuildUserArgs, EsbuildPrivateArgs])
    esbuild_parser.parse_args(esbuild_args)
    return job


def get_minion_command(job):
    """
    Prepares the command for minion to run given the job json
    """
    esbuild_args = job['esbuild_args']
    command = ['sudo /var/tungsten/services/esbuild/es_build_{}_wrapper'
               .format(job['index_type'])] + esbuild_args
    command = ' '.join(map(str, command))
    return command


if __name__ == "__main__":
    args = minion_argparser().parse_args()
    while True:
        job_json = get_job(args)
        if job_json:
            # Compose and execute the command:
            command = get_minion_command(job_json)
            logger.info('-> Running {}'.format(command))
            if args.do_not_wait_for_completion:
                # NOTE: Will result in all jobs of the queue running on a single machine
                subprocess.Popen(command, shell=True)
            else:
                subprocess.call(command, shell=True)
        else:
            time.sleep(TIMEDELTA)
