# -*- coding: utf-8 -*-
"""
esbuild.gdc_elasticsearch
----------------------------------

Defines functions to build graph indices and upload them to
Elasticsearch

"""

import os
import re
import json
import datetime
import subprocess

from cdisutils.log import get_logger
from datadog import statsd
from elasticsearch import NotFoundError, Elasticsearch, helpers
from elasticsearch.exceptions import AuthorizationException
from gdcdatamodel.models import File
from progressbar import ProgressBar, Percentage, Bar, ETA
from psqlgraph import PsqlGraphDriver

from utils import ReleaseHelper
from parsers import (
    ESArgs,
    EsbuildPrivateArgs,
    EsbuildUserArgs,
)


# TODO: Play around with these values and find the sweet spot that
# minimizes the loading time without crashing the ES cluster
THREAD_COUNT = 16
CHUNK_SIZE = 500
MAX_CHUNK_BYTES = 104857600  # 100MB


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
    if isinstance(node, File) and node.derived_files:
        return True
    else:
        return False


class GDCElasticsearch(object):

    """
    """

    def __init__(self, converter_class, indexd_client, **kwargs):
        """Walks the graph to produce elasticsearch json documents.

        :param es: An instance of Elasticsearch class
        :param converter_class: Class to use as a converter
        :param indexd_client: indexclient.client.IndexClient() object
        :param index_name: output index name
        :param build_projects: list of projects to build
        :param selective_caching: cache only data relevant to build_projects to save time
            WARNING: Will skip all nodes that do not have project_id populated
            WARNING: Does heavy query before caching resulting in memory spike. Risk of
                     running out of memory if build_projects is a large enough list (number of
                     nodes in all buld_projects is large enough)
        :param awg_mode: whether to skip es index deployment

        """

        for p in [EsbuildPrivateArgs, EsbuildUserArgs, ESArgs]:
            for argname in p().param_names:
                setattr(self, argname, kwargs.get(argname))

        self.log = get_logger("gdc_elasticsearch")
        self.log.info('Build arguments: {}'.format(kwargs))
        self.graph = PsqlGraphDriver(
            os.environ["PG_HOST"],
            os.environ["PG_USER"],
            os.environ["PG_PASS"],
            os.environ["PG_NAME"],
        )

        self.converter = converter_class(self.graph,
                                         indexd_client,
                                         build_awg=self.awg_mode,
                                         build_projects=self.build_projects,
                                         selective_caching=self.selective_caching)
        self.converter_class_name = converter_class.__class__.__name__
        self.index_alias = self.converter.index_alias

        # TODO sniff_on_start here?
        self.es = Elasticsearch(
            hosts=[os.environ["ELASTICSEARCH_HOST"]],
            http_auth=(os.environ.get("ES_USER", ""),
                    os.environ.get("ES_PASSWORD", "")),
            timeout=9999)

        # Used to clean up data in existing index
        self.release_helper = ReleaseHelper(self.es)

    def go(self, delete_nodes=True, skip_build=False):
        # having a transation out here is important, since it ensures
        # that the cached database and which nodes get deleted is
        # consistent
        with self.graph.session_scope() as session:
            if not skip_build:
                self.log.info("Caching database")
                statsd.event(
                        "caching started",
                        "starting postgres caching",
                        source_type_name="esbuild",
                        alert_type="info",
                        tags=["es_index:{}".format(self.index_name), 'stage:caching'],
                )
                self.converter.cache_database()
            self.log.info("Querying for old nodes to delete")
            to_delete = self.graph.nodes().sysan({"to_delete": True}).all()
            to_delete = [n.node_id for n in to_delete if not shouldnt_delete(n)]
            self.log.info("Found %s to_delete nodes, saving for later",
                          len(to_delete))

        if not skip_build:
            self.log.info("Denormalizing database into JSON docs")
            statsd.event(
                    "denormalization started",
                    "starting denormalizing index".format(self.index_name),
                    source_type_name="esbuild",
                    alert_type="info",
                    tags=["es_index:{}".format(self.index_name), 'stage:denormalization'],
            )
            case_docs, file_docs, ann_docs, project_docs = self.converter.denormalize_all()
            self.log.info("%s case docs, %s file docs, %s annotation docs, %s project docs",
                          len(case_docs),
                          len(file_docs),
                          len(ann_docs),
                          len(project_docs))
            self.log.info("Validating docs produced")
            statsd.event(
                    "validation started",
                    "starting validating index {}".format(self.index_name),
                    source_type_name="esbuild",
                    alert_type="info",
                    tags=["es_index:{}".format(self.index_name), 'stage:validation'],
            )
            self.converter.validate_docs(case_docs, file_docs, ann_docs, project_docs)

            # Prepare index (if it exists) to be augmented by new data
            if self.es:
                if self.index_name in self.es.indices.get_alias():
                    if self.build_projects:
                        projects_to_build = ','.join(self.build_projects)
                    else:
                        projects_to_build = 'all'
                    self.log.info("Preparing ES index to be updated with {} projects"
                                  .format(projects_to_build))
                    statsd.event(
                            "Index preparation started",
                            "starting index {} preparation".format(self.index_name),
                            source_type_name="esbuild",
                            alert_type="info",
                            tags=['es_index:{}'.format(self.index_name),
                                  'projects:{}'.format(projects_to_build),
                                  'stage:preparation'],
                    )
                    self.release_helper.prepare_index_to_build(self.index_name,
                                                               self.build_projects)

                self.log.info("Deploying new ES index with new docs and bumping alias")
                statsd.event(
                    "es uploading started",
                    "starting uploading index {}".format(self.index_name),
                    source_type_name="esbuild",
                    alert_type="info",
                    tags=["es_index:{}".format(self.index_name), 'stage:uploading'],
                )
                new_index = self.deploy(
                    self.index_name,
                    case_docs, file_docs, ann_docs, project_docs,
                )
            else:
                new_index = 'not built'

        # Delete nodes that are marked "to_delete" if --delete flag is passed.
        # Dump to log otherwise (default behavior)
        self.delete_nodes(to_delete=to_delete, delete_nodes=delete_nodes)

        # Dump skipped nodes info into a file
        self.log_skipped_nodes()
        if not skip_build:
            statsd.event(
                "esbuild finished",
                "successfully built index {}".format(new_index),
                source_type_name="esbuild",
                alert_type="info",
                tags=["es_index:{}".format(new_index), 'stage:finished'],
            )

    def log_skipped_nodes(self):
        self.log.info("Logging skipped nodes to log file in ~")
        self.log_into_file(self.converter.skipped_nodes, 'esbuild-skipped_nodes')

    @staticmethod
    def log_into_file(entries, file_nametag):
        """
        Dump entries into file `~/{file_nametag}_{datetime_now}.{list,json}`

        Extension depends on whether `entries` is list or dict
        """
        if isinstance(entries, list):
            extension = 'list'
        elif isinstance(entries, dict):
            extension = 'json'
        else:
            raise ValueError("Can only dump list or dict objects")

        file_name = '{}/{}-{}.{}'.format(os.path.expanduser('~'),
                                         file_nametag,
                                         datetime.datetime.now().isoformat(),
                                         extension)
        with open(file_name, 'w') as f:
            if isinstance(entries, list):
                for entry in entries:
                    f.write(entry + '\n')
            elif isinstance(entries, dict):
                f.write(json.dumps(entries))

    def delete_nodes(self, to_delete=None, delete_nodes=True):
        """
        If delete_nodes is True, will remove nodes marked "sysan['to_delete']" from
        the graph
        Otherwise will dump these nodes into log file (default behavior)

        """
        if to_delete is None:
            to_delete = []

        if delete_nodes == True:
            with self.graph.session_scope() as session:
                for expired_node in to_delete:
                    node = self.graph.nodes().get(expired_node)
                    if node:
                        if 'to_delete' in node.sysan:
                            if node.sysan['to_delete']:
                                self.log.info("Deleting %s", node)
                                session.delete(node)
        else:
            self.log.info("Skipping deletion of nodes, saving them to log file in ~")
            self.log_into_file(to_delete, 'esbuild-to_delete')

    def pbar(self, title, maxval):
        """Create and initialize a custom progressbar

        :param str title: The text of the progress bar
        "param int maxva': The maximumum value of the progress bar

        """
        pbar = ProgressBar(widgets=[
            title, Percentage(), ' ',
            Bar(marker='#', left='[', right=']'), ' ',
            ETA(), ' '], maxval=maxval)
        pbar.update(0)
        return pbar

    def bulk_upload(self, index, doc_type, docs, thread_count=THREAD_COUNT,
                    chunk_size=CHUNK_SIZE, max_chunk_bytes=MAX_CHUNK_BYTES):
        """Chunk and upload docs to Elasticsearch.  This function will raise
        an exception of there were errors inserting any of the
        documents

        :param str index: The index to upload documents to
        :param str doc_type: The type of document to pload as
        :param list docs: The documents to upload
        :param int batch_size: The number of docs per batch

        """

        if not docs:
            return

        pbar = self.pbar('{} upload '.format(doc_type), len(docs))

        def action_gen():
            for doc in docs:
                action = dict(
                    _index=index,
                    _type=doc_type,
                    _id=doc[doc_type+'_id'],
                    _source=doc
                )
                yield action
                pbar.update(pbar.currval+1)

        actions = action_gen()
        batches = helpers.parallel_bulk(
            self.es,
            actions,
            thread_count=thread_count,
            chunk_size=chunk_size,
            max_chunk_bytes=max_chunk_bytes,
        )
        for batch in batches:
            if not batch[0]:
                raise RuntimeError(json.dumps([
                    doc for doc in batch[1]
                    if doc['index']['status'] != 100
                ], indent=2))
        pbar.finish()

    def put_mappings(self, index):
        """Add mappings to index.

        :param str index: The elasticsearch index

        """
        return [
            self.es.indices.put_mapping(
                index=index,
                doc_type="project",
                body=self.converter.mapper.get_project_es_mapping()),
            self.es.indices.put_mapping(
                index=index,
                doc_type="file",
                body=self.converter.mapper.get_file_es_mapping()),
            self.es.indices.put_mapping(
                index=index,
                doc_type="case",
                body=self.converter.mapper.get_case_es_mapping()),
            self.es.indices.put_mapping(
                index=index,
                doc_type="annotation",
                body=self.converter.mapper.get_annotation_es_mapping()),
        ]

    def index_populate(self, index, case_docs=[], file_docs=[],
                       ann_docs=[], project_docs=[],
                       thread_count=THREAD_COUNT,
                       chunk_size=CHUNK_SIZE,
                       max_chunk_bytes=MAX_CHUNK_BYTES):
        self.bulk_upload(index, 'project', project_docs,
                         thread_count=thread_count,
                         chunk_size=chunk_size,
                         max_chunk_bytes=max_chunk_bytes)
        self.bulk_upload(index, 'annotation', ann_docs,
                         thread_count=thread_count,
                         chunk_size=chunk_size,
                         max_chunk_bytes=max_chunk_bytes)
        self.bulk_upload(index, 'case', case_docs,
                         thread_count=thread_count,
                         chunk_size=chunk_size,
                         max_chunk_bytes=max_chunk_bytes)
        self.bulk_upload(index, 'file', file_docs,
                         thread_count=thread_count,
                         chunk_size=chunk_size,
                         max_chunk_bytes=max_chunk_bytes)

    def index_create_and_populate(self, index, case_docs=[],
                                  file_docs=[], ann_docs=[], project_docs=[],
                                  thread_count=THREAD_COUNT,
                                  chunk_size=CHUNK_SIZE,
                                  max_chunk_bytes=MAX_CHUNK_BYTES):
        """Create a new index with name `index` and add given documents to it.
        `case_docs` or `project_docs` are empty, the will be generated
        automatically.

        :param list case_docs: The case docs to upload.
        :param list file_docs:
            The file docs to upload. If case_docs is empty,
            `file_docs` will be overwritten when case_docs are
            produced.
        :param list ann_docs:
            The annotation docs to upload. If case_docs is empty,
            `ann_docs` will be overwritten when case_docs are
            produced.
        :param list project_docs: The project docs to upload.

        """

        # Create index if it does not exist (otherwise, just add the data)
        if index not in self.es.indices.get_alias():
            es_settings = {
                "index.number_of_shards": self.n_shards,
                "index.number_of_replicas": self.n_replicas,
            }
            index_settings = self.converter.mapper.index_settings(**es_settings)
            self.es.indices.create(index=index, body=index_settings)
            self.put_mappings(index)

        if not case_docs:
            self.log.warning("There were no case docs passed to populate with!")
        if not project_docs:
            self.log.warning("There were no case docs passed to populate with!")

        self.index_populate(index, case_docs, file_docs, ann_docs,
                            project_docs, thread_count=thread_count,
                            chunk_size=chunk_size, max_chunk_bytes=max_chunk_bytes)

    def swap_index(self, old_index, new_index):
        """Atomically switch the resolution of `alias` from `old_index` to
        `new_index`

        :param str old_index: Old resolution
        :param str new_index: New resolution. `alias` will point here.
        :param str alias: Alias name to swap

        """

        self.es.indices.update_aliases({'actions': [
            {'remove': {'index': old_index, 'alias': self.index_alias}},
            {'add': {'index': new_index, 'alias': self.index_alias}}]})

    def lookup_index_by_alias(self):
        """Find the index that an Elasticsearch alias is poiting to. Return
        None if the index doesn't exist.

        """
        try:
            keys = self.es.indices.get_alias(self.index_alias).keys()
            if not keys:
                return None
            return keys[0]
        except NotFoundError:
            return None

    def deploy(self, index_name, case_docs, file_docs, ann_docs, project_docs,
               thread_count=THREAD_COUNT, chunk_size=CHUNK_SIZE,
               max_chunk_bytes=MAX_CHUNK_BYTES):
        """
        - Create a new index self.index_name aliased to self.index_alias,
        - Populate it with :func index_create_and_populate:

        """

        self.log.info("Deploying to index %s", index_name)
        self.index_create_and_populate(index_name, case_docs,
                                       file_docs, ann_docs,
                                       project_docs,
                                       thread_count=thread_count,
                                       chunk_size=chunk_size,
                                       max_chunk_bytes=max_chunk_bytes)

        # Add build metadata
        doc_counts = {'case': len(case_docs), 'file': len(file_docs),
                      'project': len(project_docs), 'annotation': len(ann_docs)}
        git_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                               '.git')
        try:
            commit_hash = subprocess.check_output(['git',
                                                   '--git-dir={}'.format(git_dir),
                                                   'rev-parse', 'HEAD'])
        except Exception as err:
            commit_hash = 'unable to parse commit hash: {}'.format(repr(err))

        if self.build_projects:
            doc_id = ','.join(self.build_projects)
        else:
            doc_id = 'ALL PROJECTS'

        self.es.create(index=index_name, doc_type='build_metadata',
                       id=doc_id,
                       body={
                           'commit_hash': commit_hash,
                           'build_projects': self.build_projects,
                           'counts': doc_counts
                       })

        # ensure all writes are visible
        self.es.indices.refresh(index=index_name)

        self.validate_doc_counts(index_name)

        return index_name

    def validate_doc_counts(self, case_docs, file_docs, ann_docs, project_docs, index_name):
        """
        Validate that there are the correct number of docs in the new index
        If not, log warnings
        """
        msg = ('There appears to be the wrong number of {0} files. {1} != {2}')

        file_count = self.es.count(index=index_name, doc_type="file")["count"]
        case_count = self.es.count(index=index_name, doc_type="case")["count"]
        ann_count = self.es.count(index=index_name, doc_type="annotation")["count"]
        project_count = self.es.count(index=index_name, doc_type="project")["count"]

        if file_count != len(file_docs):
            self.log.warning(msg.format('file', file_count, len(file_docs)))

        if case_count != len(case_docs):
            self.log.warning(msg.format('case', case_count, len(case_docs)))

        if ann_count != len(ann_docs):
            self.log.warning(msg.format('annotation', ann_count, len(ann_docs)))

        if project_count != len(project_docs):
            self.log.warning(msg.format('project', project_count, len(project_docs)))
