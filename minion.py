import requests
import argparse
import time
import yaml
import os
import subprocess
from multiprocessing import Process
import multiprocessing

from cdisutils.log import get_logger

from bin.base_build import main
from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder
from depotclient import DepotClient

logger = get_logger('esbuild_minion')
root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, 'config.yml'), 'r').read())

TIMEDELTA = config['timedelta']

def minion_argparser():
    """Parses depot arguments for esbuild minion"""

    parser = argparse.ArgumentParser(description='Parses esbuild job parameters')
    parser.add_argument('--depot-host',
                        help='Depot server host',
                        required=True)
    parser.add_argument('--depot-port',
                        type=int,
                        help='Depot server port',
                        required=True)
    parser.add_argument('--indexd-host',
                        help='Indexd server host',
                        default=os.environ.get('INDEXD_HOST'))
    parser.add_argument('--indexd-user',
                        help='Indexd server user',
                        default=os.environ.get('INDEXD_USER'))
    parser.add_argument('--indexd-pass',
                        help='Indexd server password',
                        default=os.environ.get('INDEXD_PASS'))
    parser.add_argument('--queue-id', type=str,
                        help='Depot queue id to listen to. Has to be UUID string',
                        required=True)
    parser.add_argument('--num_procs',
                        help='How many processes minion will run to process depot entries',
                        default=4,
                        type=int)
    parser.add_argument('--save_doc_path',
                        help='Where to save docs (if necessary)',
                        default='/var/log/esbuild')
    parser.add_argument('--skip_es',
                        help='Skips writing to es',
                        action='store_true',
                        default=False)
    return parser

def process_work(worker_id=None,
                 depot_host=None,
                 depot_queue_id=None,
                 indexd_args=None,
                 skip_es=None,
                 save_doc_path=None, 
                 sleep_time=None):

    running = True
    found_work = False
    logger = get_logger('esbuild_minion_{}'.format(worker_id))
    depot = DepotClient(depot_host)
    while running:
        # Get work from depot api:
        try:
            job_data = depot.get_work(id=depot_queue_id)
        except Exception as err:
            logger.error("Unable to get work: {}\nError: {}".format(
                job_data, err))
            time.sleep(sleep_time)
            continue

        work = job_data.get('work', {})
        logger.info("{}".format(work))
        if work.get('queue_status', {}).get(depot_queue_id, None) == 0:
            if found_work:
                logger.info('No work found, exiting')
                running = False
            else:
                logger.info('No work found, waiting')
        elif work.get('status') == 'No work found':
            if found_work:
                logger.info('No work found, exiting')
                running = False
            else:
                logger.info('No work found, waiting')
        elif not work:
            if found_work:
                logger.info('No work found, exiting')
                running = False
            else:
                logger.info('No work found, waiting')
        else:
            try:
                # Compose and execute the command:
                if work.get('build-type') == 'active':
                    builder = ActiveGraphIndexBuilder
                    index_base = 'gdc_from_graph'
                elif work.get('build-type') == 'awg':
                    builder = ActiveGraphIndexBuilder
                    index_base = 'awg_from_graph'
                else:
                    raise Exception('Unable to find/handle build-type {}: {}'.format(work.get('build-type'), work))
                found_work = True
                logger.info('-> Running {} build'.format(work.get('build-type')))
                logger.info(work)

                main(converter=ActiveGraphIndexBuilder,
                     indexd_args=indexd_args,
                     index_base=index_base,
                     work=work) 
            except Exception as err:
                logger.exception("Attempted to run job: {}\nError: {}".format(work, repr(err)))
        if running:
            time.sleep(sleep_time)

if __name__ == "__main__":
    args = minion_argparser().parse_args()
    indexd_args = {'baseurl': args.indexd_host,
                   'auth': (args.indexd_user, args.indexd_pass)}

    procs = []

    # create processes
    for i in range(0, args.num_procs):
        logger.info("Creating process {}".format(i))
        proc_info = {}

        proc_info['id'] = i
        proc_info['process'] = Process(target=process_work,
                                         args=(worker_id=i,
                                               depot_host=args.depot_host,
                                               depot_queue_id=args.queue_id,
                                               indexd_args=indexd_args,
                                               skip_es=args.skip_es,
                                               save_doc_path=args.save_doc_path,
                                               sleep_time=TIMEDELTA))
        proc_info['status'] = "running"
        procs.append(proc_info)
        proc_info['process'].start()

    for proc in procs:
        proc['process'].join()

