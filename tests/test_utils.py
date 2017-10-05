import os
import time
import pytest
from elasticsearch import Elasticsearch

from esbuild.utils import ReleaseHelper


def test_get_projects_list(test_index):
    es, index_name, _, _ = test_index
    helper = ReleaseHelper(es)

    projects = {u'TCGA-DLBC',
                u'TCGA-PRAD',
                u'TARGET-OS',
                u'TARGET-RT',
                u'TCGA-STAD',
                u'TARGET-NBL',
                u'FM-AD',
                u'TCGA-THYM'}

    assert projects == helper.get_build_projects(index_name)


@pytest.fixture(scope='module')
def es_after_deletion(test_index):
    es, index_name, _, _ = test_index
    helper = ReleaseHelper(es)

    # Will delete these projects' data
    projects_to_delete = [u"TCGA-STAD", u"FM-AD"]

    # Get project list before deletion
    projects_before = helper.get_build_projects(index_name)

    # Delete documents associated with selected projects from index
    helper.delete_docs_from_index(index_name, projects_to_delete)
    
    # Update build_metadata
    helper.update_metadata(index_name, projects_to_delete)

    # Wait for index to update
    time.sleep(2)

    # Get project list after deletion
    projects_after = helper.get_build_projects(index_name)

    return es, index_name, projects_before, projects_after, projects_to_delete


def test_delete_project_docs(es_after_deletion):
    es, index_name, _, _, deleted_projects = es_after_deletion

    # Check that correct docs are deleted
    path_to_id = {'project': 'project_id',
                  'case': 'project.project_id',
                  'file': 'cases.project.project_id',
                  'annotation': 'project.project_id'}
    for dtype, path in path_to_id.items():
        query = {
            "query": {
                "terms": {
                    path: deleted_projects
                }
            }
        }
        assert es.count(index=index_name, doc_type=dtype, body=query)['count'] == 0


def test_update_metadata(es_after_deletion):
    es, index_name, projects_before, projects_after, deleted_projects = es_after_deletion

    # Check that metadata is adjusted correctly
    assert projects_after | set(deleted_projects) == projects_before
    for project in deleted_projects:
        assert project in projects_before
        assert project not in projects_after