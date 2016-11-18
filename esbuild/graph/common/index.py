# -*- coding: utf-8 -*-
"""
esbuild.graph.common.index
----------------------------------

Defines :class:`GraphIndex` represents a GDC Data Portal index

"""

import abc
import cdisutils
import json
import logging
import os
import shutil
import time


logger = cdisutils.log.get_logger(__name__)
logger.setLevel(logging.INFO)


def create_file(path, contents):
    """Writes contents to path if file doesn't exist, else raise
    AssertionError

    """

    if os.path.exists(path):
        raise AssertionError('File {} already exists'.format(path))

    with open(path, 'w') as outfile:
        outfile.write(contents)


def write_file(path, contents):
    """Writes contents to path if file"""

    with open(path, 'w') as outfile:
        outfile.write(contents)


def read_json_file(path):
    """Writes contents to path if file doesn't exist, else raise
    AssertionError

    """

    if not os.path.exists(path):
        raise AssertionError('File {} does not exist'.format(path))

    with open(path, 'r') as infile:
        return json.loads(infile.read())


def read_dir_json_files(path):
    """Reads all files as json from directory"""

    for (dirpath, _, filenames) in os.walk(path):
        for filename in filenames:
            yield read_json_file(os.path.join(dirpath, filename))

        return  # only walk the first level


def merge_file_doc(existing_file_doc, file_doc):
    """Merges the file doc into the existing file doc"""

    existing_case_subdocs = {
        case_doc['case_id']: case_doc
        for case_doc in existing_file_doc['cases']
    }

    this_case_subdocs = {
        case_doc['case_id']: case_doc
        for case_doc in file_doc['cases']
    }

    all_case_subdocs = dict(existing_case_subdocs, **this_case_subdocs)
    existing_file_doc['cases'] = all_case_subdocs

    return existing_file_doc


class GraphIndex(object):
    """Base class to represent a complete or in progress index"""

    __metaclass__ = abc.ABCMeta

    @abc.abstractmethod
    def __iter__(self):
        """Iterate over the index (for backwards compatible unpacking)"""

        raise NotImplementedError

    @abc.abstractmethod
    def case_doc_count(self):
        """Returns the number of existing case docs"""

        raise NotImplementedError

    @abc.abstractmethod
    def add_case_doc(self, case_doc):
        """Adds a case document to this index"""

        raise NotImplementedError

    @abc.abstractmethod
    def add_file_doc(self, file_doc):
        """Adds a file document to this index"""

        raise NotImplementedError

    @abc.abstractmethod
    def add_annotation_doc(self, annotation_doc):
        """Adds a annotation document to this index"""

        raise NotImplementedError

    @abc.abstractmethod
    def add_project_doc(self, case_doc):
        """Adds a case document to this index"""

        raise NotImplementedError


class MemoryGraphIndex(GraphIndex):
    """Class to represent a complete or in progress index on memory"""

    def __init__(self):
        """Index constructor"""

        logger.info('Creating new %s', self)

        self._case_docs = {}
        self._file_docs = {}
        self._annotation_docs = {}
        self._project_docs = {}

    def __iter__(self):
        """Iterate over the index (for backwards compatible unpacking)"""

        return iter((
            self._case_docs.itervalues(),
            self._file_docs.itervalues(),
            self._annotation_docs.itervalues(),
            self._project_docs.itervalues(),
        ))

    def add_case_doc(self, case_doc):
        """Adds a case document to this index"""

        case_id = case_doc['case_id']
        self._case_docs[case_id] = case_doc

    def add_file_doc(self, file_doc):
        """Adds a file document to this index"""

        file_id = file_doc['file_id']

        if file_id not in self._file_docs:
            self._file_docs[file_id] = file_doc

        else:
            self._file_docs[file_id] = merge_file_doc(
                self._file_docs[file_id], file_doc)

    def add_annotation_doc(self, annotation_doc):
        """Adds a annotation document to this index"""

        annotation_id = annotation_doc['annotation_id']
        self._annotation_docs.setdefault(annotation_id, annotation_doc)

    def add_project_doc(self, project_doc):
        """Adds a project document to this index"""

        project_id = project_doc['project_id']
        self._project_docs[project_id] = project_doc

    def case_doc_count(self):
        """Returns the number of existing case docs"""

        return len(self._case_docs)


class DiskGraphIndex(GraphIndex):
    """Class to represent a complete or in progress index on memory"""


    def __init__(self, data_dir_base=None):
        """Index constructor"""

        rel_data_dir = '{}_{}'.format(data_dir_base, int(time.time()))
        self.data_dir = os.path.abspath(os.path.expanduser(rel_data_dir))
        self.case_dir = os.path.join(self.data_dir, 'cases')
        self.file_dir = os.path.join(self.data_dir, 'files')
        self.annotation_dir = os.path.join(self.data_dir, 'annotations')
        self.project_dir = os.path.join(self.data_dir, 'projects')

        self._seen_case_ids = set()
        self._seen_file_ids = set()

        logger.info('Creating new %s', self)

        self.create_data_dir()

    def __repr__(self):
        return "<{}('{}')>".format(self.__class__.__name__, self.data_dir)


    def __iter__(self):
        """Iterate over the index (for backwards compatible unpacking)"""

        return iter((
            read_dir_json_files(self.case_dir),
            read_dir_json_files(self.file_dir),
            read_dir_json_files(self.annotation_dir),
            read_dir_json_files(self.project_dir),
        ))

    def delete(self):
        """Deletes the entire data_dir"""

        logger.info('Deleting %s', self)
        shutil.rmtree(self.data_dir)

    def create_data_dir(self):
        """Create directory to build index to disk"""

        if not os.path.exists(self.data_dir):
            os.makedirs(self.data_dir)

        if not os.path.exists(self.case_dir):
            os.makedirs(self.case_dir)

        if not os.path.exists(self.file_dir):
            os.makedirs(self.file_dir)

        if not os.path.exists(self.annotation_dir):
            os.makedirs(self.annotation_dir)

        if not os.path.exists(self.project_dir):
            os.makedirs(self.project_dir)

    def add_case_doc(self, case_doc):
        """Adds a case document to this index"""

        case_id = case_doc['case_id']
        path = os.path.join(self.case_dir, case_id)
        self._seen_case_ids.add(case_id)

        create_file(path, json.dumps(case_doc))

    def add_file_doc(self, file_doc):
        """Adds a file document to this index"""

        try:
            file_id = file_doc['file_id']
            path = os.path.join(self.file_dir, file_id)

            if file_id not in self._seen_file_ids:
                return create_file(path, json.dumps(file_doc))

            existing_file_doc = read_json_file(path)

            updated_file_doc = merge_file_doc(existing_file_doc, file_doc)
            write_file(path, json.dumps(updated_file_doc))

        except Exception as e:
            print str(e)
        finally:
            self._seen_file_ids.add(file_id)


    def add_annotation_doc(self, annotation_doc):
        """Adds a annotation document to this index"""

        annotation_id = annotation_doc['annotation_id']
        path = os.path.join(self.annotation_dir, annotation_id)

        if not os.path.exists(path):
            create_file(path, json.dumps(annotation_doc))

    def add_project_doc(self, project_doc):
        """Adds a project document to this index"""

        project_id = project_doc['project_id']
        path = os.path.join(self.project_dir, project_id)

        create_file(path, json.dumps(project_doc))

    def case_doc_count(self):
        """Returns the number of existing case docs"""

        return len(self._seen_case_ids)
