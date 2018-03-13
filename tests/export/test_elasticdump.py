from conftest import ES_HOST, ES_PORT
from esbuild.export.elasticdump import export_to_gzip, ExportTypes
from esbuild.export.s3_upload import upload_to_s3
from moto import mock_s3

import boto
import gzip
import json
import pytest


@pytest.mark.skip(reason='This feature is never used. '
                  'We use native elasticsearch plugin repository-s3 for this')
def test_export_data_to_gzip(test_index, tmpdir):
    es, index, _, _ = test_index

    f = tmpdir.join('test_index.data.gz')
    export_to_gzip(f.strpath, ExportTypes.DATA, index, ES_HOST)

    expected_dump = {doc['_id']: doc
                     for doc in es.search(index=index, size=10000)['hits']['hits']}

    with gzip.open(f.strpath, 'rb') as f:
        dump = f.read()
        lines = dump.strip().split('\n')

        assert len(lines) == len(expected_dump)
        for line in lines:
            doc = json.loads(line)
            assert doc == expected_dump[doc['_id']]


@pytest.mark.skip(reason='This feature is never used. '
                  'We use native elasticsearch plugin repository-s3 for this')
def test_export_mapping_to_gzip(test_index, tmpdir):
    es, index, doc_type, docs = test_index

    f = tmpdir.join('test_index.mapping.gz')
    export_to_gzip(f.strpath, ExportTypes.MAPPING, index, ES_HOST)

    with gzip.open(f.strpath, 'rb') as f:
        assert f.read()


@pytest.mark.skip(reason='This feature is never used. '
                  'We use native elasticsearch plugin repository-s3 for this')
def test_raises_on_failure(test_index, tmpdir):
    es, index, doc_type, docs = test_index

    with pytest.raises(RuntimeError):
        f = tmpdir.join('test_index.mapping.gz')
        export_to_gzip(f.strpath, 'marping', index, ES_HOST)
