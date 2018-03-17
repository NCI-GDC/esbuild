import time
import pytest

import es_data
from data import DATA_FILE_INDEXD_FIELDS
from esbuild.utils import ReleaseHelper


def test_get_projects_list(test_index_data):
    es, index_name = test_index_data
    helper = ReleaseHelper(es)

    projects = {d['project_id'] for d in es_data.project_docs}

    assert projects == helper.get_project_ids(index_name)
    assert projects == helper.get_project_ids_from_metadata(index_name)


def validate_file_metadata(key, value):
    """
    Errors if file metadata key is taken from graph instead of indexd (has erroneous value)
    """
    if key == 'analysis':
        # Look deeper into .input_files
        input_files = value.get('input_files', [])
        for subkey in input_files:
            validate_file_metadata(subkey, input_files)
        return

    if key in ['index_files', 'metadata_files']:
        # Check inside special files arrays
        for subkey in value:
            validate_file_metadata(subkey, value)
        return

    if key == 'downstream_analyses':
        # Look deeper into .output_files
        for analysis in value:
            output_files = analysis.get('output_files', [])
            for subkey in output_files:
                validate_file_metadata(subkey, output_files)
        return

    if key in DATA_FILE_INDEXD_FIELDS:
        error_msg = '"{}" is loaded from graph instead of indexd'.format(key)
        if isinstance(value, basestring):
            assert value != 'error', error_msg
        elif isinstance(value, list):
            assert 'error' not in value
        elif isinstance(value, int):
            assert value != -1, error_msg
        else:
            raise Exception('Can not process file metadata key of type {}: {}={}'
                            .format(type(value), key, value))


def get_dict_paths(d, path_list=None, path='root'):
    """
    Returns list of all paths in a dict and a last path found
    """
    if path_list is None:
        path_list = []

    for k, v in d.iteritems():
        subpath = path + '.' + k
        if isinstance(v, dict):
            sublist, subpath = get_dict_paths(v, path_list, subpath)
        else:
            if isinstance(v, list):
                sublist = [path + '.' + k + '.' + str(e) for e in v]
            else:
                sublist = [path + '.' + k + '.' + str(v)]
        path_list.extend(sublist)
    return list(set(path_list)), path


@pytest.fixture(scope='module')
def es_after_deletion(test_index_data):
    """
    Deletes some projects from the index but not updates the metadata,
    leaving build_metadata inconsistent purposefully
    """
    es, index_name = test_index_data
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

    projects_after = helper.get_project_ids_from_metadata(index_name)

    # Check that metadata is adjusted correctly
    assert projects_after | set(deleted_projects) == projects_before
    for project in deleted_projects:
        assert project in projects_before
        assert project not in projects_after