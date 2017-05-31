#!/usr/bin/env python

from elasticsearch import helpers, Elasticsearch
from esbuild.esutils import add_es_args
from subprocess import Popen, PIPE

import argparse
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from esbuild.export.elasticdump import (
    ExportTypes,
)

from esbuild.esutils import (
    raise_for_error,
    construct_es_target,
    construct_auth_string,
)

DOC_TYPES = [
    'project',
    'file',
    'annotation',
    'case',
]


# ======================================================================
# Change settings/mappings here

def update_settings(settings):
    """Add your updates to settings and mappings here"""

    settings['settings']['index']['number_of_shards'] = 10


def update_mappings(doc_type, mappings):
    """Add your updates to mappings and mappings here"""

    pass


# ======================================================================

def setup_index(client, old_index, new_index):
    settings = client.indices.get_settings(old_index)[old_index]
    update_settings(settings)

    try:
        client.indices.create(index=new_index, body=settings)
    except Exception as e:
        logger.warn("Couldn't create index: %s", e)

    for doc_type in DOC_TYPES:
        mapping = client.indices.get_mapping(old_index, doc_type=doc_type)
        mapping = mapping[old_index]['mappings'][doc_type]
        update_mappings(doc_type, mapping)

        client.indices.put_mapping(
            index=new_index,
            doc_type=doc_type,
            body=mapping),



def reindex(type_, source, target, host, **kwargs):
    """Starts an export with stdout, stderr piped"""

    user = kwargs.pop('user', None)
    password = kwargs.pop('password', None)
    auth = construct_auth_string(user, password)

    logger.info("Cloning %s index: %s -> %s", type_, source, target)

    process = Popen([
        'elasticdump',
        '--input', construct_es_target(source, host, auth=auth, **kwargs),
        '--output', construct_es_target(target, host, auth=auth, **kwargs),
        '--type', type_,
    ], stdout=PIPE, stderr=PIPE)
    process.wait()
    raise_for_error(process)


def main():
    """Reindex an elasticsearch index"""

    parser = add_es_args(argparse.ArgumentParser())
    parser.add_argument('--es-new-index',
                        required=True,
                        help='Elasticsearch target index')
    args = parser.parse_args()

    client = Elasticsearch(
        hosts=[args.es_host],
        http_auth=(args.es_user, args.es_pass),
        timeout=9999)

    setup_index(client, args.es_index, args.es_new_index)

    for type_ in ExportTypes.ALL:
        reindex(type_, args.es_index, args.es_new_index, args.es_host,
                user=args.es_user, password=args.es_pass)


if __name__ == "__main__":
    main()
