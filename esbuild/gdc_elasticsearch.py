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

from cdisutils.log import get_logger
from datadog import statsd
from elasticsearch import NotFoundError, Elasticsearch
from elasticsearch.exceptions import AuthorizationException
from gdcdatamodel.models import File
from progressbar import ProgressBar, Percentage, Bar, ETA
from psqlgraph import PsqlGraphDriver
from threading import Thread

# TODO this could probably be bumped now that the number of bulk
# threads in the config is higher, c.f.
# https://github.com/NCI-GDC/tungsten/commit/3ac690d19dd49f8ad2f30bf55ca6fe70ff2cc51d
BATCH_SIZE = 4


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


def progress_bar(title, maxval):
    """Create and initialize a custom progressbar

    :param str title: The text of the progress bar
    "param int maxva': The maximumum value of the progress bar

    """

    pbar = ProgressBar(widgets=[
        title,
        Percentage(), ' ',
        Bar(marker='#', left='[', right=']'),
        ' ',
        ETA(),
        ' ',
    ], maxval=maxval)

    pbar.update(0)

    return pbar


def bulk_upload(es, index, doc_type, docs, batch_size=BATCH_SIZE):
    """Chunk and upload docs to Elasticsearch.  This function will raise
    an exception of there were errors inserting any of the
    documents

    :param es: Elasticsearch client
    :param str index: The index to upload documents to
    :param str doc_type: The type of document to pload as
    :param list docs: The documents to upload
    :param int batch_size: The number of docs per batch

    """

    if not docs:
        return

    instruction = {"index": {"_index": index, "_type": doc_type}}
    pbar = progress_bar('{} upload '.format(doc_type), len(docs))

    def body():
        start = pbar.currval
        for doc in docs[start:start+batch_size]:
            yield instruction
            yield doc
            pbar.update(pbar.currval+1)
    while pbar.currval < len(docs):
        res = es.bulk(body=body())
        if res['errors']:
            raise RuntimeError(json.dumps([
                d for d in res['items'] if d['index']['status'] != 100
            ], indent=2))
    pbar.finish()


def upload_to_index(es, index, case_docs, ann_docs, file_docs,
                    project_docs, batch_size=BATCH_SIZE):
    """Upload {case,ann,file,project}_docs to `index` with Elasticsearch
    client `es`

    """

    bulk_upload(es, index, 'project', project_docs, batch_size)
    bulk_upload(es, index, 'annotation', ann_docs, batch_size)
    bulk_upload(es, index, 'case', case_docs, batch_size)
    bulk_upload(es, index, 'file', file_docs, batch_size)


def async_upload_to_index(es, index, case_docs, ann_docs, file_docs,
                          project_docs, batch_size=BATCH_SIZE):

    """Spawn a thread to upload {case,ann,file,project}_docs to `index`
    with Elasticsearch client `es` asynchronously

    """

    thread = Thread(target=upload_to_index, args=(
        es,
        index,
        case_docs,
        ann_docs,
        file_docs,
        project_docs,
        batch_size,
    ))

    thread.start()

    return thread


class GDCElasticsearch(object):

    """
    """

    def __init__(self, converter_class, es=None,
                 index_base="gdc_from_graph"):
        """Walks the graph to produce elasticsearch json documents.

        :param es: An instance of Elasticsearch class
        :param converter_class: Class to use as a converter

        """
        self.index_base = index_base
        self.log = get_logger("gdc_elasticsearch")
        if es:
            self.es = es
        else:
            # TODO sniff_on_start here?
            self.es = Elasticsearch(
                hosts=[os.environ["ELASTICSEARCH_HOST"]],
                http_auth=(os.environ.get("ES_USER", ""),
                           os.environ.get("ES_PASSWORD", "")),
                timeout=9999)

        self.graph = PsqlGraphDriver(
            os.environ["PG_HOST"],
            os.environ["PG_USER"],
            os.environ["PG_PASS"],
            os.environ["PG_NAME"],
        )

        self.converter = converter_class(self.graph)

    def denormalize_database(self):
        """Cache the database, stash the to_delete files, and build the
        index. Returns a generator yielding (case, file, annotation,
        project) docs for each project

        """

        with self.graph.session_scope(must_inherit=True):
            self.log.info("Caching database")
            self.converter.cache_database()

            self.log.info("Denormalizing database into JSON docs")

            project_indexes = self.converter.denormalize_all_by_projects()

            for project_index in project_indexes:
                # (case_docs, file_docs, ann_docs, project_docs)
                yield project_index


    def get_to_delete_nodes(self):
        """Store list of nodes to be deleted after index is successfully
        released.  See also :func:`self.delete_to_delete_nodes`.

        """

        with self.graph.session_scope(must_inherit=True):
            self.log.info("Querying for old nodes to delete")
            to_delete = self.graph.nodes().sysan({"to_delete": True}).all()
            to_delete = [n for n in to_delete if not shouldnt_delete(n)]
            self.log.info("Found %s to_delete nodes, saving for later",
                          len(to_delete))

        return to_delete

    def go(self, roll_alias=True, batch_size=BATCH_SIZE):
        """Create a new index with an incremented name based on
        self.index_base, populates it with a new index

        """

        last_upload_thread = None

        # Create index and upload mapping
        index = self.setup_new_index()

        case_count = 0
        file_count = 0
        annotation_count = 0
        project_count = 0

        # having a transation out here is important, since it ensures
        # that the cached database and which nodes get deleted is
        # consistent
        with self.graph.session_scope():

            # Store nodes that should be deleted later
            to_delete = self.get_to_delete_nodes()

            # Create generator that returns partial indexes
            project_indexes = self.denormalize_database()

            # Consume generator and load into ES asynchronously
            for project_index in project_indexes:
                case_docs, file_docs, ann_docs, project_docs = project_index

                case_count += len(case_docs)
                annotation_count += len(ann_docs)
                file_count += len(file_docs)
                project_count += len(project_docs)

                # Only allow one index to upload asynchronously at
                # one time, so join the last one if it exists
                if last_upload_thread is not None:
                    self.log.info("Waiting for previous upload thread...")
                    last_upload_thread.join()

                # Asynchronously upload this project
                last_upload_thread = async_upload_to_index(
                    self.es, index, case_docs, ann_docs, file_docs,
                    project_docs, batch_size)
                self.log.info("Spawned async upload thread")

        # Wait for last upload thread
        if last_upload_thread is not None:
            self.log.info("Waiting on final upload thread.")
            last_upload_thread.join()
        else:
            raise RuntimeError(
                "No async thread was used, so no docs were uploaded.")

        # Check the total number of docs are in ES
        self.check_document_counts(
            index, case_count, file_count, annotation_count, project_count)

        # Update the alias to point to the new index
        if roll_alias:
            self.roll_alias(index)
        else:
            self.log.info("Skipping alias roll / old index deletion")

        self.delete_to_delete_nodes(to_delete)

        statsd.event(
            "esbuild finished",
            "successfully built index {}".format(index),
            source_type_name="esbuild",
            alert_type="success",
            tags=["es_index:{}".format(index)],
        )

    def delete_to_delete_nodes(self, to_delete_nodes):
        """To make the index release appear atomic, files can be marked
        `to_delete == True` in system_annotations.  If it is, esbuild
        will delete it as the last step in an index release.  This
        keeps postgres and the Elasticsearch index as consistant as
        possible.

        """

        with self.graph.session_scope() as session:
            for expired_node in to_delete_nodes:
                node = (self.graph.nodes(expired_node.__class__)
                        .ids(expired_node.node_id)
                        .scalar())
                if node:
                    self.log.info("Deleting %s", node)
                    session.delete(node)

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

    def get_next_index_name(self):
        """Generates and returns the string with the index name of the next
        index based on the highest numbered existing index

        """

        current_numbers = self.get_index_numbers()
        self.log.info("Currently deployed indices are %s", current_numbers)

        if not current_numbers:
            index_number = 1
        else:
            index_number = max(current_numbers)+1

        new_index = INDEX_PATTERN.format(base=self.index_base, n=index_number)

        return new_index

    def setup_new_index(self):
        """Create a new index by incrementing the naming scheme.

        :returns: A string name of the index

        """

        new_index = self.get_next_index_name()

        self.log.info("Deploying to index %s", new_index)
        index_settings = self.converter.mapper.index_settings()
        self.es.indices.create(index=new_index, body=index_settings)
        self.put_mappings(new_index)

        return new_index

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

    def get_index_numbers(self):
        """Return the numbers of the current set of indices. So concretely if
        we have gdc_from_graph_23, gdc_from_graph_24, and
        gdc_from_graph_25, this will return [23, 24, 25].

        """

        indices = set(self.es.indices.get_aliases().keys())
        p = re.compile(INDEX_PATTERN.format(base=self.index_base, n='(\d+)')+'$')
        matches = [p.match(index) for index in indices if p.match(index)]
        numbers = sorted([int(m.group(1)) for m in matches])
        return numbers

    def lookup_index_by_alias(self):
        """Find the index that an Elasticsearch alias is poiting to. Return
        None if the index doesn't exist.

        """
        try:
            keys = self.es.indices.get_alias(self.index_base).keys()
            if not keys:
                return None
            return keys[0]
        except NotFoundError:
            return None

    def check_document_counts(self, index, file_count, case_count, ann_count,
                              project_count):
        """sanity checks that there are the correct number of docs in the new
        index and logs warnings of counts don't match

        """

        msg = 'There appears to be the wrong number of {0} files. {1} != {2}'

        es_file_count = self.es.count(index=index, doc_type="file")["count"]
        es_case_count = self.es.count(index=index, doc_type="case")["count"]
        es_ann_count = self.es.count(index=index, doc_type="annotation")["count"]
        es_project_count = self.es.count(index=index, doc_type="project")["count"]

        if es_file_count != file_count:
            self.log.warning(msg.format('file', es_file_count, file_count))

        if es_case_count != case_count:
            self.log.warning(msg.format('case', es_case_count, case_count))

        if es_ann_count != ann_count:
            self.log.warning(msg.format('annotation', es_ann_count, ann_count))

        if es_project_count != project_count:
            self.log.warning(msg.format('project', es_project_count, project_count))

    def roll_alias(self, new_index):
        """atomically switch the alias to point to the new index, and delete
        anything older than the last 5 versions of this index.

        """

        # ensure all writes are visible
        self.es.indices.refresh(index=new_index)

        # Roll indices
        self.log.info("Rolling alias and deleting old indices")
        old_index = self.lookup_index_by_alias()

        if old_index:
            assert old_index.startswith(self.index_base)
            self.swap_index(old_index, new_index)
        else:
            self.es.indices.put_alias(index=new_index, name=self.index_base)

        self.cleanup_old_indices([old_index, new_index])

    def cleanup_old_indices(self, kept):
        self.log.info("Deleting old indices")

        index_numbers = self.get_index_numbers()
        indices = [
            INDEX_PATTERN.format(base=self.index_base, n=n)
            for n in index_numbers
        ]

        if len(index_numbers) <= 5:
            self.log.info("less than 5 matching indices found, not deleting anything")
            to_close = indices
            to_delete = []

        else:
            to_delete = indices[0:-5]
            to_close = indices[-5:]

        self.log.info("Deleting indices %s", to_delete)
        for index in to_delete:
            self.log.info("Deleting %s", index)
            self.es.indices.delete(index=index)

        for index in to_close:
            if index not in kept:
                self.log.info("Closing %s", index)
                try:
                    self.es.indices.flush(index=index)
                except AuthorizationException as exception:
                    # authorization exception will be raised if it's
                    # already closed
                    if "IndexClosedException" in exception.error:
                        self.log.info("%s is already closed", index)
                        continue
                    else:
                        self.log.exception("Fail to flush %s", index)
                except:
                    self.log.exception("Can't flush index %s", index)

                try:
                    self.es.indices.close(index=index)
                except:
                    self.log.error("Can't close index %s", index)
