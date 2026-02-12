#!/usr/bin/env python3

import argparse
import os
import time
from importlib.resources import files
from multiprocessing import Process

import datadog
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

datadog.initialize(statsd_host=os.environ.get("DD_DOGSTATSD_HOST", "localhost"))

root = logging.init_logging(logging.INFO)
logger = root.getChild("minion")
config = yaml.safe_load(files(esbuild).joinpath("config.yml").read_text())

TIMEDELTA = config["timedelta"]


def get_gdc_elasticsearch(
    indexd_client: client.IndexClient,
    pg_driver: psqlgraph.PsqlGraphDriver,
    es_client: Elasticsearch,
    payload: dict,
    save_doc_path: str | None = None,
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
        build_projects=build_projects,
        build_awg=payload.get("build-awg", False),
        index_alias_prefix=alias,
        selective_caching=payload.get("selective-caching", False),
        cache_versioned=payload.get("cache-versioned", False),
        save_doc_path=save_doc_path,
        skip_es=skip_es,
        gencode_version=payload.get("gencode-version"),
    )

    return gdc_es


def process_work(
    worker_id: int,
    queue_type: str,
    queue_id: str,
    skip_es: bool = False,
    save_doc_path: str | None = None,
    sleep_time: int = 30,
    no_statsd: bool = False,
) -> None:
    try:
        running = True
        found_work = False

        queue_client = get_queue_client(queue_type, queue_id)
        pg_driver = get_default_pg_driver()
        indexd_client = get_default_index_client()
        es_client = Elasticsearch(**ES_CONFIG)

        logger.info(
            f"Initializing queue client on worker_id: {worker_id} to connect to queue_id: {queue_client.queue_id}"
        )

        while running:
            payload = queue_client.dequeue()  # type: dict

            if not payload:
                if found_work:
                    logger.info("No work found, exiting")
                    break

                logger.info("No work found, waiting")
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

                logger.info(f"Running build_awg=={gdc_es.build_awg}")
                logger.info(f"Payload: {payload}")

                gdc_es.go(
                    roll_alias=not payload.get("no-roll"),
                    send_events=not no_statsd,
                )
            except Exception:
                logger.exception(
                    f"Minion failed for projects: {payload.get('projects', ())}",
                    exc_info=True,
                )

            time.sleep(sleep_time)
    except Exception:
        logger.critical("Minion failed.", exc_info=True)


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
        help="Type of queue backend to use for scheduling(defaults to 'rabbitmq'",
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


def main() -> None:
    try:
        args = minion_argparser().parse_args()
        procs = []

        # create processes
        for i in range(0, args.num_procs):
            logger.info(f"Creating process {i}")
            proc_info: dict = dict(id=i)

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
    except Exception:
        logger.critical("Failed to execute minions.", exc_info=True)
