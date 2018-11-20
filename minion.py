import requests
import argparse
import time
import yaml
import os
import subprocess
from multiprocessing import Process
import multiprocessing

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
    parser.add_argument('--num_threads',
                        help='How many threads minion will run to process depot entries',
                        default=4)
    return parser


def process_work(worker_id,
                 depot_host,
                 depot_port,
                 depot_queue_id,
                 sleep_time):

    running = True
    found_work = False
    logger = get_logger('esbuild_minion_{}'.format(worker_id))
    while running:
        # Get work from depot api:
        work = requests.get('http://{}:{}/v0/work/{}'
                            .format(depot_host, depot_port, depot_queue_id))
        try:
            work = work.json()
        except Exception as err:
            logger.error("Invalid job: {}\nError: {}".format(work, err))
        else:
            if work.get('status') == 'No work found':
                if found_work:
                    running = False
            else:
                try:
                    # Make sure that arguments are valid:
                    esbuild_argparser().parse_args(work['arguments'])
                    # Compose and execute the command:
                    command = ('sudo /var/tungsten/services/esbuild/es_build_{}_wrapper {}'
                               .format(work['build_type'], ' '.join(work['arguments'])))
                    logger.info('-> Running {}'.format(command))
                    subprocess.call(command, shell=True)
                except Exception as err:
                    logger.error("Attempted to run job: {}\nError: {}".format(work, repr(err)))

            time.sleep(sleep_time)

if __name__ == "__main__":
    args = minion_argparser().parse_args()
    
    threads = []

    # create processes
    for i in range(0, num_threads):
        logger.info("Creating thread {}".format(i))
        thread_info = {}

        thread_info['id'] = i
        thread_info['process'] = Process(target=process_work,
                                         args=(i,
                                               args.host,
                                               args.port,
                                               args.queue_id,
                                               TIMEDELTA))
        thread_info['status'] = "running"
        thread_count = thread_count + 1
        threads.append(thread_info)
        thread_info['process'].start()

    for thread in threads:
        thread['process'].join()

