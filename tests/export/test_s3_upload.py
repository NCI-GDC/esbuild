import os

from esbuild.export.s3_upload import GDCS3
from moto import mock_s3
from tempfile import NamedTemporaryFile

@mock_s3
def test_upload_to_s3():

    bucket_name = 'test_bucket'

    os.environ['S3_HOST']       = 's3.amazonaws.com'
    os.environ['S3_BUCKET']     = bucket_name
    os.environ['S3_ACCESS_KEY'] = 'test_access_key'
    os.environ['S3_SECRET_KEY'] = 'test_secret_key'

    gdcs3 = GDCS3()
    gdcs3.create_connection()

    gdcs3.get_or_create_bucket()

    # file pointer
    full_path_to_archive = NamedTemporaryFile()
    full_path_to_archive.write('sample text')
    full_path_to_archive.seek(0)

    name = os.path.basename(full_path_to_archive.name)

    gdcs3.upload_to_s3(full_path_to_archive.name)

    assert gdcs3.conn.get_bucket(bucket_name).get_key(name).get_contents_as_string()
