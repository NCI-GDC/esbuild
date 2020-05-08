import argparse
import os
import time
from multiprocessing import Process

import yaml
from cdislogging import get_logger
from queueclient.depot import DepotQueueClient

from bin.base_build import main
from esbuild.graph.active.builder import ActiveGraphIndexBuilder

logger = get_logger('esbuild_minion', log_level='info')
root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, 'config.yml'), 'r').read())

TIMEDELTA = config['timedelta']


def minion_argparser():
    """Parses depot arguments for esbuild minion"""

    parser = argparse.ArgumentParser(
        description='Parses esbuild job parameters',
    )
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
    parser.add_argument("--es5",
                        help="Use Elasticsearch5 backend",
                        action="store_true")
    return parser


def process_work(worker_id=None,
                 depot_host='depot.service.consul',
                 depot_port=80,
                 depot_queue_id=None,
                 indexd_args=None,
                 skip_es=None,
                 save_doc_path=None,
                 sleep_time=None,
                 es5=False):

    running = True
    found_work = False
    logger = get_logger('esbuild_minion_{}'.format(worker_id), log_level='info')

    depot = DepotQueueClient(
        depot_queue_id,
        host=depot_host,
        port=depot_port,
    )
    while running:
        # Get work from depot api:
        try:
            work = depot.dequeue()  # type: dict
        except Exception as err:
            logger.error("Unable to get work.\nError: %s", err)
            time.sleep(sleep_time)
            continue

        logger.info("%s", work)
        if not work\
                or work.get('queue_status', {}).get(depot_queue_id, None) == 0 \
                or work.get('status') == 'No work found':
            if found_work:
                logger.info('No work found, exiting')
                running = False
            else:
                logger.info('No work found, waiting')
        else:
            try:
                # Compose and execute the command:
                build_type = work.get("build-type")
                if build_type == 'active':
                    builder = ActiveGraphIndexBuilder
                    if work.get('build-awg'):
                        default_alias = 'awg_from_graph'
                    else:
                        default_alias = 'gdc_from_graph'
                elif build_type == "legacy":
                    raise ValueError("Legacy support has been dropped")
                else:
                    raise Exception('Unable to find/handle build-type {}: {}'.format(work.get('build-type'), work))

                found_work = True

                alias = work.get("alias", default_alias)

                main(converter=builder,
                     indexd_args=indexd_args,
                     index_alias=alias,
                     work=work,
                     es5=es5)

                logger.info('-> Running {} build'.format(work.get('build-type')))
                work['skip-es'] = work.get('skip-es', skip_es)
                work['save-doc-path'] = work.get('save-doc-path', save_doc_path)
                logger.info(work)
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
        proc_info = dict(id=i)

        proc_info['process'] = Process(
            target=process_work,
            kwargs=dict(
                worker_id=i,
                depot_host=args.depot_host,
                depot_port=args.depot_port,
                depot_queue_id=args.queue_id,
                indexd_args=indexd_args,
                skip_es=args.skip_es,
                save_doc_path=args.save_doc_path,
                sleep_time=TIMEDELTA,
                es5=args.es5,
            )
        )
        proc_info['status'] = "running"
        procs.append(proc_info)
        proc_info['process'].start()

    for proc in procs:
        proc['process'].join()
