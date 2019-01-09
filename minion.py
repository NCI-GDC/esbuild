import socket
import os
import multiprocessing
import config as conf
from datadog import statsd

from bin.es_build import main
from parsers import ParserBuilder
from utils.release import ReleaseManifestUtil
from queueclient import DepotQueueClient
from cdisutils.log import get_logger

logger = get_logger('esbuild_minion')

root_dir = os.path.dirname(os.path.abspath(__file__))


def minion_argparser():
    """
    Returns arguments parser for esbuild minion
    """
    return ParserBuilder.build(
        conf.MINION_PARSERS, description='Esbuild minion arguments parser'
    )


def execute_esbuild(job_json):
    """
    Executes one esbuild job
    """
    esbuild_args = job_json['esbuild_args']
    build_type = job_json['build_type']

    # Send the event to datadog
    statsd.event(
        "Job received",
        "job: {}".format(job_json),
        source_type_name="esbuild-minion",
        alert_type="info",
        tags=["es_index:{}".format(args.index_name), 'minion'],
    )

    # Make sure that arguments are valid:
    esbuild_parser = ParserBuilder.build(conf.ESBUILD_PARSERS)
    esbuild_args = esbuild_parser.parse_args(esbuild_args)

    logger.info('-> Running esbuild')
    start, end = main(args=esbuild_args)
    if build_type == 'release':
        logger.info('-> Saving release manifest')
        log_release(esbuild_args, start, end)


def log_release(args, start_time, end_time):
    """
    Handles release manifest file create/update
    """
    time_format = '%Y-%m-%d-%H:%M:%S'
    manifest_entry = {
        "host": socket.gethostname(),
        "started": start_time.strftime(time_format),
        "ended": start_time.strftime(time_format),
        "duration": (end_time - start_time).seconds / 3600.0,
        "arguments": ParserBuilder.get_args_dict(args, conf.ESBUILD_PARSERS),
    }
    index_name = args.index_name

    if not index_name.startswith('release-'):
        raise ValueError("Unexpected index_name. Must start with 'release-'")

    release_name = index_name.split('-')[1]
    file_name = '{}.json'.format(release_name)

    # create/update manifest in s3
    ReleaseManifestUtil().put_manifest(manifest_entry, file_name)


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
