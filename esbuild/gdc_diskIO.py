# -*- coding: utf-8 -*-

import glob
import json
import os
import shutil
import tarfile
import time

from cdisutils import md5sum
from cdisutils.log import get_logger


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
            gdc-indices-active-123456678.90.tar.gz/
            |        ./case_docs
            |        |        1111-1111-1111-1111
            |        |        2222-2222-2222-2222
            |        |        3333-3333-3333-3333
            ...
            |        ./annotation_docs
            ...
        '''

        self.log = get_logger('GDC_DiskIO')

        self.builder_type = builder_type
        # this will be where the archive is stored
        self.file_directory = file_directory
        if not self.file_directory.endswith('/'):
            self.file_directory += '/'

        if not os.path.exists(self.file_directory):
            os.mkdir(self.file_directory)

        self.archive_name_scheme = 'gdc-indices'
        self.archive_name = None

        # keep reference of this filename
        self.full_path_to_archive = None

        # treating this like a struct
        self.types = DocTypes()


    def _generate_archive_name(self):
        '''
            naming scheme should look like gdc-indices-{{timestamp}}.tar.gz

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

        full_path = self.file_directory + doc_type + '/'
        if not os.path.exists(full_path):
            self.log.info('Directory not found')
            self.log.info('Creating directory {}'.format(full_path))
            os.mkdir(full_path)
        else:
            self.log.info('Directory found. Using directory {}'.format(full_path))


        # would be too many to log
        for doc_index, doc in enumerate(docs):

            # this will get the doc ID associated with each type
            doc_file_name = full_path + docs[doc_index][self.types.id[doc_type]]

            with open(doc_file_name, 'w') as f:
                f.write(json.dumps(doc))

        self.log.info('{} successfully saved'.format(doc_type))
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
        self.log.info('Archive name: {}'.format(self.archive_name))

        # use colon if you don't need to do file seek ops
        with tarfile.open(self.archive_name, 'w:gz') as t:
            for d in self.types.all_types:
                self.log.info('Adding {} index to {}'.format(d, self.archive_name))
                t.add(d)

                # delete the folders after everything is archived
                shutil.rmtree(d)

        os.chdir(cwd)

    def _get_archives_in_dir(self):
        '''
            get all the archived doc files in the directory

            then order them, from oldest to newest

            this will make deleting the old ones easier by having
            them at them front of the list
        '''
        formatted_glob = '{}{}-{}-*.tar.gz'.format(self.file_directory,
                self.archive_name_scheme, self.builder_type)

        # glob does not do any sorting, but the files get loaded in
        # in the order they show up on disk
        # this is usually in sorted order by time, but I'm not taking chances
        return sorted(glob.glob(formatted_glob))


    def cleanup_old_archives(self):
        '''
            only want to keep the latest 5 full doc archives
            get all the files in the path and delete everything older
            than the last 5

            that means there will be 5 doc archives stored on disk at all times,
            for each active and legacy data

            so you can delete the last 5 after you've inserted the new 5.
            it currently uses the to_delete variable to determine which
            files to delete, but this needs to change to fit into the disksave idea

        '''

        for f in self._get_archives_in_dir()[:-5]:
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

        # we want to extract in the working directory chosen by SAVE_DIR env var
        cwd = os.getcwd()
        os.chdir(self.file_directory)

        if archive_name is None:
            archive_name = self.archive_name


        # use a colon in 'r:gz' when you don't need to file seek
        with tarfile.open(archive_name, 'r:gz') as t:
            self.log.info('Opening archive {}'.format(archive_name))
            t.extractall()

        results = []
        # the folders are named after the doctype
        for i, folder_name in enumerate(self.types.all_types):

            self.log.info('Reading files from [{}] into memory'.format(folder_name))

            # top level will hold indices
            results.append([])
            for filename in glob.glob(folder_name + '/*'):

                with open(filename, 'r') as f:
                    # order of this list will be dependant on the filenames
                    # which creates a different ordering than denormalize_all()
                    tmp = f.read()
                    json_tmp  = json.loads(tmp)
                    del tmp
                    results[i].append(json_tmp)
                    del json_tmp

            # clean up the folders that got unpacked
            self.log.info('Cleaning up leftover folders')
            shutil.rmtree(folder_name)

        os.chdir(cwd)
        return tuple(results)


    def indices_md5sum(self, indices):
        '''
            When the docs are writen to disk, they become out of order when
            compared to the denormalize_all() version because files are saved
            by ID name and are then read in a different order
        '''

        # sort the list of indices, AND the keys of the dictionaries inside those lists
        indices = [ json.dumps(sorted(index), sort_keys=True) for index in indices ]

        # one large string for md5sum
        return md5sum(''.join(indices))


def documents_eq(md5_one, md5_two):
    '''
        md5_one, md5_two : md5sums of indices in hopes of a smaller memory footprint
    '''

    return md5_one == md5_two

