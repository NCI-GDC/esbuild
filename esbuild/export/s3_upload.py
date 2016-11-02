# -*- coding: utf-8 -*-
"""
esbuild.export.s3_upload
----------------------------------

Functions for uploading archived indices to an s3 interface.
"""

import boto
import math
import os

from cdisutils import md5sum
from boto.s3 import connection
from filechunkio import FileChunkIO

class GDCS3():
    def __init__(self):

        self.conn   = None
        self.bucket = None

        self.bucket_name = ''
        self.base_name   = ''

    def create_connection(self):

        self.conn = boto.connect_s3(
                host                  = os.environ['S3_HOST'],
                aws_access_key_id     = os.environ['S3_ACCESS_KEY'],
                aws_secret_access_key = os.environ['S3_SECRET_KEY'],
                calling_format        = connection.OrdinaryCallingFormat(),
        )

    def get_or_create_bucket(self):

        self.bucket_name = os.environ['S3_BUCKET']
        if self.conn.lookup(self.bucket_name) is None:
            self.bucket = self.conn.create_bucket(self.bucket_name)
        else:
            self.bucket = self.conn.get_bucket(self.bucket_name)


    def upload_to_s3(self, full_path_to_archive, chunk_size=52428800):
        """Multipart upload local path to s3"""

        archive_size = os.stat(full_path_to_archive).st_size
        chunk_count = int(math.ceil(archive_size / float(chunk_size)))

        self.base_name = os.path.basename(full_path_to_archive)
        mp = self.bucket.initiate_multipart_upload(self.base_name)

        for i in xrange(chunk_count):
            offset = chunk_size * i
            size = min(chunk_size, archive_size - offset)

            # upload chunks of the archive to s3
            with FileChunkIO(full_path_to_archive, 'r', offset=offset, bytes=size) as fp:
                mp.upload_part_from_file(fp, part_num=i + 1)

        mp.complete_upload()

    def get_archive_md5sum(self):
        '''  download file from s3 and compute md5sum '''

        raw_archive =  self.conn.get_bucket(self.bucket_name).get_key(self.base_name).get_contents_as_string()
        return md5sum(raw_archive)
