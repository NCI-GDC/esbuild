import time
import yaml
import os
import subprocess
import multiprocessing
from datadog import statsd

from bin.es_build import main
from parsers import (
    ParserBuilder,
    DepotArgs,
    EsbuildUserArgs,
    EsbuildPrivateArgs,
    MinionArgs,
    ESArgs,
)
from queueclient import DepotQueueClient
from cdisutils.log import get_logger
logger = get_logger('esbuild_minion')

root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, 'config.yml'), 'r').read())

TIMEDELTA = config['timedelta']

ESBUILD_PARSERS = [ESArgs, EsbuildUserArgs, EsbuildPrivateArgs]
MINION_ARGS = [DepotArgs, MinionArgs]
ALL_PARSERS = ESBUILD_PARSERS + MINION_ARGS


def minion_argparser():
    """
    Returns arguments parser for esbuild minion
    """
    return ParserBuilder.build(
        MINION_ARGS, description='Esbuild minion arguments parser'
    )


def execute_esbuild(job_json):
    """
    Executes one esbuild job
    """
    esbuild_args = job_json['esbuild_args']

    # Send the event to datadog
    statsd.event(
        "Job received",
        "job: {}".format(job_json),
        source_type_name="esbuild-minion",
        alert_type="info",
        tags=["es_index:{}".format(args.index_name), 'minion'],
    )

    # Make sure that arguments are valid:
    esbuild_parser = ParserBuilder.build(ESBUILD_PARSERS)
    esbuild_args = esbuild_parser.parse_args(esbuild_args)

    logger.info('-> Running esbuild')
    main(args=esbuild_args)


def consume_queue(host, queue_id):
    clt = DepotQueueClient(host=host, queue_id=queue_id)
    clt.consume(execute_esbuild)


if __name__ == "__main__":
    args = minion_argparser().parse_args()
    host = args.depot_host
    qid = args.queue_id

    for _ in range(args.n_threads):
        p = multiprocessing.Process(target=consume_queue, args=(host, qid))
        p.start()
