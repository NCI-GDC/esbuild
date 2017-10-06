import os
import time
import pytest
from elasticsearch import Elasticsearch

import es_data
from esbuild.utils import ReleaseHelper


def test_get_projects_list(test_index):
    es, index_name, _, _ = test_index
    helper = ReleaseHelper(es)

    projects = {d['project_id'] for d in es_data.project_docs}

    assert projects == helper.get_project_ids(index_name)
    assert projects == helper.get_project_ids_from_metadata(index_name)


@pytest.fixture(scope='module')
def es_after_deletion(test_index):
    """
    Deletes some projects from the index but not updates the metadata,
    leaving build_metadata inconsistent purposefully
    """
    es, index_name, _, _ = test_index
    helper = ReleaseHelper(es)

    # Will delete these projects' data
    projects_to_delete = [u"TCGA-STAD", u"FM-AD"]

    # Get project list before deletion
    projects_before = helper.get_project_ids(index_name)

    # Delete documents associated with selected projects from index
    helper.delete_docs_from_index(index_name, projects_to_delete)

    # Wait for index to update
    time.sleep(2)
    return es, index_name, projects_before, projects_to_delete


def test_projects_deleted(es_after_deletion):
    es, index_name, projects_before, deleted_projects = es_after_deletion
    helper = ReleaseHelper(es)
    expected_projects = {p for p in projects_before
                         if p not in deleted_projects}
    assert helper.get_project_ids(index_name) == expected_projects


def test_delete_project_docs(es_after_deletion):
    """ Check that correct docs are deleted """
    es, index_name, _, deleted_projects = es_after_deletion

    path_to_id = {'project': 'project_id',
                  'case': 'project.project_id',
                  'file': 'cases.project.project_id',
                  'annotation': 'project.project_id'}

    # Check files
    projects = set()
    file_data = es.search(index=index_name, doc_type='file', size=10000)['hits']['hits']
    for f in file_data:
        projects.update([c['project']['project_id'] for c in f['_source']['cases']])
    assert {p for p in projects if p in deleted_projects} == set()

    # Check everything else
    def get_value_at_path(tree, path):
        if len(path) == 1:
            return tree[path[0]]
        for step in path:
            return get_value_at_path(tree[path[0]], path[1:])

    for dtype, path in path_to_id.items():
        if dtype == 'file':
            continue
        data = es.search(index=index_name, doc_type=dtype, size=10000)['hits']['hits']
        projects = set()
        for doc in data:
            project_id = get_value_at_path(doc['_source'], path.split('.'))
            projects.update(project_id)
        assert {x for x in projects if x in deleted_projects} == set()


def test_update_metadata(es_after_deletion):
    es, index_name, projects_before, deleted_projects = es_after_deletion
    helper = ReleaseHelper(es)

    helper.update_metadata(index_name)
    time.sleep(2)

    projects_after = helper.get_project_ids(index_name)

    # Check that metadata is adjusted correctly
    assert projects_after | set(deleted_projects) == projects_before
    for project in deleted_projects:
        assert project in projects_before
        assert project not in projects_after