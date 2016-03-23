# -*- coding: utf-8 -*-
"""
test_graph_index.py
----------------------------------

Test the builder for graph ES index

"""

from base import TestBase
from gdcdatamodel import models as md
from mock import patch
from prelude import create_prelude_nodes

import es_fixtures

from esbuild.graph.active.builder import (
    ActiveGraphIndexBuilder
)


class TestGraphIndexBuilder(TestBase):

    @classmethod
    def setUpClass(cls):
        super(TestGraphIndexBuilder, cls).setUpClass()
        cls.delete_all_nodes()
        create_prelude_nodes(cls.g)

    @classmethod
    def tearDownClass(cls):
        super(TestGraphIndexBuilder, cls).setUpClass()
        cls.delete_all_nodes()

    def setUp(self):
        super(TestGraphIndexBuilder, self).setUp()
        self.delete_non_prelude_nodes()
        es_fixtures.insert(self.g)
        self.add_file_nodes()
        self.convert_documents()

    def convert_documents(self, doc_conv=None):
        doc_conv = doc_conv or ActiveGraphIndexBuilder(self.g)
        with self.g.session_scope():
            doc_conv.cache_database()
        self.case_docs, self.file_docs, self.ann_docs = (
            doc_conv.denormalize_cases())
        if self.case_docs:
            self.case_doc = self.case_docs[0]
        else:
            self.case_doc = None

    def test_case_clinical(self):
        props = self.case_doc
        self.assertTrue('clinical' in props)
        clinical = props['clinical']
        self.assertEqual(clinical['age_at_diagnosis'], 12419)

    def test_case_clinical_demographic(self):
        props = self.case_doc
        self.assertTrue('demographic' in props)
        doc = props['demographic']
        self.assertEqual(doc['year_of_birth'], 1951)

    def test_case_clinical_diagnoses(self):
        props = self.case_doc
        self.assertTrue('diagnoses' in props)
        diagnoses = props['diagnoses']
        self.assertEqual(len(diagnoses), 1)
        doc = props['diagnoses'][0]
        self.assertEqual(doc['age_at_diagnosis'], 47)

    def test_case_clinical_exposures(self):
        props = self.case_doc
        self.assertTrue('exposures' in props)
        exposures = props['exposures']
        self.assertEqual(len(exposures), 1)
        doc = props['exposures'][0]
        self.assertEqual(doc['cigarettes_per_day'], 10)

    def test_case_clinical_treatments(self):
        props = self.case_doc
        self.assertTrue('diagnoses' in props)
        diagnoses = props['diagnoses']
        self.assertEqual(len(diagnoses), 1)
        self.assertTrue('treatments' in diagnoses[0])
        treatments = diagnoses[0]['treatments']
        self.assertEqual(len(treatments), 1)
        doc = treatments[0]
        self.assertEqual(doc['treatment_or_therapy'], 'unknown')

    def test_case_clinical_family_histories(self):
        props = self.case_doc
        self.assertTrue('diagnoses' in props)
        family_histories = props['family_histories']
        self.assertEqual(len(family_histories), 1)
        doc = family_histories[0]
        self.assertEqual(doc['relationship_primary_diagnosis'], 'Married')

    def test_filter_non_relevant_annotations(self):
        case = self.get_fuzzed_node(md.Case)
        annotation = self.get_fuzzed_node(
            md.Annotation, category='Item flagged DNU')
        with self.g.session_scope() as s:
            f = self.g.nodes(md.File).ids('file1').first()
            case.projects.append(self.g.nodes(md.Project).first())
            case.files.append(f)
            case.annotations.append(annotation)
            map(s.merge, (case, annotation))
        self.convert_documents()
        for annotation in self.ann_docs:
            if annotation['entity_type'] == 'case':
                self.assertEqual(
                    annotation['case_id'], annotation['entity_id'])
                self.assertEqual(
                    annotation['case_submitter_id'], case.submitter_id)

    def test_annotation_case_submitter_id(self):
        case = self.get_fuzzed_node(md.Case)
        annotation = self.get_fuzzed_node(
            md.Annotation, category='Item flagged DNU')
        with self.g.session_scope() as s:
            case.projects.append(self.g.nodes(md.Project).first())
            case.files.append(self.g.nodes(md.File).ids('file1').first())
            case.annotations.append(annotation)
            map(s.merge, (case, annotation))
        self.convert_documents()
        for annotation in self.ann_docs:
            self.assertEqual(
                annotation['case_submitter_id'], case.submitter_id)

    def test_case_project(self):
        props = self.case_doc
        self.assertTrue('project' in props)
        actual = set(props['project'].keys())
        self.assertEqual(project_props, actual)

    def test_case_summary(self):
        props = self.case_doc
        self.assertTrue('summary' in props)
        actual = set(props['summary'].keys())
        self.assertEqual(summary_props, actual)

    def test_case_tss(self):
        props = self.case_doc
        self.assertTrue('tissue_source_site' in props)
        actual = set(props['tissue_source_site'].keys())
        self.assertEqual(tss_props, actual)

    def test_case_samples(self):
        props = self.case_doc
        self.assertTrue('samples' in props)
        actual = set(props['samples'][0].keys())
        print actual
        self.assertEqual(sample_props, actual.union(
            {'annotations', 'aliquots'}))

    def test_case_portions(self):
        props = self.case_doc
        self.assertTrue('portions' in props['samples'][0])
        portion = [p for s in props['samples'] for p in s['portions']
                   if 'slides' not in p][0]
        actual = set(portion.keys())
        self.assertEqual(portion_props, actual.union(
            {'annotations', 'slides', 'center'}))

    def test_case_analytes(self):
        props = self.case_doc
        portions = (props['samples'][0]['portions'][0])
        self.assertTrue('analytes' in portions)
        actual = set(portions['analytes'][0].keys())
        self.assertEqual(analyte_props, actual.union(
            {'annotations'}))

    def test_case_aliquots(self):
        props = self.case_doc
        print props.keys()
        analytes = (props['samples'][0]['portions'][0]['analytes'][0])
        self.assertTrue('aliquots' in analytes)
        actual = set(analytes['aliquots'][0].keys())
        self.assertEqual(aliquot_props, actual.union(
            {'annotations'}))

    def test_case_files(self):
        props = self.case_doc
        self.assertTrue('files' in props)

        # this makes sure the (to_delete / non_live /
        # file-derived_from-file) file doesn't show up
        self.assertEqual(len(props["files"]), 1)

        actual = set(props['files'][0].keys())

        self.assertEqual(
            file_props.union({
                'origin'
            }),
            actual.union({
                'annotations',
                'metadata_files',
                'center',
                'tags',
                'data_format',
                'platform',
                'associated_entities',
                'archive',
                'experimental_strategy',
            })
        )

    def test_index_files(self):
        props = self.case_doc
        self.assertTrue('files' in props)
        self.assertEqual(len(props["files"]), 1)
        file_ = props['files'][0]
        self.assertTrue('index_files' in file_)
        print file_['index_files']
        self.assertEqual(len(file_["index_files"]), 1)
        index_file = file_["index_files"][0]
        self.assertEqual(index_file['file_name'], 'test_file.bam.bai')
        self.assertEqual(index_file['file_format'], 'BAI')

    def test_omitted_projects(self):
        doc_conv = ActiveGraphIndexBuilder(self.g)
        doc_conv.omitted_projects.add(('TCGA', 'BRCA'))
        self.convert_documents(doc_conv)
        self.assertIsNone(self.case_doc)

    def test_basic_suppression(self):
        case = self.get_fuzzed_node(md.Case)
        annotation = self.get_fuzzed_node(
            md.Annotation,
            classification='Redaction',
            category='Genotype mismatch',
        )
        with self.g.session_scope() as s:
            f = self.g.nodes(md.File).ids('file1').first()
            case.projects.append(self.g.nodes(md.Project).first())
            case.files.append(f)
            case.annotations.append(annotation)
            map(s.merge, (case, annotation))
        self.convert_documents()
        # the redacted case should not be there
        self.assertNotIn(case.node_id, [c["case_id"] for c in self.case_docs])
        # the redacted file should not be there
        self.assertNotIn("file1", [f["file_id"] for f in self.file_docs])

    def test_non_case_suppression(self):
        with self.g.session_scope() as s:
            annotation = self.get_fuzzed_node(
                md.Annotation,
                classification='Redaction',
                category='Genotype mismatch',
            )
            portion = self.g.nodes(md.Portion)\
                            .ids('5b2a99b7-e1a8-4739-acaf-d5f75cc47021')\
                            .one()
            portion.annotations = [annotation]
            sample = portion.samples[0]
            case = sample.cases[0]
            analyte = portion.analytes[0]
            aliquot = analyte.aliquots[0]
            redacted1 = self.get_fuzzed_node(md.File, node_id="redact1", state="live")
            redacted1.portions = [portion]
            redacted2 = self.get_fuzzed_node(md.File, node_id="redact2", state="live")
            redacted2.aliquots = [aliquot]
            s.add(redacted1)
            s.add(redacted2)
        self.convert_documents()
        case_doc = [c for c in self.case_docs if c["case_id"] == case.node_id][0]
        sample_doc = [s for s in case_doc["samples"] if s["sample_id"] == sample.node_id][0]
        self.assertNotIn(portion.node_id, [p["portion_id"] for p in sample_doc["portions"]])
        self.assertNotIn("redact1", [f["file_id"] for f in self.file_docs])
        self.assertNotIn("redact2", [f["file_id"] for f in self.file_docs])

    def test_subject_withdrew_consent_is_not_suppressed(self):
        with self.g.session_scope() as s:
            case = self.get_fuzzed_node(md.Case)
            annotation = self.get_fuzzed_node(
                md.Annotation,
                classification='Redaction',
                category='Subject withdrew consent',
            )
            f = self.g.nodes(md.File).ids('file1').first()
            case.projects.append(self.g.nodes(md.Project).first())
            case.files.append(f)
            case.annotations.append(annotation)
            map(s.merge, (case, annotation))
        self.convert_documents()
        # the case should be there
        self.assertIn(case.node_id, [c["case_id"] for c in self.case_docs])
        # the file should be there
        self.assertIn("file1", [f["file_id"] for f in self.file_docs])

    @patch("esbuild.graph.common.builder.statsd")
    def test_duplicate_classification_only_results_in_warning(self, mock_statsd):
        with self.g.session_scope() as s:
            s.add(self.live_file)
            wxs = self.g.nodes(md.ExperimentalStrategy)\
                        .props(name="WXS").one()
            validation = self.g.nodes(md.ExperimentalStrategy)\
                               .props(name="VALIDATION").one()
            self.live_file.experimental_strategies = [wxs, validation]
        self.convert_documents()
        # the file should be there
        self.assertIn(self.live_file.node_id,
                      [f["file_id"] for f in self.file_docs])
        self.assertEqual(len(mock_statsd.event.mock_calls), 1)

    def test_derived_files(self):
        with self.g.session_scope() as s:
            s.add(self.live_file)
            fake_center = self.get_fuzzed_node(md.Center)
            self.live_file.centers = [fake_center]
            related_to_live = self.live_file.related_files[1]
            derived_file = self.get_fuzzed_node(
                md.File,
                state="live",
                file_name="derived_file.bam",
            )
            derived_file.sysan["source"] = "tcga_exome_alignment"
            self.live_file.derived_files = [derived_file]
            related_to_derived = self.get_fuzzed_node(
                md.File,
                state="live",
                file_name="derived_file.bam.txt",
            )
            related_to_derived.sysan["source"] = "tcga_exome_alignment"
            derived_file.related_files = [related_to_derived]

        self.convert_documents()

        # derived_file should be a doc in it's own right, and should
        # have the single correct related file
        derived_file_docs = [
            f for f in self.file_docs
            if f["file_id"] == derived_file.node_id
        ]
        self.assertEqual(len(derived_file_docs), 1)
        derived_file_doc = derived_file_docs[0]
        self.assertEqual(len(derived_file_doc["metadata_files"]), 1)

        self.assertIn(
            related_to_derived.node_id,
            [f["file_id"] for f in derived_file_doc["metadata_files"]]
        )
        # self,live_file should just have the one correct related_file
        live_file_doc = [f for f in self.file_docs
                         if f["file_id"] == self.live_file.node_id][0]
        self.assertEqual(len(live_file_doc["metadata_files"]), 1)
        self.assertIn(
            related_to_live.node_id,
            [f["file_id"] for f in live_file_doc["metadata_files"]]
        )
        # test origins are correct
        self.assertEqual(live_file_doc["origin"], "migrated")
        self.assertEqual(derived_file_doc["origin"], "harmonized")
        # centers and associated_entities should be the same
        self.assertEqual(live_file_doc["center"], derived_file_doc["center"])
        self.assertEqual(live_file_doc["associated_entities"],
                         derived_file_doc["associated_entities"])

    def test_non_live_related_files_dont_cause_source_files_in_related(self):
        with self.g.session_scope() as s:
            s.add(self.live_file)
            related_to_live = self.live_file.related_files[1]
            derived_file = self.get_fuzzed_node(
                md.File,
                state="live",
                file_name="derived_file.bam",
            )
            derived_file.sysan["source"] = "tcga_exome_alignment"
            self.live_file.derived_files = [derived_file]
            related_to_derived = self.get_fuzzed_node(
                md.File,
                state="uploaded",
                file_name="derived_file.txt",
            )
            related_to_derived.sysan["source"] = "tcga_exome_alignment"
            derived_file.related_files = [related_to_derived]

        self.convert_documents()

        # derived_file should be a doc in it's own right, and should
        # have the single correct related file
        derived_file_docs = [
            f for f in self.file_docs
            if f["file_id"] == derived_file.node_id
        ]
        self.assertEqual(len(derived_file_docs), 1)
        derived_file_doc = derived_file_docs[0]
        self.assertIsNone(derived_file_doc.get("metadata_files"))

        # self.live_file should just have the one correct related_file
        live_file_docs = [
            f for f in self.file_docs
            if f["file_id"] == self.live_file.node_id
        ]
        self.assertEqual(len(live_file_docs), 1)
        live_file_doc = live_file_docs[0]
        self.assertEqual(len(live_file_doc["metadata_files"]), 1)

        self.assertIn(
            related_to_live.node_id,
            [f["file_id"] for f in live_file_doc["metadata_files"]]
        )
        # test origins are correct
        self.assertEqual(live_file_doc["origin"], "migrated")
        self.assertEqual(derived_file_doc["origin"], "harmonized")


sample_props = {
    'aliquots',
    'annotations',
    'created_datetime',
    'current_weight',
    'days_to_collection',
    'days_to_sample_procurement',
    'freezing_method',
    'initial_weight',
    'intermediate_dimension',
    'is_ffpe',
    'longest_dimension',
    'oct_embedded',
    'pathology_report_uuid',
    'portions',
    'sample_id',
    'sample_type',
    'sample_type_id',
    'shortest_dimension',
    'state',
    'submitter_id',
    'time_between_clamping_and_freezing',
    'time_between_excision_and_freezing',
    'tumor_code',
    'tumor_code_id',
    'updated_datetime',
}

project_props = {
    'dbgap_accession_number',
    'disease_type',
    'name',
    'primary_site',
    'program',
    'project_id',
    'released',
    'state',
}

summary_props = {
    'data_categories',
    'experimental_strategies',
    'file_count',
    'file_size',
}

tss_props = {
    'bcr_id',
    'code',
    'name',
    'project',
    'tissue_source_site_id',
}

portion_props = {
    'analytes',
    'annotations',
    'center',
    'created_datetime',
    'creation_datetime',
    'is_ffpe',
    'portion_id',
    'portion_number',
    'slides',
    'state',
    'submitter_id',
    'updated_datetime',
    'weight',
}

analyte_props = {
    'a260_a280_ratio',
    'aliquots',
    'amount',
    'analyte_id',
    'analyte_type',
    'analyte_type_id',
    'annotations',
    'concentration',
    'created_datetime',
    'spectrophotometer_method',
    'state',
    'submitter_id',
    'updated_datetime',
    'well_number',
}

aliquot_props = {
    'aliquot_id',
    'amount',
    'annotations',
    'center',
    'concentration',
    'created_datetime',
    'source_center',
    'state',
    'submitter_id',
    'updated_datetime',
}

annotation_props = {
    'annotation_id',
    'case_id',
    'case_submitter_id',
    'category',
    'classification',
    'created_datetime',
    'created_datetime',
    'creator',
    'entity_id',
    'entity_type',
    'notes',
    'state',
    'status',
    'submitter_id',
    'updated_datetime',
}

file_props = {
    'access',
    'acl',
    'annotations',
    'archive',
    'associated_entities',
    'cases',
    'center',
    'created_datetime',
    'data_format',
    'data_type',
    'data_category',
    'error_type',
    'experimental_strategy',
    'file_id',
    'file_name',
    'file_size',
    'file_state',
    'index_files',
    'md5sum',
    'platform',
    'published_datetime',
    'metadata_files',
    'state',
    'state_comment',
    'submitter_id',
    'tags',
    'updated_datetime',
    'uploaded_datetime',
}
