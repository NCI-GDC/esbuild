import os
import sys
import collections
import httplib
import boto
import ssl
from boto.s3 import connection
from distutils.version import StrictVersion


class S3Util(object):

    def __init__(self, s3_args=None):
        S3Args = collections.namedtuple(
            'S3Args', 's3_host s3_access_key s3_secret_key',
        )
        if s3_args is None:
            self.args = S3Args(
                s3_host=os.environ['S3_HOST'],
                s3_access_key=os.environ['S3_ACCESS_KEY'],
                s3_secret_key=os.environ['S3_SECRET_KEY'],
            )
        else:
            self.args = S3Args(**s3_args)

        self.conn = self._connect_to_s3()

    def _connect_to_s3(self):
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
            host=self.args.s3_host,
            aws_access_key_id=self.args.s3_access_key,
            aws_secret_access_key=self.args.s3_secret_key,
            validate_certs=False,
            https_connection_factory=factory,
            calling_format=connection.OrdinaryCallingFormat(),
        )
