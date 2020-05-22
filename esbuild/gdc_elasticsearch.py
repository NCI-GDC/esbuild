# -*- coding: utf-8 -*-
"""
esbuild.gdc_elasticsearch
----------------------------------

Defines functions to build graph indices and upload them to
Elasticsearch

"""

import datetime
import json
import os
import time
from typing import Dict, Iterable, List, Optional, Tuple

from cdislogging import get_logger
from datadog import statsd
from elasticsearch import (
    Elasticsearch,
    NotFoundError,
    helpers,
)
from indexclient.client import IndexClient
from progressbar import ETA, Bar, Percentage, ProgressBar
from psqlgraph import PsqlGraphDriver

from esbuild.graph.common.builder import GraphIndexBuilder
from esbuild.graph.active.mappings import ActiveESMapper
from esbuild.utils import (
    ES_CONFIG,
    ReleaseHelper,
    VersionedNodesDiffCollector,
)

# TODO: Play around with these values and find the sweet spot that
#   minimizes the loading time without crashing the ES cluster
THREAD_COUNT = 16
CHUNK_SIZE = 500
MAX_CHUNK_BYTES = 104857600  # 100MB


mapping_getters = {
    "annotation": "get_annotation_es_mapping",
    "case": "get_case_es_mapping",
    "file": "get_file_es_mapping",
    "project": "get_project_es_mapping",
}


def no_op(*_, **__):
    pass


def get_statsd_event_logger(index_prefix, projects):
    if not projects:
        projects = "all"

    projects_string = ", ".join(projects)
    index_tag = "index_group:" + index_prefix

    def statsd_event(title, text, tags, alert_type="info"):
        final_text = text + " Projects: " + projects_string
        statsd.event(
            title,
            final_text,
            source_type_name="esbuild",
            alert_type=alert_type,
            tags=[index_tag] + tags,
        )

    return statsd_event


def get_index_names(
    index_prefix: str,
    index_types: Iterable[str],
    es5: bool = False
) -> Dict[str, str]:
    """
    Return elasticsearch index names given an index_prefix.

    When es5 is True, the index names will be the same for all index types, and
    index_type will be ES5's doc_type.

    Since Elasticsearch7 does not support more than 1 doc_type per index, the
    index names will be in a format: <index_prefix>_<index_type>
    """
    if es5:
        return {
            index_type: index_prefix for index_type in index_types
        }

    return {
        index_type: "{}_{}".format(index_prefix, index_type)
        for index_type in index_types
    }


class GDCElasticsearch(object):

    """
    Walks the graph to produce elasticsearch json documents.

    Attributes:
        converter_class (GraphIndexBuilder): builder class
        indexd_client (indexclient.client.IndexClient): IndexD client instance
        es (Elasticsearch): ES client
        graph (psqlgraph.PsqlGraphDriver): db connection
        index_prefix (str): prefix to use for a set of graph indices
        build_projects (list): a list of projects to build
        selective_caching (bool): cache only data relevant to build_projects to save time
            WARNING: Will skip all nodes that do not have project_id populated
            WARNING: Does heavy query before caching resulting in memory spike. Risk of
                     running out of memory if build_projects is a large enough list (number of
                     nodes in all buld_projects is large enough)
        build_awg (bool): enable AWG specific logic
        index_replicas (int): number of replicas to create when deploying index
        index_shards (int): number of shards to allocate for a deployed index
        cache_versioned (bool): enable looking up versioned files that haven't been
            released yet
        save_doc_path (str): dump documents to this location
        event_logger (callable): statsd event logger
        index_alias_prefix (str): destination index alias
        audit: create audit documents in ES or not
        skip_es (bool): do not deploy indices to Elasticsearch
        release_helper (ReleaseHelper): utility class that does index cleanup and
            audit logging

        FIXME: Should we just drop this?
        es5: upload to an Elasticsearch5 cluster
    """

    def __init__(self,
                 converter_class: GraphIndexBuilder.__class__,
                 indexd_client: Optional[IndexClient],
                 es: Elasticsearch = None,
                 pg_driver: PsqlGraphDriver = None,
                 index_prefix: str = None,
                 build_projects: List[str] = None,
                 selective_caching: bool = False,
                 build_awg: bool = False,
                 index_replicas: int = 0,
                 index_shards: int = 1,
                 cache_versioned: bool = False,
                 save_doc_path: str = os.path.expanduser("~/esbuild_output"),
                 skip_es: bool = False,
                 index_alias_prefix: str = None,
                 audit: bool = True,
                 es5: bool = False,
                 **kwargs):
        self.converter_class = converter_class  # type: GraphIndexBuilder.__class__
        self.indexd_client = indexd_client

        self.graph = pg_driver or PsqlGraphDriver(os.environ["PG_HOST"],
                                                  os.environ["PG_USER"],
                                                  os.environ["PG_PASS"],
                                                  os.environ["PG_NAME"])
        self.index_prefix = index_prefix
        self.build_projects = build_projects
        self.selective_caching = selective_caching

        self.build_awg = build_awg

        self.index_replicas = index_replicas
        self.index_shards = index_shards
        self.cache_versioned = cache_versioned

        self.save_doc_path = save_doc_path or os.path.expanduser("~/esbuild-output")
        self.skip_es = skip_es

        self.log = get_logger("gdc_elasticsearch", log_level='info')
        self.converter = None

        self.log.info('Build arguments: {}'.format(kwargs))

        self.event_logger = no_op

        if self.skip_es:
            self.es = None
        else:
            self.es = es or Elasticsearch(timeout=9999, **ES_CONFIG)

        self.index_names = None
        self.index_aliases = None
        self.es5 = es5
        self.no_parallel_bulk = kwargs.get("no_parallel_bulk", False)

        if index_prefix:
            self.index_names = get_index_names(index_prefix, mapping_getters.keys(), es5)

        if index_alias_prefix:
            self.index_aliases = get_index_names(index_alias_prefix, mapping_getters.keys(), es5)

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
        self.release_helper = ReleaseHelper(self.es, audit_index="build_metadata",
                                            audit=audit, es5=es5)

    def save_docs(self, case_docs, file_docs, ann_docs, project_docs):

        def _save_docs(docs, filename):
            with open(filename, "w") as f:
                json.dump(docs, f, indent=2)

        time_stamp = time.strftime("%Y%m%d_%H-%M-%S")
        for file_name, docs in [("case_docs", case_docs),
                                ("file_docs", file_docs),
                                ("ann_docs", ann_docs),
                                ("project_docs", project_docs)]:
            file_name = "{}/{}_{}.json".format(self.doc_output_dir, file_name, time_stamp)
            self.log.info("Saving to {}".format(file_name))
            _save_docs(docs, file_name)

    def _cache_versioned_files(self) -> Optional[dict]:

        if not self.cache_versioned or self.build_awg or not self.build_projects:
            return None

        vnc = VersionedNodesDiffCollector(self.build_projects, self.graph, self.indexd_client)
        return vnc.run()

    def _cache_database(self, converter: GraphIndexBuilder) -> Tuple[list, list, list, list]:
        with self.graph.session_scope() as session, session.no_autoflush:
            self.log.info("Caching database")

            self.event_logger("Caching", "Started postgres caching.", tags=["stage:caching"])

            cache_start_time = datetime.datetime.now()
            converter.cache_database()
            cache_end_time = datetime.datetime.now()

            self.log.info("ANALYSIS: Loaded data in %s", cache_end_time - cache_start_time)

            self.event_logger("Denormalization", "Started denormalizing indices. ",
                              tags=["stage:denormalization"])

            cases, files, annotations, projects = converter.denormalize_all()

            denom_end_time = datetime.datetime.now()

            self.log.info("ANALYSIS: Denormalized data in %s", denom_end_time - cache_end_time)

            session.rollback()

            self.log.info(
                "ANALYSIS: %d case docs, %d file docs, %d annotation docs, %d project docs",
                len(cases), len(files), len(annotations), len(projects),
            )

            return cases, files, annotations, projects

    def _prepare_indices(self):
        if self.build_projects:
            projects_to_build = ','.join(self.build_projects)
        else:
            projects_to_build = 'all'

        self.log.info(
            "ANALYSIS: Preparing ES index to be updated "
            "with {} projects".format(projects_to_build)
        )

        self.event_logger("Indices preparation", "Started indices preparation.",
                          tags=["stage:preparation"])

        self.release_helper.add_esbuild_log(
            self.index_prefix, action="index preparation", project_ids=self.build_projects,
        )

        for index_type, index_name in self.index_names.items():
            self.release_helper.delete_docs_from_index(
                index_name,
                index_type,
                self.build_projects,
            )

    def _dump_locally(self, cases, files, annotations, projects):
        self.log.info("Skipping ES index deploy and saving docs on local storage instead")

        self.event_logger("Dump to LS", "Started dumping to LS", tags=["stage:dump"])

        self.save_docs(cases, files, annotations, projects)

        self.event_logger("Dump to LS", "Finished dumping to LS",
                          tags=["stage:dump", "status:succeeded"])

    def go(self, roll_alias=True, send_events=True):
        if not self.index_prefix:
            raise ValueError("'index_prefix' is required")

        if roll_alias and not self.index_aliases:
            raise ValueError("'index_alias_prefix' is required")

        if send_events:
            self.event_logger = get_statsd_event_logger(self.index_prefix, self.build_projects)

        versioned_files = self._cache_versioned_files()

        self.converter = self.converter_class(
            self.graph,
            self.indexd_client,
            build_projects=self.build_projects,
            build_awg=self.build_awg,
            selective_caching=self.selective_caching,
            versioned_files=versioned_files,
        )

        cases, files, annotations, projects = self._cache_database(self.converter)

        self.log.info("Validating docs produced")

        self.event_logger("Validation", "Started validation", tags=["stage:validation"])

        # TODO: Validation logic needs to be fixed, because some of the queries
        #   are invalid now. Seems like the assumption at some point was that
        #   we always build all projects
        # self.converter.validate_docs(cases, files, annotations, projects)

        # Dump skipped nodes info into a file
        self.log_skipped_nodes(self.converter.skipped_nodes)

        if not self.es or self.skip_es:
            # Skip index upload and save the documents instead
            self._dump_locally(cases, files, annotations, projects)
            return

        self._prepare_indices()

        self.log.info("Deploying new ES index with new docs")

        self.event_logger("ES Upload", "Uploading indices", tags=["stage:upload"])

        event = {
            "text": "successfully built indices for '{}'".format(self.index_prefix),
            "alert_type": "info",
        }
        extra_tags = ["status:succeeded"]

        try:
            self.deploy(cases, files, annotations, projects, roll_alias=roll_alias)
        except Exception as exception:
            self.log.exception(
                "Unable to deploy documents to {}: {}, saving to {}"
                "".format(self.index_prefix, exception,
                          self.doc_output_dir),
                exc_info=True,
            )
            event["text"] = "index deploy failed: {}".format(self.index_prefix)
            event["alert_type"] = "error"
            extra_tags = ["status:failed"]
            self.save_docs(cases, files, annotations, projects)
        finally:
            self.event_logger("ESBuild finished", tags=["stage:finished"] + extra_tags, **event)

    def log_skipped_nodes(self, skipped_nodes):
        self.log.info("Logging skipped nodes to log file in `save_doc_path`")
        self.log_into_file(skipped_nodes, self.save_doc_path, 'esbuild-skipped_nodes')

    @staticmethod
    def log_into_file(entries, path, file_nametag):
        """
        Dump entries into file `{path}/{file_nametag}_{datetime_now}.{list,json}`

        Extension depends on whether `entries` is list or dict
        """
        if isinstance(entries, list):
            extension = 'list'
        elif isinstance(entries, dict):
            extension = 'json'
        else:
            raise ValueError("Can only dump list or dict objects")

        file_name = '{}/{}-{}.{}'.format(
            path, file_nametag, datetime.datetime.now().isoformat(), extension)

        with open(file_name, 'w') as f:
            if isinstance(entries, list):
                for entry in entries:
                    f.write(entry + '\n')
            elif isinstance(entries, dict):
                f.write(json.dumps(entries, indent=2))

    def pbar(self, title, max_value):
        """Create and initialize a custom progressbar

        :param str title: The text of the progress bar
        :param int maxval: The maximum value of the progress bar

        """
        pbar = ProgressBar(
            widgets=[title, Percentage(), ' ',
                     Bar(marker='#', left='[', right=']'), ' ', ETA(), ' '],
            max_value=max_value,
        )
        pbar.update(0)
        return pbar

    def _create_index(self, index_name, index_type, index_settings, mappings):
        if not self.es.indices.exists(index=index_name):
            self.log.info("Creating new index: '{}'".format(index_name))
            self.es.indices.create(index=index_name, body=index_settings)
            self.es.indices.refresh(index=index_name)
        else:
            self.log.info("Using existing index: '{}'".format(index_name))

        if not self.es.indices.exists_type(index_name, index_type):
            self.log.info("Putting mappings for index_type: '{}'".format(index_type))

            additional_params = {}
            if not self.es5:
                additional_params["include_type_name"] = True

            self.es.indices.put_mapping(
                index=index_name,
                doc_type=index_type,
                body=mappings,
                **additional_params
            )
        else:
            self.log.info("Using existing doc_type mappings: '{}'".format(index_type))

    def create_and_populate_index(self, index_type, docs, thread_count=THREAD_COUNT,
                                  chunk_size=CHUNK_SIZE, max_chunk_bytes=MAX_CHUNK_BYTES):
        """
        Create index and put mappings for a given index_type if it doesn't exist,
        otherwise proceed with document indexing
        """
        index_name = self.index_names[index_type]
        mapping_getter = mapping_getters[index_type]

        index_settings = self.get_index_settings()
        mappings = getattr(self.converter.mapper, mapping_getter)()
        self._create_index(index_name, index_type, index_settings, mappings.to_dict())

        if not docs:
            self.log.warning("There're no documents for '{}' to populate".format(index_type))
            return

        self.log.info("Populating index %s" % index_name)

        self.populate_index(index_type, docs, thread_count, chunk_size, max_chunk_bytes)

    def populate_index(self, index_type, docs, thread_count, chunk_size, max_chunk_bytes):
        """Chunk and upload docs to Elasticsearch.  This function will raise
        an exception of there were errors inserting any of the
        documents

        Args:
            index_type (str): The index_type to upload documents to
            docs (list): The documents to upload
            thread_count (int): Number of threads to spawn during parallel bulk
                index upload
            chunk_size (int): Number of actions to perform per bulk request
            max_chunk_bytes (int): Bulk request document size limit
        """

        index_name = self.index_names[index_type]
        id_field = index_type + "_id"
        pbar = self.pbar("{} upload ".format(index_name), len(docs))

        def action_gen():
            for doc in docs:
                action = dict(
                    _index=index_name,
                    _type=index_type,
                    _id=doc[id_field],
                    _source=doc,
                )

                yield action

                pbar.update(pbar.value + 1)

        actions = action_gen()
        if self.no_parallel_bulk:
            success, errors = helpers.bulk(
                self.es,
                actions,
                chunk_size=chunk_size,
                max_chunk_bytes=max_chunk_bytes,
            )
            if errors:
                self.log.error(errors)
        else:
            batches = helpers.parallel_bulk(
                self.es,
                actions,
                thread_count=thread_count,
                chunk_size=chunk_size,
                max_chunk_bytes=max_chunk_bytes,
            )
            for batch in batches:
                if not batch[0]:
                    raise RuntimeError(
                        json.dumps([doc for doc in batch[1]
                                    if doc['index']['status'] != 100], indent=2)
                    )

        pbar.finish()

    def swap_index_alias(self, alias: str, new_index: str):
        """
        Switch the resolution of alias from old indices to new_index

        Args:
            alias: alias that needs to be updated
            new_index: new index to be associated with the alias
        """

        self.drop_aliases(alias)

        self.log.info("Adding new alias: '{}' for indices: '{}'".format(alias, new_index))

        return self.es.indices.put_alias(index=new_index, name=alias)

    def lookup_index_by_alias(self, alias):
        """
        Find a set of indices that an Elasticsearch alias is pointing to.

        Returns:
            list: a list of ES indices that have a given alias

        """
        try:
            aliases = self.es.indices.get_alias(alias)
        except NotFoundError:
            return []

        return list(aliases)

    def drop_aliases(self, alias):
        """Remove all index aliases for `alias`"""
        indices = self.lookup_index_by_alias(alias)

        if not indices:
            return

        actions = []
        for index in indices:
            actions.append({"remove": {"index": index, "alias": alias}})

        self.log.info("Removing alias: '{}', for indices: '{}'".format(alias, indices))

        return self.es.indices.update_aliases({"actions": actions})

    def deploy(self, case_docs, file_docs, ann_docs, project_docs, roll_alias=True,
               thread_count=THREAD_COUNT, chunk_size=CHUNK_SIZE,
               max_chunk_bytes=MAX_CHUNK_BYTES):
        """Create a new index with an name based on self.index_prefix, populate
        it with :func create_and_populate_index:, atomically switch the alias to
        point to the new index
        """

        self.log.info("Deploying to index %s", self.index_prefix)

        for index_type, index_docs in [("project", project_docs),
                                       ("annotation", ann_docs),
                                       ("file", file_docs),
                                       ("case", case_docs)]:

            self.create_and_populate_index(
                index_type,
                index_docs,
                thread_count=thread_count,
                chunk_size=chunk_size,
                max_chunk_bytes=max_chunk_bytes,
            )
            self.es.indices.refresh(index=self.index_names[index_type])

        self.log.info("Deployed to index %s", self.index_prefix)

        # Create audit logs for this ESBuild run
        self.release_helper.add_esbuild_log(
            self.index_prefix,
            action="upload index",
            project_ids=self.build_projects,
            index_aliases=self.index_aliases,
            build_awg=self.build_awg,
            counts={
                "annotation": len(ann_docs),
                "case": len(case_docs),
                "file": len(file_docs),
                "project": len(project_docs),
            },
        )

        if not roll_alias:
            self.log.info("Skipping alias roll")
            return

        for index_type, index_alias in self.index_aliases.items():
            self.swap_index_alias(alias=index_alias,
                                  new_index=self.index_names[index_type])

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

    def reindex(self,
                old_index: str,
                new_index: str,
                index_types: Iterable[str] = None,
                index_settings: dict = None,
                query: dict = None,
                conflicts: str = None,
                es5: bool = False) -> dict:
        """
        Perform reindex operation on an existing ``old_index``, create
        ``new_index`` with updated mappings and invoke ES reindex API. Wait for
        reindexing to copmlete and return the summary

        Args:
            old_index: existing ES index
            new_index: new ES index to be created
            index_settings: optional index settings and/or mappings, when no index_types
                are provided, the index_settings must also include "mappings"
            index_types: index types to reindex. If this is passed, then old_index
                and new_index are treated as prefixes instead
            query: optional query to be run against the original index to
                limit the documents being reindexed
            conflicts: conflicts resolution strategy in case of indexing
                collisions
            es5: use Elasticsearch5 backend

        Returns:
            dict: reindex operation summary
        """

        if old_index == new_index:
            raise ValueError(
                "New index must be different from the old one: "
                "old: '{}' new: '{}'".format(old_index, new_index)
            )

        index_settings = index_settings or self.get_index_settings()

        if not index_types:
            mappings = index_settings.pop("mappings", {})
            self._create_index(new_index, "_doc", index_settings, mappings)

            return self._reindex_one(
                old_index,
                new_index,
                index_type=None,
                conflicts=conflicts,
                query=query,
            )

        old_names = get_index_names(old_index, mapping_getters.keys(), es5)
        new_names = get_index_names(new_index, mapping_getters.keys(), es5)

        summaries = {}
        for index_type in index_types:
            index_name = new_names[index_type]

            mappings = index_settings.get("mappings", {}).get(index_type)

            if not mappings:
                mappings = getattr(ActiveESMapper, mapping_getters[index_type])()

            self._create_index(index_name, index_type, index_settings, mappings.to_dict())

            summary = self._reindex_one(
                old_names[index_type],
                index_name,
                index_type,
                conflicts,
                query,
            )

            summaries[index_type] = summary

        return summaries

    def _reindex_one(self, old_index, new_index, index_type, conflicts, query):
        self.log.info("Start reindexing: '{}' ====> '{}'".format(old_index, new_index))

        source = {
            "index": old_index,
        }

        if index_type:
            source["type"] = index_type

        reindex_body = {
            "source": source,
            "dest": {"index": new_index},
        }

        if conflicts:
            reindex_body["conflicts"] = conflicts

        if query:
            reindex_body["source"]["query"] = query

        task_info = self.es.reindex(body=reindex_body, refresh=True,
                                    wait_for_completion=False)

        task_id = task_info['task']

        self.log.info("Monitoring active reindex task: {}".format(task_id))

        summary = self._wait_for_task_completion(task_id)

        self.log.info("Reindexing completed in {} min".format(summary['took']))
        self.log.info("Summary:\n{}".format(summary))

        return summary

    def get_index_settings(self):
        """Get settings for a new index based on this instance's config."""
        index_settings = self.converter.mapper.index_settings()

        actual_settings = index_settings.setdefault('settings', {})

        if self.index_replicas is not None:
            actual_settings['index.number_of_replicas'] = self.index_replicas

        if self.index_shards is not None:
            actual_settings['index.number_of_shards'] = self.index_shards

        return index_settings
