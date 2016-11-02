# -*- coding: utf-8 -*-

import glob
import json
import os
import shutil
import tarfile
import time

class DocTypes():
    def __init__(self):
        self.case       = 'case_docs'
        self.file       = 'file_docs'
        self.annotation = 'annotation_docs'
        self.project    = 'project_docs'

        # used for iterating
        # this is the exact order that converter.denoramlize_all() unpacks it
        # keep in mind order matters in iteration
        self.all_types = [self.case, self.file, self.annotation, self.project]

        # easy way to reference the ID field type in each doc json blob
        self.id = {
                self.case:       'case_id',
                self.file:       'file_id',
                self.annotation: 'annotation_id',
                self.project:    'project_id',
        }


class GDCDiskIO():
    def __init__(self, file_directory, builder_type):
        '''
            str: file_directory
            str: builder_type = 'active' or 'legacy' used in
                determining the archive name

            class for handling disk operations so that the docs
            can be uploaded elsewhere like ES or S3 afterward

            high level overview of the file structure:
            gdc-doc-archive-active-123456678.90.tar.gz/
            |        ./case_docs
            |        |        1111-1111-1111-1111
            |        |        2222-2222-2222-2222
            |        |        3333-3333-3333-3333
            ...
            |        ./annotation_docs
            ...
        '''

        self.builder_type = builder_type
        # this will be where the archive is stored
        self.file_directory = file_directory
        if not self.file_directory.endswith('/'):
            self.file_directory += '/'

        if not os.path.exists(self.file_directory):
            os.mkdir(self.file_directory)

        self.archive_name_scheme = 'gdc-doc-archive'
        self.archive_name = None

        # keep reference of this filename
        self.full_path_to_archive = None

        # treating this like a struct
        self.types = DocTypes()


    def _generate_archive_name(self):
        '''
            naming scheme should look like gdc-doc-archive-{{timestamp}}.tar.gz

            tar puts everything into one file
            gzip compresses that one file

            eg
            gdc-doc-archive-active-123456678.90.tar.gz/

        '''
        self.archive_name = '{}-{}-{}.tar.gz'.format(self.archive_name_scheme,
                self.builder_type, str(time.time()))
        self.full_path_to_archive = self.file_directory + self.archive_name


    def save_doctype(self, docs, doc_type):
        '''
            list[dict]: doc (list of json objects)
            str: doc_type

            save copy of the docs on disk first to be used
            in uploading to elasticsearch and s3

            large list of all {case,file,annotation,project}_doc into this function
            write each element of the list into it's own separate file
            named by index of the list

        '''

        # might be a string or json blob (dict) depending on where it's coming from
        full_path = self.file_directory + doc_type + '/'
        if not os.path.exists(full_path):
            os.mkdir(full_path)

        for doc_index, doc in enumerate(docs):

            # this will get the doc ID associated with each type
            doc_file_name = full_path + docs[doc_index][self.types.id[doc_type]]

            with open(doc_file_name, 'w') as f:
                f.write(json.dumps(doc))

        return full_path

    def write_archive(self):
        '''
            uses the name generator to save a tar.gz archive
            containing folders for each doctype

            tarfile will attempt to store the full path given when writing
            to an archive

            ie the entirety of the tempfile.mkdtemp() path
            will be stored in your local directory
        '''

        # go to the directory, to avoid saving the full path in the archive
        cwd = os.getcwd()
        os.chdir(self.file_directory)

        self._generate_archive_name()

        # use colon if you don't need to do file seek ops
        with tarfile.open(self.archive_name, 'w:gz') as t:
            for d in self.types.all_types:
                t.add(d)

                # delete the folders after everything is archived
                shutil.rmtree(d)

        os.chdir(cwd)

    def _get_files_in_dir(self):
        '''
            get all the archived doc files in the directory

            then order them, from oldest to newest

            this will make deleting the old ones easier by having
            them at them front of the list
        '''
        formatted_glob = '{}{}-{}-*.tar.gz'.format(self.file_directory,
                self.archive_name_scheme, self.builder_type)

        return sorted( glob.glob(formatted_glob) )


    def cleanup_old_indices(self):
        '''
            only want to keep the latest 5 full docs
            get all the files in the path and delete everything older
            than the last 5

            that means there will be 5 doc archives stored on disk at all times,
            so you can delete the last 5 after you've inserted the new 5.
            it currently uses the to_delete variable to determine which
            files to delete, but this needs to change to fit into the disksave idea

        '''

        for f in self._get_files_in_dir()[:-5]:
            os.remove(f)


    def read_archive(self, archive_name=None):
        '''
            this method takes an param because it should read archives that
            were previously made

            if you're not reading an older archive, read the one you just wrote

            return the same thing as .denormalize_all() returns
            e.g. a tuple of length 4, eaceh containing a list of
            docs for that doctype. the docs are a json object (dict)

            the archive_name will be the full path to the archive

            extract it in the current working directory, delete the files after
        '''

        #
        if archive_name is None and self.full_path_to_archive is not None:
            archive_name = self.full_path_to_archive

        # use a colon in 'r:gz' when you don't need to file seek
        with tarfile.open(archive_name, 'r:gz') as t:
            t.extractall()

        results = []
        # the folders are named after the doctype
        for i, folder_name in enumerate(self.types.all_types):

            results.append([])
            for filename in glob.glob(folder_name + '/*'):
                with open(filename, 'r') as f:
                    # order of this list will be dependant on the filename
                    # which creates a different ordering than denormalize_all()
                    results[i].append(json.loads(f.read()))

            # clean up the folders that got unpacked
            shutil.rmtree(folder_name)

        return tuple(results)


def documents_eq(a, b):
    '''
        a, b: tuple of doctypes, each containing a list of documents/json blobs
        When the docs are writen to disk, they become out of order compared
        to the denormalize_all() version because files are saved by ID name
        and are then read in a different order
    '''

    # case_doc, file_doc, ann_doc, project_doc => len 4
    if len(a) == 4 and len(a) != len(b):
        return False

    for i, _ in enumerate(a):
        if sorted(a[i]) != sorted(b[i]):
            return False

    return True

