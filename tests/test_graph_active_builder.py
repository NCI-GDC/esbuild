# -*- coding: utf-8 -*-
"""
test_graph_index.py
----------------------------------

Test the builder for graph ES index

"""

from base import TestBase
from gdcdatamodel import models as md
from prelude import create_prelude_nodes
from unittest import TestCase

import es_fixtures

from esbuild.graph.active.builder import (
    ActiveGraphIndexBuilder,
    list_product,
    subtree_paths_to_file,
    get_case_to_file_paths,
)

from esbuild.graph.legacy.builder import (
    LegacyGraphIndexBuilder,
)

from test_graph_legacy_builder import (
    TestGraphIndexBuilder as TestLegacyGraphIndexBuilder
)


class TestGraphIndexBuilder(TestLegacyGraphIndexBuilder):

    """Test that the ActiveGraphIndexBuilder produces an index that is a
    superset of the legacy graph index.

    """

    builder_class = ActiveGraphIndexBuilder


class TestGraphIndexBuilderUtils(TestCase):

    expected_file_path1 = [
        "submitted_aligned_reads",
        "alignment_cocleaning_workflow",
        "aligned_reads",
        "somatic_mutation_calling_workflow",
        "simple_somatic_mutation"
    ]

    def test_list_product(self):
        self.assertEqual(
            list_product(
                [['a', 'b'], ['-', '#']],
                [range(0, 2), range(2, 4), range(4, 8)]
            ),
            [['a', 'b', 0, 1],
             ['a', 'b', 2, 3],
             ['a', 'b', 4, 5, 6, 7],
             ['-', '#', 0, 1],
             ['-', '#', 2, 3],
             ['-', '#', 4, 5, 6, 7]])

    def test_subtree_paths_to_file_subset(self):
        self.assertIn(
            self.expected_file_path1,
            subtree_paths_to_file(md.ReadGroup))

    def test_subtree_paths_to_file_expecting_single(self):
        self.assertEqual(
            [['exon_expression'], ['gene_expression']],
            subtree_paths_to_file(md.RnaExpressionWorkflow))

    def test_subtree_paths_to_file_expecting_empty(self):
        self.assertEqual([], subtree_paths_to_file(md.Annotation))

    def test_get_case_to_file_paths_contains_legacy(self):
        active_paths = get_case_to_file_paths()
        for path in LegacyGraphIndexBuilder.case_to_file_paths:
            self.assertIn(path, active_paths)

    def test_get_case_to_file_paths_contains_expected_path_1(self):
        prefixes = [
            ['sample', 'aliquot', 'read_group'],
            ['sample', 'portion', 'analyte', 'aliquot', 'read_group'],
        ]
        for prefix in prefixes:
            self.assertIn(prefix + self.expected_file_path1,
                          get_case_to_file_paths())


class TestActiveGraphIndexBuilder(TestBase):

    @classmethod
    def setUpClass(cls):
        cls.delete_all_nodes()
        create_prelude_nodes(cls.g)
        es_fixtures.insert(cls.g)

    @classmethod
    def tearDownClass(cls):
        cls.delete_all_nodes()

    def setUp(self):
        with self.g.session_scope():
            self.submitted_aligned_reads1 = (
                self.g.nodes(md.SubmittedAlignedReads)
                .ids('b3601406-3676-4f76-9aa0-ed68ed6c3a05').one())
            self.submitted_aligned_reads2 = (
                self.g.nodes(md.SubmittedAlignedReads)
                .ids('c7ca17cd-a4be-47da-a446-8efaf0f73272').one())
            self.alignment_workflow = (
                self.g.nodes(md.AlignmentWorkflow)
                .ids('973bd442-04a0-4189-8f02-c8c7e041afe9').one())
            self.aligned_reads = (
                self.g.nodes(md.AlignedReads)
                .ids('a819133c-65c4-438c-93ae-a04e24e82626').one())

    def convert_documents(self):
        doc_conv = ActiveGraphIndexBuilder(self.g)
        with self.g.session_scope():
            doc_conv.cache_database()
        self.case_docs, self.file_docs, self.ann_docs = (
            doc_conv.denormalize_cases())
        self.case_doc = self.case_docs[0] if self.case_docs else None

    def get_aligned_reads_doc(self):
        self.convert_documents()
        return [
            d for d in self.file_docs
            if d['file_id'] == self.aligned_reads.node_id
        ][0]

    def test_simple_conversion(self):
        self.convert_documents()

    def test_files_are_in_index(self):
        self.convert_documents()
        file_ids = {d['file_id'] for d in self.file_docs}
        self.assertIn(self.submitted_aligned_reads1.node_id, file_ids)
        self.assertIn(self.submitted_aligned_reads2.node_id, file_ids)
        self.assertIn(self.aligned_reads.node_id, file_ids)

    def test_submitted_aligned_reads_no_analysis(self):
        self.convert_documents()
        docs = [
            d for d in self.file_docs
            if d['file_id'] in [
                self.submitted_aligned_reads1.node_id,
                self.submitted_aligned_reads2.node_id,
            ]
        ]
        for doc in docs:
            self.assertNotIn('analysis', doc)

    def test_aligned_reads_analysis(self):
        doc = self.get_aligned_reads_doc()
        self.assertIn('analysis', doc)
        self.assertIn('analysis_id', doc['analysis'])

    def test_aligned_reads_analysis_input_files(self):
        doc = self.get_aligned_reads_doc()
        self.assertIn('input_files', doc['analysis'])
        self.assertEqual(len(doc['analysis']['input_files']), 2)

        for f in doc['analysis']['input_files']:
            self.assertTrue(f['file_name'])

    def test_aligned_reads_analysis_read_group(self):
        doc = self.get_aligned_reads_doc()
        self.assertIn('metadata', doc['analysis'])
        self.assertIn('read_groups', doc['analysis']['metadata'])
        self.assertIn(
            'read_group_id',
            doc['analysis']['metadata']['read_groups'][0])

    def test_submitted_aligned_reads_has_downstream_analysis(self):
        self.convert_documents()
        docs = [
            d for d in self.file_docs
            if d['file_id'] in [
                self.submitted_aligned_reads1.node_id,
                self.submitted_aligned_reads2.node_id,
            ]
        ]
        for doc in docs:
            self.assertIn('downstream_analysis', doc)
            self.assertIn('output_files', doc['downstream_analysis'])
