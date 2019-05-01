import time
import os
from sys import getsizeof
from itertools import chain
from collections import deque
try:
    from reprlib import repr
except ImportError:
    pass
import subprocess

from elasticsearch import Elasticsearch
from cdisutils.log import get_logger

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
                        self.log.warn('Unable to delete {} from {}, skipping'.format(
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

        self.es.create(index=index_name, id=','.join(projects_after),
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
        git_dir = os.path.join(os.path.dirname(
                                os.path.dirname(
                                  os.path.realpath(__file__))), '.git')
        try:
            commit_hash = subprocess.check_output(['git',
                                                   '--git-dir={}'.format(git_dir),
                                                   'rev-parse', 'HEAD'])
        except Exception as err:
            commit_hash = 'unable to parse commit hash: {}'.format(repr(err))

        return commit_hash
