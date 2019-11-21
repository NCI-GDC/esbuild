import os
import subprocess
import time
from collections import deque
from hashlib import md5
from itertools import chain
from reprlib import repr
from sys import getsizeof

import six
from cdislogging import get_logger
from dotenv import load_dotenv
from gdcdatamodel import models
from gdcdatamodel.models.submission import TransactionSnapshot
from indexclient.client import IndexClient
from psqlgraph import PsqlGraphDriver
from requests import HTTPError

from esbuild.graph.common.builder import GraphIndexBuilder


def get_file_state(doc):
    state = None
    for url, meta in doc.urls_metadata.items():
        if meta.get('type') == GraphIndexBuilder.INDEXD_URL_TYPE:
            state = state or meta.get('state')
    return state


INDEXD_METADATA_FIELDS = GraphIndexBuilder.data_file_indexd_fields + ['file_id']
INDEXD_METADATA_VALUE_GETTERS = {
    'file_id': lambda doc: doc.did,
    'md5sum': lambda doc: doc.hashes['md5'],
    'file_size': lambda doc: doc.size,
    'file_state': get_file_state,
}

load_dotenv()


def get_default_pg_driver():
    return PsqlGraphDriver(
        user=os.getenv('PG_USER'),
        host=os.getenv('PG_HOST'),
        password=os.getenv('PG_PASS'),
        database=os.getenv('PG_NAME'),
    )


def get_default_index_client():
    return IndexClient(
        baseurl=os.getenv('INDEXD_HOST'),
        auth=(os.getenv('INDEXD_USER'), os.getenv('INDEXD_PASS')),
    )


def get_total_size(obj, handlers={}):
    """ Returns the memory used (in bytes) of an object and all of its
        nested objects. Handlers for special objects can be passed in
        as long as they provide an iterator to loop over themselves.
    """
    dict_handler = lambda d: chain.from_iterable(d.items())
    all_handlers = {tuple: iter,
                    list: iter,
                    deque: iter,
                    dict: dict_handler,
                    set: iter,
                    frozenset: iter,
                   }
    all_handlers.update(handlers)
    seen_objs = set()

    def sizeof(obj):
        size = 0
        if id(obj) not in seen_objs:
            seen_objs.add(id(obj))
            size = getsizeof(obj, 0)
            for type_name, handler in all_handlers.items():
                if isinstance(obj, type_name):
                    size += sum(map(sizeof, handler(obj)))
                    break
        return size

    return sizeof(obj)


# TODO: Refactor esbuild.graph.common.builder to use this method to extract IndexD properties
def extract_indexd_metadata(doc, fields=None, getters=None):
    if fields is None:
        fields = INDEXD_METADATA_FIELDS
    if getters is None:
        getters = INDEXD_METADATA_VALUE_GETTERS

    metadata = {}
    for field in fields:
        if hasattr(doc, field):
            metadata[field] = getattr(doc, field)
        else:
            getter = getters[field]
            metadata[field] = getter(doc)
    return metadata


class VersionedNodesDiffCollector(object):
    TARGET_NODE_STATES = ['validated', 'submitted']

    def __init__(self, project_ids=None, graph=None, indexd_client=None):
        if isinstance(project_ids, six.text_type):
            self.project_ids = project_ids.split(',')
        elif isinstance(project_ids, list):
            self.project_ids = project_ids
        else:
            self.project_ids = project_ids

        self.g = graph or get_default_pg_driver()
        self.i = indexd_client or get_default_index_client()
        self.diffs = {}
        self.logger = get_logger(__name__ + '.' + self.__class__.__name__)

    def query_nodes(self):
        with self.g.session_scope():
            q = self.g.nodes() \
                .prop_in('state', self.TARGET_NODE_STATES) \
                .filter(models.Node._props.has_key('file_name'))

            if self.project_ids and isinstance(self.project_ids, list):
                q = q.prop_in('project_id', self.project_ids)

            nodes = q.yield_per(1000).enable_eagerloads(False)
            for n in nodes:
                yield n

    def iter_nodes(self, strategy='query'):
        if strategy == 'query':
            return self.query_nodes()
        else:
            raise NotImplementedError(
                "Node loading strategy '{}' is not implemented".format(strategy)
            )

    def get_props_from_snapshot(self, node_id, action):
        with self.g.session_scope():
            ts = self.g.nodes(TransactionSnapshot).filter(
                TransactionSnapshot.id == node_id,
                TransactionSnapshot.action == action,
            ).order_by(TransactionSnapshot.transaction_id.desc()).first()

            if not ts:
                return {}

            old = ts.old_props
            new = ts.new_props

            diff = {}
            for key, value in old.items():
                if new.get(key) != value:
                    diff[key] = value
            return diff

    def get_props_from_indexd(self, versions, latest_id):
        # get only unreleased files
        unreleased_all = [
            v for v in versions
            if not (v.version and v.metadata.get('release_number'))
        ]

        if len(unreleased_all) > 1:
            if len([v for v in unreleased_all if v.did == latest_id]) < 1:
                raise ValueError("No unreleased document found")

            extra = [v for v in unreleased_all if v.did != latest_id]

            for e in extra:
                self.logger.debug(
                    "Extra unreleased IndexD doc: '{}'".format(e.did)
                )

        # Get latest released
        released = sorted([v for v in versions
                           if v.version and v.metadata.get('release_number')],
                          key=lambda x: int(x.version))[-1]

        # Get primary url ('type' should be 'cleversafe')
        primary_urls = {url: meta
                        for url, meta in released.urls_metadata.items()
                        if meta.get('type') == 'cleversafe'}

        if len(primary_urls) > 1:
            raise ValueError("Multiple primary urls for doc")

        _, meta = primary_urls.popitem()

        old_props = {
            'file_state': meta['state'],
        }

        indexd_meta = extract_indexd_metadata(released)

        old_props.update(indexd_meta)

        return old_props

    def list_versions(self, node):
        for _ in range(5):
            try:
                versions = self.i.list_versions(node.node_id)
            except HTTPError as e:
                if e.response and e.response.status_code != 404:
                    self.logger.error("Error while making request to IndexD: {}. Retrying".format(str(e)))
                    time.sleep(5)
                    continue
                # Return an empty list if record doesn't exist
                return []
            return versions

        self.logger.debug("IndexD is being weird with: {} '{}'".format(
            node.project_id, node))
        # Return an empty list if unable to query IndexD
        return []

    def get_old_props(self, node):
        """
        Given a Node, collect old properties from TransactionSnapshot and IndexD
        """
        # Lookup TransactionSnapshot with 'version' action
        transaction_props = self.get_props_from_snapshot(node.node_id,
                                                         'version')

        # This will mean that the given node never created a new file version
        if not transaction_props:
            return {}

        versions = self.list_versions(node)
        if len(versions) <= 1:
            # Latest version isn't released or IndexD didn't return anything,
            # so no older version to look for
            return {}

        # Lookup differences in IndexD
        indexd_props = self.get_props_from_indexd(versions, node.node_id)

        # Prioritize IndexD metadata over Graph metadata
        transaction_props.update(indexd_props)

        return transaction_props

    def run(self):
        return self.collect_differences()

    def collect_differences(self):
        for node in self.iter_nodes():
            node_diff = self.get_old_props(node)
            if node_diff:
                self.diffs[node.node_id] = node_diff
                self.logger.debug("Found old version of: {} '{}'".format(
                    node.project_id, node))
        return self.diffs


class ReleaseHelper:
    """
    Prepares previously stored index to be used in a next data release
    """

    def __init__(self, es):
        """
        Usage:
            - initialize the helper
            - run .prepare_index_to_build()
        """
        self.es = es
        self.log = get_logger('utils_releasehelper')

    def prepare_index_to_build(self, index_name, projects_to_build):
        """
        Prepares index :index_name to be populated with :projects_to_build
        i.e. removes documents associated with :projects_to_build from :index_name
        """

        # If index does not exist, do nothing
        if index_name not in self.es.indices.get_alias():
            return

        # If index does exist, but it's empty, do nothing
        if len(self.get_project_ids(index_name)) == 0:
            return

        # Remove data associated with projects that are to be build from index
        self.delete_docs_from_index(index_name, projects_to_build)

        # Update build_metadata
        self.update_metadata(index_name)

    def get_project_ids(self, index_name):
        """
        Returns set of projects based on project documents in index
        """
        query = {
            "query": {},
            "stored_fields": "_id"
        }
        res = self.es.search(index=index_name, doc_type='project',
                             size=10000, body=query)['hits']['hits']
        if res:
            projects = set([project['_id'] for project in res])
        else:
            # Existing index did not contain any project docs
            projects = set()
        return projects

    def get_project_ids_from_metadata(self, index_name):
        """
        Returns set of projects based on build_metadata
        """

        res = self.es.search(index=index_name, doc_type='build_metadata',
                             size=10000)['hits']['hits']
        projects = set()
        for doc in res:
            projects.update(set(doc['_source']['build_projects']))
        return projects

    def delete_docs_from_index(self, index_name, projects_to_delete):
        """
        Removes ebsuild docs associated with selected projects from the index
        """
        for doc_type in ['case', 'file', 'project', 'annotation']:
            path_to_id = {'project': 'project_id',
                          'case': 'project.project_id',
                          'file': 'cases.project.project_id',
                          'annotation': 'project.project_id'}
            for project in projects_to_delete:
                if doc_type == 'file':
                    query = {
                        "query": {
                            "nested": {
                                "path": "cases",
                                "query": {
                                    "bool": {
                                        "must": [
                                            {"match_phrase": {"cases.project.project_id": project}},
                                        ]
                                    }
                                }
                            }
                        }
                    }
                else:
                    query = {
                        "query": {
                            "match_phrase": {
                                path_to_id[doc_type]: project
                            }
                        }
                    }
                try:
                    self.es.delete_by_query(index=index_name,
                                            doc_type=doc_type, body=query)
                except Exception as exception:
                    self.log.exception('Unable to delete {} from {}, skipping'.format(
                        doc_type, index_name))

    def update_metadata(self, index_name):
        """
        Updates build_metadata doc after projects deletion
        """
        # Get new project list
        projects_after = self.get_project_ids(index_name)

        # Get new counts
        counts = self.get_index_counts(index_name)

        # Get commit hash
        commit_hash = self.get_commit_hash()

        # Update the metadata
        metadata_after = {'build_projects': list(projects_after),
                          'commit_hash': commit_hash,
                          'counts': counts}
        self.es.delete_by_query(index=index_name,
                                doc_type='build_metadata', body={})

        build_metadata_id = self.get_build_metadata_id(projects_after)
        self.es.create(index=index_name, id=build_metadata_id,
                       doc_type='build_metadata', body=metadata_after)
        self.wait_for_es(index_name, 'build_metadata')

    def get_index_counts(self, index_name):
        counts = {}
        for dtype in ['case', 'file', 'project', 'annotation']:
            counts[dtype] = self.es.count(index=index_name, doc_type=dtype)['count']
        return counts

    def wait_for_es(self, index_name, doc_type, query={}, max_wait_sec=30):
        """
        Wait for query to return non empty result
        """
        time_slept = 0
        while not self.es.search(index=index_name, doc_type=doc_type, body=query)['hits']['hits']:
            time.sleep(1)
            time_slept += 1
            if time_slept > max_wait_sec:
                break

    @staticmethod
    def get_commit_hash():
        git_dir = os.path.join(
            os.path.dirname(
                os.path.dirname(
                    os.path.realpath(__file__))), '.git')
        try:
            commit_hash = subprocess.check_output(['git',
                                                   '--git-dir={}'.format(git_dir),
                                                   'rev-parse', 'HEAD'])
        except Exception as err:
            commit_hash = 'unable to parse commit hash: {}'.format(repr(err))

        return commit_hash.decode('utf-8')

    @staticmethod
    def get_build_metadata_id(project_ids):
        if not isinstance(project_ids, list):
            project_ids = [str(project_ids)]

        project_ids_sorted = sorted(project_ids)
        md5hash = md5(','.join(project_ids_sorted))

        return md5hash.hexdigest()
