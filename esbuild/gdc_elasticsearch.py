# -*- coding: utf-8 -*-
"""
esbuild.gdc_elasticsearch
----------------------------------

Defines functions to build graph indices and upload them to
Elasticsearch

"""

import os
import sys
import re
import json
import datetime

from cdisutils.log import get_logger
from datadog import statsd
from elasticsearch import NotFoundError, Elasticsearch
from elasticsearch.exceptions import AuthorizationException
from gdcdatamodel.models import File
from progressbar import ProgressBar, Percentage, Bar, ETA
from psqlgraph import PsqlGraphDriver

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
        self.converter_class_name = converter_class.__class__.__name__

    def go(self, roll_alias=True, delete_nodes=True, skip_build=False):
        self.log.info("Caching database")
        # having a transation out here is important, since it ensures
        # that the cached database and which nodes get deleted is
        # consistent
        with self.graph.session_scope() as session:
            if not skip_build:
                self.converter.cache_database()
            self.log.info("Querying for old nodes to delete")
            to_delete = self.graph.nodes().sysan({"to_delete": True}).all()
            to_delete = [n.node_id for n in to_delete if not shouldnt_delete(n)]
            self.log.info("Found %s to_delete nodes, saving for later",
                          len(to_delete))
            self.log.info(to_delete)
        
        if not skip_build:
            self.log.info("Denormalizing database into JSON docs")
            case_docs, file_docs, ann_docs, project_docs = self.converter.denormalize_all()
            self.log.info("%s case docs, %s file docs, %s annotation docs, %s project docs",
                          len(case_docs),
                          len(file_docs),
                          len(ann_docs),
                          len(project_docs))
            self.log.info("Validating docs produced")
            self.converter.validate_docs(case_docs, file_docs, ann_docs, project_docs)
            self.log.info("Deploying new ES index with new docs and bumping alias")
            new_index = self.deploy(case_docs, file_docs, ann_docs, project_docs,
                                    roll_alias=roll_alias)
        self.delete_nodes(to_delete=to_delete,
                          delete_nodes=delete_nodes)
        if not skip_build:
            statsd.event(
                "esbuild finished",
                "successfully built index {}".format(new_index),
                source_type_name="esbuild",
                alert_type="success",
                tags=["es_index:{}".format(new_index)],
            )

    def delete_nodes(self, to_delete=[], delete_nodes=True):
        if delete_nodes == True:
            with self.graph.session_scope() as session:
                for expired_node in to_delete:
                    #node = self.graph.nodes(expired_node.__class__)\
                    #                 .ids(expired_node)\
                    #                 .scalar()
                    node = self.graph.nodes().get(expired_node)
                    if node:
                        if 'to_delete' in node.sysan:
                            if node.sysan['to_delete']:
                                self.log.info("Deleting %s", node)
                                session.delete(node)
        else:
            deleted_file_name = '{}/{}-{}.json'.format(os.path.expanduser('~'),
                                                       'esbuild',
                                                       datetime.datetime.now().isoformat())
            self.log.info("Skipping deletion of nodes, saving them to log file {}"
                          .format(deleted_file_name))
            with open(deleted_file_name, 'w') as json_file:
                for entry in to_delete:
                    json_file.write(entry + '\n')

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

    def bulk_upload(self, index, doc_type, docs, batch_size=BATCH_SIZE):
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

        def body():
            """Alternatingly yield instruction/doc, instruction/doc..."""

            start = pbar.currval
            for doc in docs[start:start+batch_size]:
                instruction = dict(
                    index=dict(
                        _index=index,
                        _type=doc_type,
                        _id=doc[doc_type+'_id'],
                    )
                )
                yield instruction
                yield doc

                pbar.update(pbar.currval+1)

        while pbar.currval < len(docs):
            res = self.es.bulk(body=body())
            if res['errors']:
                raise RuntimeError(json.dumps([
                    doc for doc in res['items']
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
                       batch_size=BATCH_SIZE):
        self.bulk_upload(index, 'project', project_docs, batch_size)
        self.bulk_upload(index, 'annotation', ann_docs, batch_size)
        self.bulk_upload(index, 'case', case_docs, batch_size)
        self.bulk_upload(index, 'file', file_docs, batch_size)

    def index_create_and_populate(self, index, case_docs=[],
                                  file_docs=[], ann_docs=[], project_docs=[],
                                  batch_size=BATCH_SIZE):
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

        index_settings = self.converter.mapper.index_settings()
        self.es.indices.create(index=index, body=index_settings)
        self.put_mappings(index)
        if not case_docs:
            self.log.warning("There were no case docs passed to populate with!")
        if not project_docs:
            self.log.warning("There were no case docs passed to populate with!")
        self.index_populate(index, case_docs, file_docs, ann_docs,
                            project_docs, batch_size)

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

        return (
            # Closed indices
            self.es.cluster.state()['blocks'].get('indices', {}).keys()
            # Open indices
            + self.es.indices.stats()['indices'].keys()
        )


    def get_index_numbers(self):
        """Return the numbers of the current set of indices. So concretely if we
        have gdc_from_graph_23, gdc_from_graph_24, and
        gdc_from_graph_25, this will return [23, 24, 25].
        """
        indices = set(self.get_indices())
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

    def cleanup_old_indices(self, kept):
        self.log.info("Deleting old indices")
        numbers = self.get_index_numbers()
        indices = [INDEX_PATTERN.format(base=self.index_base, n=n)
                     for n in numbers]
        if len(numbers) <= 5:
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
                except AuthorizationException as e:
                    # authorization exception will be raised if it's already closed
                    if "IndexClosedException" in e.error:
                        self.log.info("%s is already closed" % index)
                        continue
                    else:
                        self.log.exception("Fail to flush %s" % index)
                except:
                    self.log.exception("Can't flush index %s" % index)
                try:
                    self.es.indices.close(index=index)
                except:
                    self.log.error("Can't close index %s" % index)


    def deploy(self, case_docs, file_docs, ann_docs,
               project_docs, roll_alias=True,
               batch_size=BATCH_SIZE):
        """Create a new index with an incremented name based on
        self.index_base, populate it with :func
        index_create_and_populate:, atomically switch the alias to
        point to the new index, and delete anything older than the
        last 5 versions of this index.

        """
        current_numbers = self.get_index_numbers()
        self.log.info("Currently deployed indices are %s", current_numbers)
        if not current_numbers:
            n = 1
        else:
            n = max(current_numbers)+1
        new_index = INDEX_PATTERN.format(base=self.index_base, n=n)
        self.log.info("Deploying to index %s", new_index)
        self.index_create_and_populate(new_index, case_docs,
                                       file_docs, ann_docs,
                                       project_docs, batch_size)
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
                assert old_index.startswith(self.index_base)
                self.swap_index(old_index, new_index)
            else:
                self.es.indices.put_alias(index=new_index, name=self.index_base)
            self.cleanup_old_indices([old_index, new_index])
        else:
            self.log.info("Skipping alias roll / old index deletion")
        return new_index
