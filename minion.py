import requests
import time
import yaml
import os
import subprocess
from datadog import statsd

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


def minion_argparser():
    """
    Returns arguments parser for esbuild minion
    """
    return ParserBuilder.build([
        ESArgs,
        DepotArgs,
        MinionArgs,
        EsbuildUserArgs,
        EsbuildPrivateArgs,
    ], description='Esbuild minion arguments parser')


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
    esbuild_parser = ParserBuilder.build([EsbuildUserArgs, EsbuildPrivateArgs])
    esbuild_parser.parse_args(esbuild_args)

    command = (
        ['python /var/tungsten/services/esbuild/deploy/current/es_build.py',
         '--index-type', job_json['index_type']] + esbuild_args
    )
    command = ' '.join(map(str, command))

    logger.info('-> Running {}'.format(command))
    subprocess.call(command)


if __name__ == "__main__":
    args = minion_argparser().parse_args()
    clt = DepotQueueClient(host="depot.service.consul", queue_id=args.queue_id)
    clt.consume(execute_esbuild)
