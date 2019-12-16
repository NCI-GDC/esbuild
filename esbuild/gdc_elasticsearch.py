# -*- coding: utf-8 -*-
"""
esbuild.gdc_elasticsearch
----------------------------------

Defines functions to build graph indices and upload them to
Elasticsearch

"""

import os
import re
import time
import json
import datetime
import subprocess
import resource

from cdislogging import get_logger
from datadog import statsd
from elasticsearch import (
    NotFoundError, Elasticsearch, helpers, exceptions as es_exc,
)
from elasticsearch.exceptions import AuthorizationException
from gdcdatamodel.models import File
from progressbar import ProgressBar, Percentage, Bar, ETA
from psqlgraph import PsqlGraphDriver

from esbuild.utils import ReleaseHelper, VersionedNodesDiffCollector

# TODO: Play around with these values and find the sweet spot that
# minimizes the loading time without crashing the ES cluster
THREAD_COUNT = 16
CHUNK_SIZE = 500
MAX_CHUNK_BYTES = 104857600  # 100MB

INDEX_PATTERN = '{base}_{n}'


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

    def __init__(self, converter_class, indexd_client, index_close_thresh=5,
                 **kwargs):
        """Walks the graph to produce elasticsearch json documents.

        :param es: An instance of Elasticsearch class
        :param converter_class: Class to use as a converter
        :param indexd_client: indexclient.client.IndexClient() object
        :param index_close_thresh: we try to control the ES cluster size, by
            keeping only X number of indices and deleting old ones. Set X by
            passing this param
        :param index_base: base name template for resulting es index
        :param index_name: if provided, will build index with this name ignoring index_base
        :param build_projects: list of projects to build
        :param selective_caching: cache only data relevant to build_projects to save time
            WARNING: Will skip all nodes that do not have project_id populated
            WARNING: Does heavy query before caching resulting in memory spike. Risk of
                     running out of memory if build_projects is a large enough list (number of
                     nodes in all buld_projects is large enough)
        :param build_awg: whether to skip es index deployment
        :param skip_es: whether to skip es index deployment

        """
        valid_kwargs = [
            ('es', None),
            ('index_base', "gdc_from_graph"),
            ('index_name', None),
            ('build_projects', None),
            ('selective_caching', False),
            ('build_awg', False),
            ('skip_es', False),
            ('cache_versioned', False),
            ('save_doc_path', os.path.expanduser('~/esbuild_output'))
        ]

        for arg, default in valid_kwargs:
            setattr(self, arg, kwargs.get(arg) or default)

        self.index_close_thresh = index_close_thresh
        self.log = get_logger("gdc_elasticsearch")
        self.log.info('Build arguments: {}'.format(kwargs))
        self.graph = kwargs.pop('pg_driver',
                                PsqlGraphDriver(os.environ["PG_HOST"],
                                                os.environ["PG_USER"],
                                                os.environ["PG_PASS"],
                                                os.environ["PG_NAME"]))

        versioned_files = None
        if not self.build_awg and self.build_projects and self.cache_versioned:
            vnc = VersionedNodesDiffCollector(self.build_projects, self.graph,
                                              indexd_client)
            versioned_files = vnc.run()

        self.converter = converter_class(self.graph,
                                         indexd_client,
                                         build_awg=self.build_awg,
                                         build_projects=self.build_projects,
                                         selective_caching=self.selective_caching,
                                         versioned_files=versioned_files)
        self.converter_class_name = converter_class.__class__.__name__

        if not self.skip_es:
            if not self.es:
                # TODO sniff_on_start here?
                self.es = Elasticsearch(
                    hosts=[os.environ["ELASTICSEARCH_HOST"]],
                    http_auth=(os.environ.get("ES_USER", ""),
                               os.environ.get("ES_PASSWORD", "")),
                    timeout=9999)
        else:
            self.es = None

        if self.index_name is None:
            self.index_name = self.get_index_name()

        # where to save docs if they fail
        if os.path.exists(self.save_doc_path):
            self.doc_output_dir = self.save_doc_path
        else:
            try:
                os.mkdir(self.save_doc_path)
            except:
                self.doc_output_dir = os.getcwd()
            else:
                self.doc_output_dir = self.save_doc_path

        # Used to clean up data in existing index
        self.release_helper = ReleaseHelper(self.es)

    def save_doc(self, doc, file_name):
        with open(file_name, 'w') as out_file:
            json.dump(doc, out_file)

    def save_docs(self, case_docs, file_docs, ann_docs, project_docs):
        time_stamp = time.strftime("%Y%m%d_%H-%M-%S")
        file_name = '{}/case_docs_{}.json'.format(self.doc_output_dir, time_stamp)
        self.log.info('Saving to {}'.format(file_name))
        self.save_doc(case_docs, file_name)
        file_name = '{}/file_docs_{}.json'.format(self.doc_output_dir, time_stamp)
        self.log.info('Saving to {}'.format(file_name))
        self.save_doc(file_docs, file_name)
        file_name = '{}/ann_docs_{}.json'.format(self.doc_output_dir, time_stamp)
        self.log.info('Saving to {}'.format(file_name))
        self.save_doc(ann_docs, file_name)
        file_name = '{}/project_docs_{}.json'.format(self.doc_output_dir, time_stamp)
        self.log.info('Saving to {}'.format(file_name))
        self.save_doc(project_docs, file_name)

    def go(self, roll_alias=True, cleanup_indices=True, delete_nodes=True,
           skip_build=False):
        # having a transation out here is important, since it ensures
        # that the cached database and which nodes get deleted is
        # consistent
        new_index = None

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
                start_time = datetime.datetime.now()
                self.converter.cache_database()
                cache_end_time = datetime.datetime.now()

            to_delete = []

            self.log.info("ANALYSIS: Loaded data in %s",
                          cache_end_time - start_time)

        if not skip_build:
            self.log.info("Denormalizing database into JSON docs")
            statsd.event(
                "denormalization started",
                "starting denormalizing index: '{}'".format(self.index_name),
                source_type_name="esbuild",
                alert_type="info",
                tags=["es_index:{}".format(self.index_name),
                      'stage:denormalization'],
            )
            case_docs, file_docs, ann_docs, project_docs = self.converter.denormalize_all()
            self.log.info(
                "ANALYSIS: %d case docs,"
                "%d file docs,"
                "%d annotation docs,"
                "%d project docs",
                len(case_docs),
                len(file_docs),
                len(ann_docs),
                len(project_docs),
            )
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
                start_time = datetime.datetime.now()
                if self.index_name in self.es.indices.get_alias():
                    if self.build_projects:
                        projects_to_build = ','.join(self.build_projects)
                    else:
                        projects_to_build = 'all'
                        self.log.info(
                            "ANALYSIS: Preparing ES index to be updated "
                            "with {} projects".format(projects_to_build)
                        )
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

                denom_end_time = datetime.datetime.now()
                self.log.info(
                    "ANALYSIS: Denormalized data in %s",
                    denom_end_time - start_time
                )
                self.log.info("Deploying new ES index with new docs and bumping alias")
                statsd.event(
                    "es uploading started",
                    "starting uploading index {}".format(self.index_name),
                    source_type_name="esbuild",
                    alert_type="info",
                    tags=["es_index:{}".format(self.index_name),
                          'stage:uploading'],
                )
                try:
                    new_index = self.deploy(
                        case_docs, file_docs, ann_docs, project_docs,
                        index_name=self.index_name, roll_alias=roll_alias,
                        cleanup_indices=cleanup_indices)
                except Exception as exception:
                    self.log.exception(
                        'Unable to deploy documents to {}: {}, saving to {}'
                        ''.format(self.index_name, exception,
                                  self.doc_output_dir),
                        exc_info=True,
                    )
                    self.save_docs(case_docs, file_docs, ann_docs, project_docs)
            else:
                new_index = 'not built'

        # Delete nodes that are marked "to_delete" if --delete flag is passed.
        # Dump to log otherwise (if any in list -- default behavior)
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
        end_time = datetime.datetime.now()
        self.log.info("ANALYSIS: Run complete in %s - high water %d", end_time - start_time,
            resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)

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
            if to_delete:
                self.log.info("Skipping deletion of nodes, saving them to log file in ~")
                self.log_into_file(to_delete, 'esbuild-to_delete')

    def pbar(self, title, maxval):
        """Create and initialize a custom progressbar

        :param str title: The text of the progress bar
        "param int maxva': The maximumum value of the progress bar

        """
        pbar = ProgressBar(
            widgets=[title, Percentage(), ' ',
                     Bar(marker='#', left='[', right=']'), ' ', ETA(), ' '],
            maxval=maxval,
        )
        pbar.update(0)
        return pbar

    def bulk_upload(self, index, doc_type, docs, thread_count=THREAD_COUNT,
                    chunk_size=CHUNK_SIZE, max_chunk_bytes=MAX_CHUNK_BYTES,
                    parallel_bulk=True):
        """Chunk and upload docs to Elasticsearch.  This function will raise
        an exception of there were errors inserting any of the
        documents

        :param str index: The index to upload documents to
        :param str doc_type: The type of document to upload as
        :param list docs: The documents to upload
        :param thread_count: Number of threads to spawn during parallel bulk
            index upload
        :param chunk_size: Number of actions to perform per bulk request
        :param max_chunk_bytes: Bulk request document size limit
        :param parallel_bulk: Use parallel_bulk for index upload or not
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
                pbar.update(pbar.value + 1)

        actions = action_gen()
        if parallel_bulk:
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
        else:
            success, errors = helpers.bulk(
                self.es,
                actions,
                chunk_size=chunk_size,
                max_chunk_bytes=max_chunk_bytes,
            )
            if errors:
                self.log.error(errors)
        pbar.finish()

    def put_mappings(self, index):
        """Add mappings to index.

        :param str index: The elasticsearch index
        :returns: results of putting es mappings
        """
        return [
            self.es.indices.put_mapping(
                index=index,
                doc_type="project",
                body=self.converter.mapper.get_project_es_mapping().to_dict()
            ),
            self.es.indices.put_mapping(
                index=index,
                doc_type="file",
                body=self.converter.mapper.get_file_es_mapping().to_dict()
            ),
            self.es.indices.put_mapping(
                index=index,
                doc_type="case",
                body=self.converter.mapper.get_case_es_mapping().to_dict()
            ),
            self.es.indices.put_mapping(
                index=index,
                doc_type="annotation",
                body=self.converter.mapper.get_annotation_es_mapping().to_dict()
            ),
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
            self.log.info('Index %s not found, creating', index)
            index_settings = self.converter.mapper.index_settings()
            self.es.indices.create(index=index, body=index_settings)
            self.put_mappings(index)

        if not case_docs:
            self.log.warning("There were no case docs passed to populate with!")
        if not project_docs:
            self.log.warning("There were no case docs passed to populate with!")

        self.log.info('Populating index %s', index)
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
            {'remove': {'index': old_index, 'alias': self.index_base}},
            {'add': {'index': new_index, 'alias': self.index_base}}]})

    def get_indices(self):
        """Returns a list of open and closed index names"""

        indices = None
        if self.es:
            indices = (
                # Closed indices
                list(self.es.cluster.state()['blocks'].get('indices', {}).keys()) +
                # Open indices
                list(self.es.indices.stats()['indices'].keys())
            )
        return indices

    def get_index_numbers(self):
        """Return the numbers of the current set of indices. So concretely if we
        have gdc_from_graph_23, gdc_from_graph_24, and
        gdc_from_graph_25, this will return [23, 24, 25].
        """
        numbers = []
        indices = self.get_indices()
        if indices:
            indices = set(indices)
            p = re.compile(INDEX_PATTERN.format(base=self.index_base, n='(\d+)')+'$')
            matches = [p.match(index) for index in indices if p.match(index)]
            numbers = sorted([int(m.group(1)) for m in matches])
        return numbers

    def lookup_index_by_alias(self):
        """Find the index that an Elasticsearch alias is poiting to. Return
        None if the index doesn't exist.

        """
        try:
            index_names = list(self.es.indices.get_alias(self.index_base).keys())
            if not index_names:
                return None
            return index_names[0]
        except NotFoundError:
            return None

    def cleanup_old_indices(self, kept):
        self.log.info("Deleting old indices")
        numbers = self.get_index_numbers()
        indices = [INDEX_PATTERN.format(base=self.index_base, n=n)
                   for n in numbers]
        if len(numbers) <= self.index_close_thresh:
            self.log.info("less than 5 matching indices found, not deleting anything")
            to_close = indices
            to_delete = []
        else:
            to_delete = indices[0:-self.index_close_thresh]
            to_close = indices[-self.index_close_thresh:]

        self.log.info("Deleting indices %s", to_delete)
        for index in to_delete:
            self.log.info("Deleting %s", index)
            self.es.indices.delete(index=index)
            self.es.indices.refresh()
        for index in to_close:
            if index not in kept:
                self.log.info("Closing %s", index)
                try:
                    self.es.indices.flush(index=index)
                except AuthorizationException as e:
                    # authorization exception will be raised if it's already closed
                    if ('IndexClosedException' in str(e.error) or
                            'index_closed_exception' in str(e.error)):
                        self.log.info("%s is already closed" % index)
                        continue
                    else:
                        self.log.exception("Failed to flush %s" % index,
                                           exc_info=True)
                except:
                    self.log.exception("Can't flush index %s" % index,
                                       exc_info=True)

                try:
                    self.es.indices.close(index=index)
                except:
                    self.log.exception("Can't close index %s" % index,
                                       exc_info=True)

    def get_index_name(self):
        """Returns incremented index name"""
        current_numbers = self.get_index_numbers()
        self.log.info("Currently deployed indices are %s", current_numbers)
        if not current_numbers:
            n = 1
        else:
            n = max(current_numbers) + 1
        return INDEX_PATTERN.format(base=self.index_base, n=n)

    def deploy(self, case_docs, file_docs, ann_docs,
               project_docs, roll_alias=True, cleanup_indices=True,
               thread_count=THREAD_COUNT, chunk_size=CHUNK_SIZE,
               max_chunk_bytes=MAX_CHUNK_BYTES, index_name=None):
        """Create a new index with an incremented name based on
        self.index_base, populate it with :func
        index_create_and_populate:, atomically switch the alias to
        point to the new index, and delete anything older than the
        last 5 versions of this index.

        """
       
        # If explicit name provided, will upsert data to this particular index
        if index_name:
            new_index = index_name
        # Else will create a new index with incremented name
        else:
            new_index = self.get_index_name()

        self.log.info("Deploying to index %s", new_index)
        self.index_create_and_populate(new_index, case_docs,
                                       file_docs, ann_docs,
                                       project_docs,
                                       thread_count=thread_count,
                                       chunk_size=chunk_size,
                                       max_chunk_bytes=max_chunk_bytes)
        self.log.info("Deployed to index %s", new_index)

        # Add build metadata
        doc_counts = {'case': len(case_docs), 'file': len(file_docs),
                      'project': len(project_docs), 'annotation': len(ann_docs)}
        git_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))),
                               '.git')
        try:
            commit_hash = subprocess.check_output(['git',
                                                   '--git-dir={}'.format(git_dir),
                                                   'rev-parse', 'HEAD'])
            commit_hash = commit_hash.decode('utf-8')
        except Exception as err:
            commit_hash = 'unable to parse commit hash: {}'.format(repr(err))

        project_ids = self.build_projects or ['ALL PROJECTS']
        doc_id = ReleaseHelper.get_build_metadata_id(self.build_projects or 'ALL PROJECTS')

        self.es.create(index=new_index, doc_type='build_metadata',
                       id=doc_id,
                       body={
                           'commit_hash': commit_hash,
                           'build_projects': project_ids,
                           'counts': doc_counts
                       })

        if roll_alias:
            # ensure all writes are visible
            self.es.indices.refresh(index=new_index)

            # sanity checks that there are the correct number of docs in the new index
            msg = ('There appears to be the wrong number of {0} files. {1} != {2}')

            file_count = self.es.count(index=new_index, doc_type="file")["count"]
            case_count = self.es.count(index=new_index, doc_type="case")["count"]
            ann_count = self.es.count(index=new_index, doc_type="annotation")["count"]
            project_count = self.es.count(index=new_index, doc_type="project")["count"]

            if file_count != len(file_docs):
                self.log.warning(msg.format('file', file_count, len(file_docs)))

            if case_count != len(case_docs):
                self.log.warning(msg.format('case', case_count, len(case_docs)))

            if ann_count != len(ann_docs):
                self.log.warning(msg.format('annotation', ann_count, len(ann_docs)))

            if project_count != len(project_docs):
                self.log.warning(msg.format('project', project_count, len(project_docs)))

            # Roll indices
            self.log.info("Rolling alias and deleting old indices")
            old_index = self.lookup_index_by_alias()
            if old_index:
                self.swap_index(old_index, new_index)
            else:
                self.es.indices.put_alias(index=new_index, name=self.index_base)
            if cleanup_indices:
                self.cleanup_old_indices([old_index, new_index])
        else:
            self.log.info("Skipping alias roll / old index deletion")
        return new_index

    def _wait_for_task_completion(self, task_id):
        """
        Given an Elasticsearch task_id, wait for its completion and return
        task summary
        :param task_id: ES task ID
        :return: Task summary
        """

        summary = {}
        while True:
            response = self.es.tasks.get(task_id)

            if response['completed']:
                break

            so_far = response['task']['status']['batches']
            total = response['task']['status']['total']
            self.log.info(
                'Reindexed: {} out of {} documents'.format(so_far*1000, total)
            )
            time.sleep(10)

        summary.update(response)

        time_elapsed = response['task']['running_time_in_nanos'] // (10 ** 9)
        elapsed_mins = time_elapsed / 60.
        summary['took'] = elapsed_mins

        return summary

    def reindex(self, old_index, new_index, types=None, index_settings=None,
                query=None, conflicts=None):
        """
        Perform reindex operation on an existing ``old_index``, create
        ``new_index`` with updated mappings and invoke ES reindex API. Wait for
        reindexing to copmlete and return the summary

        :param old_index: existing ES index
        :param new_index: new ES index to be created
        :param types: ES document types to reindex
        :param index_settings: optional index settings and/or mappings
        :param query: optional query to be run against the original index to
            limit the documents being reindexed
        :param conflicts: conflicts resolution strategy in case of indexing
            collisions
        :return: reindex operation summary
        """

        self.log.info("Start reindexing")

        if old_index == new_index:
            raise ValueError(
                "New index must be different from the old one: "
                "old: '{}' new: '{}'".format(old_index, new_index)
            )

        index_settings = index_settings or self.converter.mapper.index_settings()

        reindex_body = {
            'source': {
                'index': old_index,
            },
            'dest': {
                'index': new_index,
            },
        }

        if conflicts:
            reindex_body['conflicts'] = conflicts

        if query:
            reindex_body['source']['query'] = query

        # FIXME: Maybe want to do a more extensive param check, but this should
        # cover our immediate use cases
        if types:
            types = types if isinstance(types, list) else [types]
            reindex_body['source']['type'] = types

        self.log.info("Creating new index: '{}'".format(new_index))

        self.es.indices.create(index=new_index, body=index_settings)

        if 'mappings' not in index_settings:
            self.put_mappings(new_index)

        task_info = self.es.reindex(body=reindex_body, refresh=True,
                                    wait_for_completion=False)

        task_id = task_info['task']

        self.log.info("Monitoring active reindex task: {}".format(task_id))

        summary = self._wait_for_task_completion(task_id)

        self.log.info("Reindexing completed in {} min".format(summary['took']))
        self.log.info("Summary:\n{}".format(summary))

        return summary
