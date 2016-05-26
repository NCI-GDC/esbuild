from conftest import ES_HOST, ES_PORT
from moto import mock_s3

import boto

from esbuild.export.elasticdump import (
    export_to_gzip,
    ExportTypes,
)

from esbuild.export.s3_upload import (
    export_to_gzip_and_upload_to_s3,
    upload_to_s3,
)


@mock_s3
def test_upload_to_s3(test_index, tmpdir):
    es, index, doc_type, docs = test_index
    conn = boto.connect_s3()

    name = 'test_index.mapping.gz'
    f = tmpdir.join(name)
    export_to_gzip(f.strpath, ExportTypes.MAPPING, index, ES_HOST)

    bucket = 'test_bucket'
    upload_to_s3(conn, bucket, f.strpath)
    assert conn.get_bucket(bucket).get_key(name).get_contents_as_string()


@mock_s3
def test_upload_to_s3_script(test_index, tmpdir):
    es, index, doc_type, docs = test_index

    bucket = 'test_bucket'
    args = [
        '--working-directory', tmpdir.strpath,
        '--s3-host', 's3.amazonaws.com',
        '--s3-bucket', bucket,
        '--s3-access-key', 'test_access_key',
        '--s3-secret-key', 'test_secret_key',
        '--es-host', ES_HOST,
        '--es-index', index,
        '--es-port', str(ES_PORT),
    ]

    export_to_gzip_and_upload_to_s3(args)

    conn = boto.connect_s3()
    assert len(list(conn.get_bucket(bucket).list())) == 3
