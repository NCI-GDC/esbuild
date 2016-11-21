#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
esbuild.gdc_datarelease
----------------------------------

Defines functions to build graph indices and...
1.) save to disk
2.) read from disk
3.) upload to elasticsearch
4.) upload to s3

"""

import argparse
import json
import os
import re

from cdisutils import md5sum
from cdisutils.log import get_logger
from datadog import statsd
from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder
from esbuild.gdc_diskIO import GDCDiskIO, DocTypes, documents_eq

from esbuild.export.es_upload import GDCElasticsearch
from esbuild.export.s3_upload import GDCS3

from elasticsearch import NotFoundError, Elasticsearch
from gdcdatamodel.models import File
from psqlgraph import PsqlGraphDriver


def shouldnt_delete(node):
    """In most cases, we delete any node that's marked
    `to_delete`. However, if the node is a file, we don't, for two reasons:

    1. We would lose the information about the alignment.

    2. CGHub sometimes suppresses and then unsupresses files. In most
    cases this is fine, but if a file has derived files, deleting and
    recreating it will cause the relevant edge to be lost, which we
    don't want.

    This is a predicate to filter files with derived files so we don't
    delete them.

    """

    # python conditionals are funny sometimes
    #
    # True  and [1,2,3] => [1,2,3]
    # False and [1,2,3] => False
    # True  or  [1,2,3] => True
    # False or  [1,2,3] => [1,2,3]

    if isinstance(node, File) and node.derived_files:
        return True
    else:
        return False


log = get_logger("gdc_datarelease")

class GDCDataRelease(object):
    def __init__(self, converter_class):
        """Walks the graph to produce json documents.

        :param converter_class: Class to use as a converter

        """

        self.active = 'active'
        self.legacy = 'legacy'


        self.graph = PsqlGraphDriver(
                os.environ["PG_HOST"],
                os.environ["PG_USER"],
                os.environ["PG_PASS"],
                os.environ["PG_NAME"],
        )

        self.converter = converter_class(self.graph)

        # go
        log.info("Caching database")

        # having a transation out here is important, since it ensures
        # that the cached database and which nodes get deleted is consistent
        with self.graph.session_scope():
            self.converter.cache_database()

        log.info("Denormalizing database into JSON docs")
        self.denormalized = self.converter.denormalize_all()

        log.info("%s case docs, %s file docs, %s annotation docs, %s project docs",
                      len(self.denormalized[0]),
                      len(self.denormalized[1]),
                      len(self.denormalized[2]),
                      len(self.denormalized[3]))

        log.info("Validating docs produced")
        self.converter.validate_docs(
            self.denormalized[0],
            self.denormalized[1],
            self.denormalized[2],
            self.denormalized[3])


    def save_to_disk(self, builder_type='active'):
        '''
            1.) take the denormalized docs and save them to disk
            2.) read them from disk
        '''
        g = GDCDiskIO(os.environ['SAVE_DIR'], builder_type)

        for i, d in enumerate(DocTypes().all_types):
            g.save_doctype(self.denormalized[i], d)

        log.info('Saving indices to disk')
        g.write_archive()
        log.info('Archive {} save: COMPLETE'.format(g.full_path_to_archive))

        log.info('Reading indices from disk')
        read_doctypes = g.read_archive()
        log.info('Reading indices from disk: COMPLETE')

        log.info('Cleaning up old indices on disk')
        g.cleanup_old_archives()
        log.info('Cleaning up old indices on disk: COMPLETE')

        denorm_md5 = g.indices_md5sum(self.denormalized)

        # be kind to your memory and it will be kind to you
        del self.denormalized

        read_md5 = g.indices_md5sum(read_doctypes)

        if not documents_eq(denorm_md5, read_md5):
            log.error('Documents not written or read correctly to or from disk')
            log.warning('md5sum from disk: {}'.format(read_md5))
            log.warning('md5sum from graph: {}'.format(denorm_md5))

        return g.full_path_to_archive, read_doctypes


    def save_to_elasticsearch(self, es=None, index_base='gdc_from_graph',
            roll_alias=True, denorm_docs=([],[],[],[])):
        ''' 3.) save to elasticsearch from disk '''

        with self.graph.session_scope():
            log.info("Querying for old nodes to delete")
            self.to_delete = self.graph.nodes().sysan({"to_delete": True}).all()
            self.to_delete = [ n for n in self.to_delete if not shouldnt_delete(n) ]

            log.info("Found %s to_delete nodes, saving for later",
                          len(self.to_delete))

        if not es:
            es = Elasticsearch(
                    hosts=[os.environ['ELASTICSEARCH_HOST']],
                    http_auth=(os.environ.get("ES_USER", ""),
                           os.environ.get("ES_PASSWORD", "")),
                    timeout=9999
            )

        gdces = GDCElasticsearch(self.converter, es=es, index_base=index_base)
        log.info("Deploying new ES index with new docs and bumping alias")

        # 0:case, 1:file, 2:annotations, 3:project
        new_index = gdces.deploy(denorm_docs[0], denorm_docs[1],
                                 denorm_docs[2], denorm_docs[3],
                                 roll_alias=roll_alias)

        with self.graph.session_scope() as session:
            for expired_node in self.to_delete:
                node = self.graph.nodes(expired_node.__class__)\
                                 .ids(expired_node.node_id)\
                                 .scalar()

                if node:
                    log.info("Deleting %s", node)
                    session.delete(node)

        statsd.event(
                "esbuild finished",
                "successfully built index {}".format(new_index),
                source_type_name="esbuild",
                alert_type="success",
                tags=["es_index:{}".format(new_index)],
        )


    def save_to_s3(self, full_path_to_archive, chunk_size=52428800):
        ''' 4.) uploads the archived indices to s3 '''

        gdcs3 = GDCS3()

        log.info("Creating s3 connection")
        gdcs3.create_connection()

        log.info("Getting or creating bucket")
        gdcs3.get_or_create_bucket()

        log.info("Uploading archive to s3")
        gdcs3.upload_to_s3(full_path_to_archive, chunk_size)

        return gdcs3.get_archive_md5sum()


    def s3_md5sum_equals(self, s3_md5sum, full_path_to_archive):
        '''
            compare the raw archive data

            this is important because the gzip headers can change
            when the archive is written. even though the contents of
            the archive can be the same, the gzip header can be different
        '''

        # compute md5sum of archive on disk
        with open(full_path_to_archive, 'r') as f:
            disk_archive_contents = f.read()

        # compare the two hashes
        return md5sum(disk_archive_contents) == s3_md5sum


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument('--test', dest='test', action='store_true',
            help='run with test defaults')
    parser.add_argument('--legacy', dest='legacy', action='store_true',
            default=False,
            help='Build legacy graph index (defaults to active)')
    args = parser.parse_args()

    if args.test:
        os.environ['SAVE_DIR'] = 'temp_dir'

        os.environ['PG_HOST'] = 'localhost'
        os.environ['PG_USER'] = 'test'
        os.environ['PG_PASS'] = 'test'
        os.environ['PG_NAME'] = 'automated_test'

        os.environ['ELASTICSEARCH_HOST'] = 'localhost'

        os.environ['S3_HOST']       = 's3.amazonaws.com'
        os.environ['S3_BUCKET']     = 'test_bucket'
        os.environ['S3_ACCESS_KEY'] = 'test_access_key'
        os.environ['S3_SECRET_KEY'] = '_test_secret_key'

    keys = ('PG_HOST', 'PG_USER','PG_PASS', 'PG_NAME', 'ELASTICSEARCH_HOST',
            'S3_HOST', 'S3_BUCKET', 'S3_ACCESS_KEY', 'S3_SECRET_KEY', 'SAVE_DIR')

    for key in keys:
        if key not in os.environ:
            log.warning('Missing environment variable: {}'.format(key))
            log.warning('Exiting')
            return

    args = parser.parse_args()

    if args.legacy == True:
        g = GDCDataRelease(converter_class=LegacyGraphIndexBuilder)
        builder_type = g.legacy
    else:
        g = GDCDataRelease(converter_class=ActiveGraphIndexBuilder)
        builder_type = g.active

    # 1.) save to disk
    # 2.) read from disk
    full_path_to_archive, denorm_docs = g.save_to_disk(builder_type)

    # 3.) upload to elasticsearch
    log.info('Uploading indices to Elasticsearch')
    g.save_to_elasticsearch(denorm_docs=denorm_docs)

    # 4.) upload to s3
    s3_md5 = ''
    if not args.test:
        s3_md5 = g.save_to_s3(args, full_path_to_archive)
    else:
        from moto import mock_s3
        @mock_s3
        def test_s3_upload():
            return g.save_to_s3(full_path_to_archive)

        s3_md5 = test_s3_upload()

    if g.s3_md5sum_equals(s3_md5, full_path_to_archive):
        log.info('Downloaded s3 md5sum integrity status: GOOD')
    else:
        log.warning('Downloaded s3 md5sum integrity status: BAD')


if __name__ == '__main__':
    main()
    log.info('GDC Data Release COMPLETE')

