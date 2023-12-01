#!/usr/bin/env python3

import argparse
import time
from importlib.resources import files
from multiprocessing import Process
from typing import Any, Dict, Optional, cast
from ddtrace import tracer

import psqlgraph
import yaml
from elasticsearch import Elasticsearch
from indexclient import client

import esbuild
from esbuild import logging
from esbuild.gdc_elasticsearch import GDCElasticsearch
from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.utils import (
    ES_CONFIG,
    get_default_index_client,
    get_default_pg_driver,
    get_queue_client,
)

_ = logging.init_logging(level=logging.INFO)
logger = logging.getLogger(__name__)

config = yaml.safe_load(files(esbuild).joinpath("config.yml").read_text())

TIMEDELTA = config["timedelta"]


def get_gdc_elasticsearch(
    indexd_client: client.IndexClient,
    pg_driver: psqlgraph.PsqlGraphDriver,
    es_client: Elasticsearch,
    payload: dict,
    save_doc_path: str = None,
    skip_es: bool = False,
) -> GDCElasticsearch:
    """Parse and validate payload and return GDCElasticsearch instance.

    Args:
        indexd_client: Indexd Client
        pg_driver: psql graph driver
        es_client: elasticsearch client
        payload: job payload
        save_doc_path: Where to save docs (if necessary)
        skip_es: Skips writing to es

    Returns:
        GDCElasticsearch

    Raises:
        ValueError when build type is not active
    """
    build_type = payload.get("build-type")

    if build_type != "active":
        raise ValueError(f"Unknown build-type: '{build_type}'")

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
        build_projects=build_projects,
        index_alias_prefix=alias,
        save_doc_path=save_doc_path,
        skip_es=skip_es,
        **payload,
    )

    return gdc_es


@tracer.wrap(name="esbuild-minion", service="esbuild")
def process_work(
    worker_id: int,
    queue_type: str,
    queue_id: str,
    skip_es: bool = False,
    save_doc_path: str = "",
    sleep_time: int = 30,
    no_statsd: bool = False,
) -> None:
    running = True

    queue_client = get_queue_client(queue_type, queue_id)
    pg_driver = get_default_pg_driver()
    indexd_client = get_default_index_client()
    es_client = Elasticsearch(**ES_CONFIG)

    logger.info(
        f"Initializing queue client on worker_id: {worker_id} to connect to queue_id: {queue_client.queue_id}"
    )

    while running:
        payload = cast(Optional[dict], queue_client.dequeue())

        if not payload:
            logger.info("No work found, exiting")
            break

        try:
            gdc_es = get_gdc_elasticsearch(
                indexd_client,
                pg_driver,
                es_client,
                payload,
                save_doc_path=save_doc_path,
                skip_es=skip_es,
            )

            logger.info(f"Running build-type 'active', build_awg '{gdc_es.build_awg}'")
            logger.info(f"Payload: {payload}")

            gdc_es.go(
                roll_alias=not payload.get("no-roll"),
                send_events=not no_statsd,
            )
        except Exception as e:
            logger.exception(str(e))

        time.sleep(sleep_time)


def minion_argparser() -> argparse.ArgumentParser:
    """Parse run arguments for esbuild minion.

    Returns:
        argparse argument parser
    """
    parser = argparse.ArgumentParser(
        description="Parses esbuild job parameters",
    )
    parser.add_argument(
        "--queue-type",
        choices=["depot", "rabbitmq"],
        default="rabbitmq",
        help="Type of queue backend to use for scheduling" "(defaults to 'rabbitmq'",
    )
    parser.add_argument("--queue-id", type=str, help="Name of queue to bind to")
    parser.add_argument(
        "--num_procs",
        help="How many processes minion will run to process depot entries",
        default=4,
        type=int,
    )
    parser.add_argument(
        "--save_doc_path",
        help="Where to save docs (if necessary)",
        default="/var/log/esbuild",
    )
    parser.add_argument(
        "--skip_es", help="Skips writing to es", action="store_true", default=False
    )
    parser.add_argument(
        "--no-statsd", help="Do not send events to Datadog", action="store_true"
    )
    return parser


if __name__ == "__main__":
    args = minion_argparser().parse_args()
    procs = []

    # create processes
    for i in range(0, args.num_procs):
        logger.info(f"Creating process {i}")
        proc_info: Dict[str, Any] = dict(id=i)

        proc_info["process"] = Process(
            target=process_work,
            kwargs=dict(
                worker_id=i,
                queue_type=args.queue_type,
                queue_id=args.queue_id,
                skip_es=args.skip_es,
                save_doc_path=args.save_doc_path,
                sleep_time=TIMEDELTA,
                no_statsd=args.no_statsd,
            ),
        )
        proc_info["status"] = "running"
        procs.append(proc_info)
        proc_info["process"].start()

    for proc in procs:
        proc["process"].join()
