# -*- coding: utf-8 -*-
"""
esbuild.export.s3_upload
----------------------------------

Functions for uploading Elasticsearch indices to an s3 interface.
"""

from filechunkio import FileChunkIO
from boto.s3 import connection
from distutils.version import StrictVersion

import argparse
import boto
import os
import ssl
import sys
import time
import math
import httplib

from esbuild.export.elasticdump import (
    ExportTypes,
    add_es_args,
    export_to_gzip,
)


def get_or_create_bucket(conn, bucket_name):
    """create or retrieve bucket if exists"""

    if conn.lookup(bucket_name) is None:
        return conn.create_bucket(bucket_name)
    else:
        return conn.get_bucket(bucket_name)


def upload_to_s3(conn, bucket_name, source_path, chunk_size=52428800):
    """Multipart upload local path to s3"""

    bucket = get_or_create_bucket(conn, bucket_name)
    source_size = os.stat(source_path).st_size
    chunk_count = int(math.ceil(source_size / float(chunk_size)))
    name = os.path.basename(source_path)
    mp = bucket.initiate_multipart_upload(name)

    for i in range(chunk_count):
        offset = chunk_size * i
        size = min(chunk_size, source_size - offset)

        with FileChunkIO(source_path, 'r', offset=offset,  bytes=size) as fp:
            mp.upload_part_from_file(fp, part_num=i + 1)

    mp.complete_upload()


def connect_to_s3(args):
    def create_factory(host, port=443, timeout=10):
        return (
            httplib.HTTPSConnection(
                host=host,
                port=port,
                timeout=timeout,
                context=ssl._create_unverified_context()
            )
        )

    py_ver = ".".join(str(sys.version_info[i]) for i in xrange(3))
    if StrictVersion(py_ver) >= StrictVersion('2.7.9'):
        factory = (create_factory, ())
    else:
        factory = None
    return boto.connect_s3(
        host=args.s3_host,
        aws_access_key_id=args.s3_access_key,
        aws_secret_access_key=args.s3_secret_key,
        validate_certs=False,
        https_connection_factory=factory,
        calling_format=connection.OrdinaryCallingFormat(),
    )


def add_s3_args(parser):
    parser.add_argument('--s3-host',
                        required=True,
                        help='Host of s3 upload destination')
    parser.add_argument('--s3-bucket',
                        default='elasticsearch_snapshots',
                        help='Host of s3 upload destination')
    parser.add_argument('--s3-access-key',
                        required=True,
                        help='Access key for s3 upload destination')
    parser.add_argument('--s3-secret-key',
                        required=True,
                        help='Access key for s3 upload destination')

    return parser


def export_to_gzip_and_upload_to_s3(arg_list=None):
    """takes argument list or reads from command line. export and upload
    index to s3.

    """

    parser = add_es_args(add_s3_args(argparse.ArgumentParser()))

    parser.add_argument('--working-directory',
                        required=True,
                        help='Where to store local export files while working')
    parser.add_argument('--leave-files',
                        action='store_false',
                        help='Leave local export files when finished')

    args = parser.parse_args(arg_list)
    base_dir = os.path.expanduser(args.working_directory)
    conn = connect_to_s3(args)
    timestamp = int(time.time())

    for type_ in ExportTypes.ALL:
        name = '{}.{}_{}.gz'.format(args.es_index, type_, timestamp)
        path = os.path.join(base_dir, name)

        export_to_gzip(
            path,
            type_,
            args.es_index,
            args.es_host,
            port=args.es_port,
            user=args.es_user,
            password=args.es_pass)

        upload_to_s3(conn, args.s3_bucket, path)


def upload_file_to_s3(arg_list=None):
    """takes argument list or reads from command line. upload given paths
    to s3.

    """

    parser = add_s3_args(argparse.ArgumentParser())
    parser.add_argument('files', nargs='+', help='Files to upload to s3')

    args = parser.parse_args(arg_list)
    conn = connect_to_s3(args)

    for file_path in args.files:
        upload_to_s3(conn, args.s3_bucket, file_path)
