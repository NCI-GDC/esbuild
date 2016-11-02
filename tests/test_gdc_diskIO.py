
import glob
import os
import tempfile
import shutil

from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder
from esbuild.gdc_diskIO import DocTypes, GDCDiskIO, documents_eq
from psqlgraph import PsqlGraphDriver
from unittest import TestCase

from conftest import (
        PG_HOST,
        PG_USER,
        PG_PASSWORD,
        PG_DATABASE,
)


class DiskIOTest(TestCase):
    def setUp(self):
        os.environ["PG_HOST"] = PG_HOST
        os.environ["PG_USER"] = PG_USER
        os.environ["PG_PASS"] = PG_PASSWORD
        os.environ["PG_NAME"] = PG_DATABASE

        # use a temp directory using the nice python stdlib functions
        # the programmer is responsible for cleaning up the temp directory
        # making it not really temporary
        os.environ["SAVE_DIR"] = tempfile.mkdtemp()

        self.test_path = os.environ['SAVE_DIR']

        graph = PsqlGraphDriver(
                os.environ['PG_HOST'],
                os.environ['PG_USER'],
                os.environ['PG_PASS'],
                os.environ['PG_NAME'],
        )

        converter = ActiveGraphIndexBuilder(graph)
        converter.cache_database()
        self.denormalized = converter.denormalize_all()

        self.gdio = GDCDiskIO(self.test_path, 'active')


    def tearDown(self):
        if os.path.exists(os.environ['SAVE_DIR']):
            shutil.rmtree(os.environ['SAVE_DIR'])


    def test_save_docs(self):

        for i, d in enumerate(DocTypes().all_types):
            self.gdio.save_doctype(self.denormalized[i], d)

        # check if the filename with the same doc ID is in the saved dir
        bools = []
        for i, doctype in enumerate(DocTypes().all_types):
            for doc in self.denormalized[i]:
                doc_id = DocTypes().id[doctype]

                bools.append( doc[doc_id] in os.listdir(self.test_path + '/' + doctype) )

        self.assertTrue(False not in bools)


    def test_documents_eq(self):
        '''
            the docs are written to disk and read from disk out or order
            when compared to the original tuple returned by denormalize_all()

            `==` does not work in this case because the document lists
            for each doc_type are out of order, but they should be the same!

            this attempts to check equality of the tuples
        '''

        a = {'a':'a'}
        b = {'b':'b'}
        c = {'c':'c'}

        #  each index of t1 and t2 have the same elements, but out of order
        t1 = ( [b,a], [a,b,c,a,b,c], [b,b], [c,a] )
        t2 = ( [a,b], [a,a,b,b,c,c], [b,b], [a,c] )

        # reference for the false tests
        f1 = ( [a,c], [b,c], [c,a], [c,b] )

        # wrong length
        f2 = ( [a,c], [b,c] )

        # wrong elements
        f3 = ( [a,a], [b,b], [c,c], [a,c] )

        self.assertTrue(
                documents_eq(t1, t2) == True  and
                documents_eq(f1, f2) == False and
                documents_eq(f1, f3) == False
        )


    def test_read_write_archive(self):
        ''' make sure it reads and writes to a directory of anyone's choosing '''

        for i, d in enumerate(DocTypes().all_types):
            self.gdio.save_doctype(self.denormalized[i], d)

        self.gdio.write_archive()

        # use the same archive just written
        r1 = self.gdio.read_archive(self.gdio.full_path_to_archive)

        # if there should be a time where there are no indices
        # which should not happen unless there's something wrong
        empty_denorm = ( [], [], [], [] )
        tmp_gdio = self.gdio
        tmp_gdio.denormalized = empty_denorm

        for i, d in enumerate(DocTypes().all_types):
            self.gdio.save_doctype(tmp_gdio.denormalized[i], d)
        tmp_gdio.write_archive()
        r2 = tmp_gdio.read_archive(self.gdio.full_path_to_archive)


        self.assertTrue(
                documents_eq(self.denormalized, r1)  and
                documents_eq(empty_denorm, r2)
        )


    def test_cleanup_old_indices(self):
        ''' only keep the last 5 indices '''

        for _ in xrange(6):
            for i, d in enumerate(DocTypes().all_types):
                self.gdio.save_doctype(self.denormalized[i], d)
            self.gdio.write_archive()

        self.gdio.cleanup_old_indices()

        self.assertEqual( len(glob.glob(os.environ['SAVE_DIR'] + '/*tar.gz')), 5 )
