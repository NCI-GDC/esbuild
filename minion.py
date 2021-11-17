import argparse
import os
import time
from multiprocessing import Process

import yaml
from cdislogging import get_logger
from elasticsearch import Elasticsearch

from esbuild.gdc_elasticsearch import GDCElasticsearch
from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.utils import (
    ES_CONFIG,
    get_default_index_client,
    get_default_pg_driver,
    get_queue_client,
)


logger = get_logger('esbuild_minion', log_level='info')
root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, 'config.yml'), 'r').read())

TIMEDELTA = config['timedelta']


def get_gdc_elasticsearch(
    indexd_client,
    pg_driver,
    es_client: Elasticsearch,
    payload: dict,
    save_doc_path: str = None,
    skip_es: bool = False,
) -> GDCElasticsearch:
    """Parse and validate payload and return GDCElasticsearch instance"""
    build_type = payload.get("build-type")

    if build_type != "active":
        raise ValueError("Unknown build-type: '{}'".format(build_type))

    if not payload.get("projects"):
        build_projects = None
    else:
        build_projects = payload["projects"].split()

    if payload.get("build-awg"):
        default_alias = "awg_from_graph"
    else:
        default_alias = "gdc_from_graph"

    alias = payload.get("alias") or default_alias

    gdc_es = GDCElasticsearch(
        converter_class=ActiveGraphIndexBuilder,
        indexd_client=indexd_client,
        pg_driver=pg_driver,
        es=es_client,
        index_prefix=payload.get("index"),
        index_replicas=payload.get("replicas"),
        build_projects=build_projects,
        build_awg=payload.get("build-awg"),
        index_shards=payload.get("shards"),
        index_alias_prefix=alias,
        selective_caching=payload.get("selective-caching"),
        cache_versioned=payload.get("cache-versioned"),
        save_doc_path=save_doc_path,
        skip_es=skip_es,
        gencode_version=payload.get("gencode-version"),
    )

    return gdc_es


def process_work(
    worker_id: int,
    queue_type: str,
    skip_es: bool = False,
    save_doc_path: str = None,
    sleep_time: int = 30,
    no_statsd: bool = False,
) -> None:
    running = True
    found_work = False

    queue_client = get_queue_client(queue_type)
    pg_driver = get_default_pg_driver()
    indexd_client = get_default_index_client()
    es_client = Elasticsearch(**ES_CONFIG)

    log = get_logger('esbuild_minion_{}'.format(worker_id), log_level='info')

    while running:
        payload = queue_client.dequeue()  # type: dict

        if not payload:
            if found_work:
                log.info("No work found, exiting")
                break

            log.info("No work found, waiting")
            time.sleep(sleep_time)
            continue

        found_work = True

        try:
            gdc_es = get_gdc_elasticsearch(
                indexd_client,
                pg_driver,
                es_client,
                payload,
                save_doc_path=save_doc_path,
                skip_es=skip_es,
            )

            log.info("Running build-type 'active', build_awg '{}'".format(gdc_es.build_awg))
            log.info("Payload: {}".format(payload))

            gdc_es.go(
                roll_alias=not payload.get("no-roll"),
                send_events=not no_statsd,
            )
        except Exception as e:
            log.exception(str(e))

        time.sleep(sleep_time)


def minion_argparser():
    """Parses run arguments for esbuild minion"""

    parser = argparse.ArgumentParser(
        description='Parses esbuild job parameters',
    )
    parser.add_argument("--queue-type",
                        choices=["depot", "rabbitmq"],
                        default="rabbitmq",
                        help="Type of queue backend to use for scheduling"
                             "(defaults to 'rabbitmq'")
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
    parser.add_argument("--no-statsd",
                        help="Do not send events to Datadog",
                        action="store_true")
    return parser


if __name__ == "__main__":
    args = minion_argparser().parse_args()
    procs = []

    # create processes
    for i in range(0, args.num_procs):
        logger.info("Creating process {}".format(i))
        proc_info = dict(id=i)

        proc_info['process'] = Process(
            target=process_work,
            kwargs=dict(
                worker_id=i,
                queue_type=args.queue_type,
                skip_es=args.skip_es,
                save_doc_path=args.save_doc_path,
                sleep_time=TIMEDELTA,
                no_statsd=args.no_statsd,
            )
        )
        proc_info['status'] = "running"
        procs.append(proc_info)
        proc_info['process'].start()

    for proc in procs:
        proc['process'].join()
