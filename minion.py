import requests
import argparse
import time
import yaml
import os
import subprocess

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
    ], description='Esbuild minion arguments parser')


def get_work(args):
    """
    Get work from depot queue
    """
    # Get work from depot api:
    work = requests.get('http://{}:{}/v0/work/{}'
                        .format(args.host, args.port, args.queue_id))
    try:
        work = work.json()
    except Exception as err:
        logger.error("Invalid job: {}\nError: {}".format(work, err))

    if work.get('status') == 'No work found':
        return

    # Make sure that arguments are valid:
    esbuild_parser = Parser.build_parser([EsbuildUserArgs, EsbuildPrivateArgs])
    esbuild_parser.parse_args(work['esbuild_args'])
    return work


def get_minion_command(work):
    """
    Prepares the command for minion to run given the work json
    """
    esbuild_args = work['esbuild_args']
    command = ['sudo /var/tungsten/services/esbuild/es_build_{}_wrapper'
               .format(work['index_type'])] + esbuild_args
    command = ' '.join(map(str, command))
    return command


if __name__ == "__main__":
    args = minion_argparser().parse_args()
    while True:
        work = get_work(args)
        if work:
            # Compose and execute the command:
            command = get_minion_command(work)
            logger.info('-> Running {}'.format(command))
            if args.do_not_wait_for_completion:
                # NOTE: Will result in all jobs of the queue running on a single machine
                subprocess.Popen(command, shell=True)
            else:
                subprocess.call(command, shell=True)
        else:
            time.sleep(TIMEDELTA)
