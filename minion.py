import requests
import argparse
import time
import yaml
import os

from master import esbuild_argparser
from cdisutils.log import get_logger
logger = get_logger('esbuild_minion')

root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, 'config.yml'), 'r').read())

TIMEDELTA = config['timedelta']


def minion_argparser():
    """Parses depot arguments for esbuild minion"""

    parser = argparse.ArgumentParser(description='Parses esbuild job parameters')
    parser.add_argument('--host',
                        help='Depot server host',
                        required=True)
    parser.add_argument('--port',
                        type=int,
                        help='Depot server port',
                        required=True)
    parser.add_argument('--queue-id', type=str,
                        help='Depot queue id to listen to. Has to be UUID string',
                        required=True)

    return parser


if __name__ == "__main__":
    args = minion_argparser().parse_args()

    while True:
        # Get work from depot api:
        work = requests.get('http://{}:{}/v0/work/{}'
                            .format(args.host, args.port, args.queue_id))
        try:
            work = work.json()
        except Exception as err:
            logger.error("Invalid job: {}\nError: {}".format(work, err))

        if work.get('status') == 'No work found':
            continue

        try:
            # Make sure that arguments are valid:
            esbuild_argparser().parse_args(work['arguments'])
            # Compose and execute the command:
            command = ('sudo /var/tungsten/services/esbuild/es_build_{}_wrapper {}'
                       .format(work['build_type'], ' '.join(work['arguments'])))
            logger.info('-> Running {}'.format(command))
            os.system(command)
        except Exception as err:
            logger.error("Attempted to run job: {}\nError: {}".format(work, err))

        time.sleep(TIMEDELTA)
