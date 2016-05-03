"""This is the fixture data from a sample biospecemin XML, just
represented in a way that can be persisted without using xml2psqlgraph.

"""

from gdcdatamodel.models import *  # noqa
from gdcdictionary import gdcdictionary

import random
import string
import uuid


def random_string(length=6):
    return ''.join([
        random.choice(
            string.ascii_lowercase + string.digits
        ) for _ in range(length)
    ])


def fuzzed(node_class, node_id=None, **kwargs):
    if node_id is None:
        node_id = str(uuid.uuid4())
    for key, types in node_class.get_pg_properties().iteritems():
        schema = gdcdictionary.schema[node_class.label]
        prop_def = schema['properties'].get(key, {})

        if key in kwargs:
            continue
        # Enum
        elif 'enum' in prop_def:
            kwargs[key] = prop_def['enum'][0]
        # String
        elif not types or str in types:
            kwargs[key] = random_string()
        # Integer
        elif int in types or long in types:
            kwargs[key] = random.randint(1e6, 1e7)
        # Float
        elif float in types:
            kwargs[key] = random.random()
        # Boolean
        elif bool in types:
            kwargs[key] = random.choice((True, False))

    return node_class(node_id, **kwargs)


NODES = [
    fuzzed(
        SubmittedTangentCopyNumber,
        node_id='cnv-file-1',
        acl=['phs000178'],
        state='submitted',
    ),
    fuzzed(
        CopyNumberLiftoverWorkflow,
        node_id='cnv-workflow-1',
        acl=['phs000178'],
        state='submitted',
    ),
    fuzzed(
        CopyNumberSegment,
        node_id='cnv-segment-file-1',
        acl=['phs000178'],
        state='submitted',
    ),
    fuzzed(
        AnalysisMetadata,
        node_id='analysis-metadata-1',
        acl=['phs000178'],
        file_name='analysis-metadata-1.xml',
        md5sum='d8e8fca2dc0f896fd7cb4cb0031ba249',
    ),
    fuzzed(
        RunMetadata,
        node_id='run-metadata-1',
        acl=['phs000178'],
        file_name='run-metadata-1.xml',
        md5sum='d8e8fca2dc0f896fd7cb4cb0031ba249',
    ),
    fuzzed(
        ExperimentMetadata,
        node_id='experiment-metadata-1',
        acl=['phs000178'],
        file_name='experiment-metadata-1.xml',
        md5sum='d8e8fca2dc0f896fd7cb4cb0031ba249',
    ),
    File(
        node_id='live-file',
        acl=['phs000178'],
        project_id='TCGA-BRCA',
        file_name='TCGA-WR-A838-01A-12R-A406-31_rnaseq_fastq.tar',
        file_size=12916551680,
        md5sum='d7e6cbd40ef2f5b6607cb4af982280a9',
        state='live',
        file_state='submitted',
        state_comment=None,
        submitter_id='5cb6bc65-9cd5-45ac-9078-551bc7408906',
        error_type=None,
    ),
    File(
        node_id='harmonized-file',
        acl=['phs000178'],
        project_id='TCGA-BRCA',
        file_name='TCGA-WR-A838-01A-12R-A406-31_aligned.bam',
        file_size=12916551680,
        md5sum='d3f6cbd40ef2f5b6607cb4af982280a9',
        state='live',
        submitter_id='3d16fb28-51b7-4fa2-b528-077716e5d64a',
        system_annotations=dict(
            source='target_wgs_alignment',
        )
    ),
    fuzzed(
        File,
        node_id='index-file',
        acl=['phs000178'],
        state='live',
        file_name='test_file.bam.bai',
    ),
    fuzzed(
        AlignedReadsIndex,
        node_id='index-file-2',
        acl=['phs000178'],
        state='live',
        file_name='index-file-2.bam.bai',
    ),
    fuzzed(
        File,
        node_id='legacy-file-with-empty-acl',
        acl=[],
        state='live',
        file_name='test-file-3.bam',
    ),
    fuzzed(
        AlignedReads,
        node_id='active-file-with-empty-acl',
        acl=[],
        state='live',
        file_name='test-file-4.bam',
    ),
    fuzzed(
        File,
        node_id='related-file',
        acl=['phs000178'],
        state="live",
        file_state='submitted',
        file_name="a_related_file.txt"
    ),
    fuzzed(
        File,
        node_id='non-live-file',
        acl=['phs000178'],
        state='uploaded'
    ),
    File(
        node_id='to-delete-file',
        acl=['phs000178'],
        project_id='TCGA-BRCA',
        file_name='a_file_to_be_deleted.txt',
        file_size=5,
        md5sum='foobar',
        state='live',
        file_state='submitted',
        state_comment=None,
        submitter_id='5cb6bc65-9cd5-45ac-9078-551bc7408906',
        error_type=None,
    ),
    AlignedReads(
        node_id='a819133c-65c4-438c-93ae-a04e24e82626',
        acl=['phs000178'],
        data_category='Sequencing Data',
        data_type='Aligned Reads',
        error_type='file_size',
        experimental_strategy='WGS',
        data_format='BAM',
        file_name='aligned-reads-1.bam',
        file_size=6977248,
        file_state='submitted',
        md5sum='i73t7p',
        project_id='c83dho',
        state='submitted',
        state_comment='qi8sh3',
        submitter_id='280msb',
    ),
    AlignmentWorkflow(
        node_id='973bd442-04a0-4189-8f02-c8c7e041afe9',
        acl=['phs000178'],
        project_id='b7ghsa',
        state='submitted',
        submitter_id='jstzk2',
        workflow_link='fsnt4s',
        workflow_type='STAR 2-Pass'
    ),
    SubmittedAlignedReads(
        node_id='b3601406-3676-4f76-9aa0-ed68ed6c3a05',
        acl=['phs000178'],
        data_category='Sequencing Data',
        data_type='Aligned Reads',
        error_type='file_size',
        experimental_strategy='WGS',
        data_format='BAM',
        file_name='submitted_aligned_reads1.bam',
        file_size=3007547,
        file_state='submitted',
        md5sum='5ot6ln',
        project_id='pmo7pt',
        state='submitted',
        state_comment='6665h3',
        submitter_id='submitted_aligned_reads1',
    ),
    SubmittedAlignedReads(
        node_id='c7ca17cd-a4be-47da-a446-8efaf0f73272',
        acl=['phs000178'],
        data_category='Sequencing Data',
        data_type='Aligned Reads',
        error_type='file_size',
        experimental_strategy='WGS',
        data_format='BAM',
        file_name='submitted_aligned_reads2.bam',
        file_size=3277108,
        file_state='submitted',
        md5sum='jo94nz',
        project_id='9q5ibr',
        state='submitted',
        state_comment='tl16c3',
        submitter_id='submitted_aligned_reads2',
    ),
    ReadGroup(
        node_id='64f66bc3-1cee-41d7-ae86-cb443e84f30e',
        RIN=6610844,
        adapter_name='j0o0ou',
        adapter_sequence='0ypboh',
        base_caller_name='7ycy5z',
        base_caller_version='ctfuts',
        experiment_name='o91rjj',
        flow_cell_barcode='rbqv3b',
        includes_spike_ins=True,
        instrument_model='454 GS FLX Titanium',
        is_paired_end=True,
        library_name='i3z5fz',
        library_preparation_kit_catalog_number='iyeuoq',
        library_preparation_kit_name='a51svh',
        library_preparation_kit_vendor='07yeqz',
        library_preparation_kit_version='e30pa1',
        library_selection='Hybrid_Selection',
        library_strand='Unstranded',
        library_strategy='WGS',
        platform='Illumina',
        project_id='rmjpo8',
        read_group_name='1ros3k',
        read_length=4546829,
        sequencing_center='yzpdzm',
        sequencing_date='qisc3g',
        size_selection_range='7tl5qm',
        spike_ins_concentration='kdbjp1',
        spike_ins_fasta='0bxlsj',
        state='submitted',
        submitter_id='7yo0r1',
        target_capture_kit_catalog_number='lb3cvt',
        target_capture_kit_name='3gt57w',
        target_capture_kit_target_region='6o6lb3',
        target_capture_kit_vendor='es6bwd',
        target_capture_kit_version='nuoood',
        to_trim_adapter_sequence=False,
    ),
    Clinical(
        node_id='3239e85f-6be7-417b-b8e9-073c4d9c311c',
        project_id='TCGA-BRCA',
        age_at_diagnosis=34,
    ),
    Demographic(
        node_id='fe0dab0c-55d1-4721-8ebd-f5eb7b2c2f01',
        project_id='TCGA-BRCA',
        ethnicity='hispanic or latino',
        gender='male',
        race='white',
        submitter_id='TCGA-AB-2846_demographicID1',
        year_of_birth=1951,
        year_of_death=-1,
    ),
    Exposure(
        node_id='12af079f-da2c-4b48-86d4-c98fc0bf2a4f',
        alcohol_history='',
        alcohol_intensity='',
        bmi=-1,
        cigarettes_per_day=10,
        height=-1,
        project_id=u'TCGA-BRCA',
        submitter_id=u'TCGA-49-AARO_exposure',
        weight=-1,
        years_smoked=-1
    ),
    FamilyHistory(
        node_id='b56a74f5-650e-4fa4-8870-b0cf1d19c40c',
        project_id=u'TCGA-DEV1',
        relationship_age_at_diagnosis=10,
        relationship_gender=u'male',
        relationship_primary_diagnosis=u'Married',
        relationship_type=u'Legal',
        submitter_id=u'TCGA-DEV-1-CASE-0011-FAMILY-HISTORY',
    ),
    Diagnosis(
        node_id='5880dfde-9cc4-4027-92ec-921148fd0d40',
        age_at_diagnosis=47,
        classification_of_tumor=u'other',
        days_to_birth=-17238,
        days_to_last_follow_up=-1,
        days_to_last_known_disease_status=-1,
        days_to_recurrence=-1,
        last_known_disease_status=u'Unknown tumor status',
        morphology=u'8255/3',
        primary_diagnosis=u'c34.3',
        prior_malignancy=u'no',
        progression_or_recurrence=u'unknown',
        project_id=u'TCGA-LUAD',
        site_of_resection_or_biopsy=u'c34.3',
        submitter_id=u'TCGA-49-AARO_diagnosis',
        tissue_or_organ_of_origin=u'c34.3',
        tumor_grade=u'',
        tumor_stage=u'stage iiia',
        vital_status=u'dead',
    ),
    Treatment(
        node_id='4768cc70-ca97-4af8-9e66-6947c75a9376',
        days_to_treatment=None,
        project_id=u'TCGA-DEV3',
        submitter_id=u'TCGA-DEV-3-CASE-014-DIAG1-TR1',
        therapeutic_agents=None,
        treatment_intent_type=None,
        treatment_or_therapy=u'unknown',
    ),
    Sample(
        node_id='5fa9998b-deff-493e-8a8e-dc2422192a48',
        project_id='TCGA-BRCA',
        state='submitted',
        current_weight=None,
        days_to_collection=1416,
        days_to_sample_procurement=None,
        freezing_method=None,
        initial_weight=250.0,
        intermediate_dimension=None,
        is_ffpe=False,
        longest_dimension=None,
        oct_embedded='true',
        pathology_report_uuid='747FB91B-F523-4FA0-91DD-6014EF55643D',
        sample_type='Primary Tumor',
        sample_type_id='01',
        shortest_dimension=None,
        submitter_id='TCGA-AR-A1AR-01A',
        time_between_clamping_and_freezing=None,
        time_between_excision_and_freezing=None,
        tumor_code=None,
        tumor_code_id=None,
    ),
    Aliquot(
        node_id='84df0f82-69c4-4cd3-a4bd-f40d2d6ef916',
        project_id='TCGA-BRCA',
        state='submitted',
        amount=13.0,
        concentration=0.18,
        source_center='23',
        submitter_id='TCGA-AR-A1AR-10A-01D-A133-02',
    ),
    Aliquot(
        node_id='aliquot-attached-to-sample',
        project_id='TCGA-BRCA',
        state='submitted',
        amount=12.0,
        concentration=0.19,
        source_center='23',
        submitter_id='TCGA-AR-A1AR-10A-01D-A133-03',
    ),
    Analyte(
        node_id='344dffb3-2d2b-479d-8be5-9ead2728541b',
        project_id='TCGA-BRCA',
        state='submitted',
        a260_a280_ratio=None,
        amount=None,
        analyte_type='Repli-G (Qiagen) DNA',
        analyte_type_id='W',
        concentration=None,
        spectrophotometer_method=None,
        submitter_id='TCGA-AR-A1AR-01A-31W',
        well_number=None,
    ),
    Analyte(
        node_id='07c974b3-3286-4c4f-8b67-6f8e425936f4',
        project_id='TCGA-BRCA',
        a260_a280_ratio=1.94,
        state='submitted',
        amount=22.25,
        analyte_type='DNA',
        analyte_type_id='D',
        concentration=0.18,
        spectrophotometer_method='UV Spec',
        submitter_id='TCGA-AR-A1AR-10A-01D',
        well_number=None,
    ),
    Analyte(
        node_id='a58e8309-8346-4648-945d-e48efdc1a635',
        project_id='TCGA-BRCA',
        state='submitted',
        a260_a280_ratio=None,
        amount=None,
        analyte_type='Repli-G (Qiagen) DNA',
        analyte_type_id='W',
        concentration=None,
        spectrophotometer_method=None,
        submitter_id='TCGA-AR-A1AR-10A-01W',
        well_number=None,
    ),
    Case(
        node_id='eda6d2d5-4199-4f76-a45b-1d0401b4e54c',
        project_id='TCGA-BRCA',
        state='submitted',
        submitter_id='TCGA-AR-A1AR',
    ),
    Case(
        # floating case. has no neighbors
        node_id='ce5d360b-db30-4f60-a926-e8788fc0ed3b',
        project_id='TCGA-BRCA',
        state='submitted',
        submitter_id='TCGA-AR-A2AR',
    ),
    Portion(
        node_id='5b2a99b7-e1a8-4739-acaf-d5f75cc47021',
        project_id='TCGA-BRCA',
        creation_datetime=1293494400,
        state='submitted',
        is_ffpe=False,
        portion_number='01',
        submitter_id='TCGA-AR-A1AR-10A-01',
        weight=None,
    ),
    Aliquot(
        node_id='2708315c-d58a-42d7-a914-d6299aa74936',
        project_id='TCGA-BRCA',
        amount=6.67,
        state='submitted',
        concentration=0.18,
        source_center='23',
        submitter_id='TCGA-AR-A1AR-10A-01D-A134-01',
    ),
    Aliquot(
        node_id='c7976361-e689-44f1-9e5a-2a07064f2f95',
        project_id='TCGA-BRCA',
        state='submitted',
        amount=6.67,
        concentration=0.16,
        source_center='23',
        submitter_id='TCGA-AR-A1AR-01A-31D-A134-01',
    ),
    Aliquot(
        node_id='0ffb3f3d-f20e-43d1-9867-7dc75ac24f3b',
        project_id='TCGA-BRCA',
        state='submitted',
        amount=20.0,
        concentration=0.16,
        source_center='23',
        submitter_id='TCGA-AR-A1AR-01A-31R-A136-13',
    ),
    Aliquot(
        node_id='05c45162-6c94-4a15-accc-b6239451064c',
        project_id='TCGA-BRCA',
        state='submitted',
        amount=13.0,
        concentration=0.16,
        source_center='23',
        submitter_id='TCGA-AR-A1AR-01A-31D-A133-02',
    ),
    Analyte(
        node_id='3febc6c8-85ae-4d38-ba55-c959959846db',
        project_id='TCGA-BRCA',
        state='submitted',
        a260_a280_ratio=1.98,
        amount=48.62,
        analyte_type='DNA',
        analyte_type_id='D',
        concentration=0.16,
        spectrophotometer_method='UV Spec',
        submitter_id='TCGA-AR-A1AR-01A-31D',
        well_number=None,
    ),
    Aliquot(
        node_id='281bfaa0-3f3c-412f-a3f8-76f1aa6e53ed',
        project_id='TCGA-BRCA',
        state='submitted',
        amount=80.0,
        concentration=0.5,
        source_center='23',
        submitter_id='TCGA-AR-A1AR-10A-01W-A14P-09',
    ),
    Aliquot(
        node_id='0395a62f-3f37-4068-bab6-4c1d29cef2d5',
        project_id='TCGA-BRCA',
        state='submitted',
        amount=40.0,
        concentration=0.09,
        source_center='23',
        submitter_id='TCGA-AR-A1AR-10A-01D-A135-09',
    ),
    Aliquot(
        node_id='6d066a72-f59f-45a8-ab90-216000b36da4',
        project_id='TCGA-BRCA',
        state='submitted',
        amount=26.7,
        concentration=0.16,
        source_center='23',
        submitter_id='TCGA-AR-A1AR-01A-31R-A137-07',
    ),
    Aliquot(
        node_id='008ba655-a0a3-42c4-8c72-f1341365ef02',
        project_id='TCGA-BRCA',
        state='submitted',
        amount=40.0,
        concentration=0.08,
        source_center='23',
        submitter_id='TCGA-AR-A1AR-01A-31D-A135-09',
    ),
    Slide(
        node_id='3013e9be-aa3e-4986-990c-559982f00e36',
        project_id='TCGA-BRCA',
        state='submitted',
        number_proliferating_cells=None,
        percent_eosinophil_infiltration=None,
        percent_granulocyte_infiltration=None,
        percent_inflam_infiltration=None,
        percent_lymphocyte_infiltration=0.0,
        percent_monocyte_infiltration=0.0,
        percent_necrosis=0.0,
        percent_neutrophil_infiltration=0.0,
        percent_normal_cells=0.0,
        percent_stromal_cells=20.0,
        percent_tumor_cells=80.0,
        percent_tumor_nuclei=90.0,
        section_location='TOP',
        submitter_id='TCGA-AR-A1AR-01A-03-TSC',
    ),
    Aliquot(
        node_id='7b017050-97d4-45bb-bf83-c89dab812e44',
        project_id='TCGA-BRCA',
        state='submitted',
        amount=26.7,
        concentration=0.16,
        source_center='23',
        submitter_id='TCGA-AR-A1AR-01A-31D-A138-05',
    ),
    Aliquot(
        node_id='c1fd82a9-f75f-4297-b2c2-ec91c40a57f4',
        project_id='TCGA-BRCA',
        state='submitted',
        amount=80.0,
        concentration=0.5,
        source_center='23',
        submitter_id='TCGA-AR-A1AR-01A-31W-A14P-09',
    ),
    Portion(
        node_id='40407260-e805-4c2e-b2a7-13862bc5e494',
        project_id='TCGA-BRCA',
        state='submitted',
        creation_datetime=1297728000,
        is_ffpe=False,
        portion_number='31',
        submitter_id='TCGA-AR-A1AR-01A-31',
        weight=30.0,
    ),
    Analyte(
        node_id='5f5b9bb2-3278-424f-9cf2-e26f0c3b0fd5',
        project_id='TCGA-BRCA',
        state='submitted',
        a260_a280_ratio=1.82,
        amount=29.44,
        analyte_type='RNA',
        analyte_type_id='R',
        concentration=0.16,
        spectrophotometer_method='UV Spec',
        submitter_id='TCGA-AR-A1AR-01A-31R',
        well_number=None,
    ),
    Sample(
        node_id='c1e5beaa-6103-409d-bdd4-a86c0f210014',
        project_id='TCGA-BRCA',
        state='submitted',
        current_weight=None,
        days_to_collection=1416,
        days_to_sample_procurement=None,
        freezing_method=None,
        initial_weight=None,
        intermediate_dimension=None,
        is_ffpe=False,
        longest_dimension=None,
        oct_embedded='false',
        pathology_report_uuid='91C655D1-C777-41A9-B759-7ED12C72CF30',
        sample_type='Blood Derived Normal',
        sample_type_id='10',
        shortest_dimension=None,
        submitter_id='TCGA-AR-A1AR-10A',
        time_between_clamping_and_freezing=None,
        time_between_excision_and_freezing=None,
        tumor_code=None,
        tumor_code_id=None,
    ),
    Annotation(
        node_id='d7cb38ff-0ca2-5496-896b-92c5a76b6109',
        category="Center QC failed",
        classification="CenterNotification",
        creator="test_creator",
        notes="RNA-seq:LOW 5/3 COVERAGE RATIO",
        state='submitted',
        status="Approved",
        submitter_id="0000",
    ),
    fuzzed(
        SomaticMutationCallingWorkflow,
        node_id='somatic_mutation_calling_workflow_1',
        state='submitted',
    ),
    fuzzed(
        SimpleSomaticMutation,
        node_id='somatic_mutation_1',
        acl=['phs000178'],
        state='submitted',
    ),
    fuzzed(
        SimpleSomaticMutation,
        node_id='somatic_mutation_1',
        acl=['phs000178'],
        state='submitted',
    ),
    fuzzed(
        BiospecimenSupplement,
        node_id='biospecimen_supplement_1',
        acl=['phs000178'],
        data_category='Biospecimen',
        data_format='BCR XML',
        data_type='Biospecimen Supplement',
        file_name='nationwidechildrens.org_biospecimen.TCGA-A1-A1A1.xml',
        state='live'
    ),
    fuzzed(
        ClinicalSupplement,
        node_id='clinical_supplement_1',
        acl=['phs000178'],
        data_category='Clinical',
        data_format='BCR XML',
        data_type='Clinical Supplement',
        file_name='nationwidechildrens.org_clinical.TCGA-A1-A1A1.xml',
        state='live'
    ),
    fuzzed(
        File,
        node_id='old-biospecimen-supplement-xml',
        acl=['phs000178'],
        file_name='nationwidechildrens.org_biospecimen.TCGA-72-4234.xml',
        file_size=129165,
        md5sum='d7e6cbd40ef2f5b6607cb4af982280a9',
        state='live',
        file_state='submitted',
    ),

    # Prelude nodes
    DataSubtype(
        node_id='data_subtype_aligned_reads',
        name='Aligned reads',
    ),
    DataType(
        node_id='data_type_raw_sequencing',
        name='Raw sequencing data',
    ),
    Platform(
        node_id='ed523719-86fa-4131-bd14-a13f06d453ae',
        name='Illumina HiSeq',
    ),
    ExperimentalStrategy(
        node_id='a2b74dcc-052a-42ce-836e-c2fb549beea5',
        name='RNA-Seq'
    ),
    Tag(
        node_id='326acbfa-fcdf-4d25-9247-c393b988aa09',
        name='snv',
    ),
    Program(
        node_id='b80aa962-9650-5110-b3eb-bd087da808db',
        dbgap_accession_number="phs000178",
        name="TCGA",
    ),
    Center(
        node_id='ee7a85b3-8177-5d60-a10c-51180eb9009c',
        code="07",
        namespace="unc.edu",
        name="University of North Carolina",
        short_name="UNC",
        center_type="CGCC",
    ),
    Center(
        node_id='5069ce55-a23f-57c4-a28c-70a3c3cb0e4c',
        code="01",
        namespace="broad.mit.edu",
        name="Broad Institute of MIT and Harvard",
        short_name="BI",
        center_type="CGCC",
    ),
    TissueSourceSite(
        node_id='5e793cf6-1554-55db-b2ee-9c772717cea0',
        project="Breast invasive carcinoma",
        bcr_id="NCH",
        code="AR",
        name="Mayo",
    ),
    Center(
        node_id='c8611490-4cbd-5651-8de2-64484a515eec',
        code="02",
        namespace="hms.harvard.edu",
        name="Harvard Medical School",
        short_name="HMS",
        center_type="CGCC",
    ),
    Center(
        node_id='7ef3885b-37ce-5e16-8ba3-9d75b6690008',
        code="05",
        namespace="jhu-usc.edu",
        name="Johns Hopkins / University of Southern California",
        short_name="JHU_USC",
        center_type="CGCC",
    ),
    Project(
        node_id='1334612b-3d2e-5941-a476-d455d71b458f',
        released=True,
        state="legacy",
        code="BRCA",
        primary_site="Breast",
        disease_type="Breast Invasive Carcinoma",
        dbgap_accession_number=None,
        name="Breast Invasive Carcinoma",
    ),
    Center(
        node_id='6eba705a-0f00-5aa2-b1d0-04dbf62100cc',
        code="13",
        namespace="bcgsc.ca",
        name="Canada's Michael Smith Genome Sciences Centre",
        short_name="BCGSC",
        center_type="CGCC",
    ),
    Center(
        node_id='956ca84c-1124-53ff-824f-fa0c84425425',
        center_type='GSC',
        code='09',
        name='Washington University School of Medicine',
        namespace='genome.wustl.ed',
        short_name='WUSM',
    ),
]


EDGES = [
    FileDescribesCase(
        src_id='old-biospecimen-supplement-xml',
        dst_id='eda6d2d5-4199-4f76-a45b-1d0401b4e54c',
    ),
    BiospecimenSupplementDerivedFromCase(
        src_id='biospecimen_supplement_1',
        dst_id='eda6d2d5-4199-4f76-a45b-1d0401b4e54c',
    ),
    ClinicalSupplementDerivedFromCase(
        src_id='clinical_supplement_1',
        dst_id='eda6d2d5-4199-4f76-a45b-1d0401b4e54c',
    ),
    AnnotationAnnotatesAliquot(
        src_id='d7cb38ff-0ca2-5496-896b-92c5a76b6109',
        dst_id='84df0f82-69c4-4cd3-a4bd-f40d2d6ef916',
    ),
    FileMemberOfDataSubtype(
        src_id='live-file',
        dst_id='data_subtype_aligned_reads'
    ),
    FileRelatedToFile(
        src_id='live-file',
        dst_id='index-file',
    ),
    AlignedReadsIndexDerivedFromAlignedReads(
        src_id='index-file-2',
        dst_id='a819133c-65c4-438c-93ae-a04e24e82626',
    ),
    FileRelatedToFile(
        src_id='live-file',
        dst_id='related-file',
    ),
    FileDataFromAliquot(
        src_id='live-file',
        dst_id='84df0f82-69c4-4cd3-a4bd-f40d2d6ef916',
    ),
    FileDataFromAliquot(
        src_id='legacy-file-with-empty-acl',
        dst_id='84df0f82-69c4-4cd3-a4bd-f40d2d6ef916',
    ),
    FileDataFromAliquot(
        src_id='harmonized-file',
        dst_id='84df0f82-69c4-4cd3-a4bd-f40d2d6ef916',
    ),
    FileDataFromFile(
        src_id='harmonized-file',
        dst_id='live-file',
    ),
    FileDataFromAliquot(
        src_id='non-live-file',
        dst_id='84df0f82-69c4-4cd3-a4bd-f40d2d6ef916',
    ),
    FileDataFromAliquot(
        src_id='to-delete-file',
        dst_id='84df0f82-69c4-4cd3-a4bd-f40d2d6ef916',
    ),
    FileDataFromAliquot(
        src_id='related-file',
        dst_id='84df0f82-69c4-4cd3-a4bd-f40d2d6ef916',
    ),
    ReadGroupDerivedFromAliquot(
        src_id='64f66bc3-1cee-41d7-ae86-cb443e84f30e',
        dst_id='84df0f82-69c4-4cd3-a4bd-f40d2d6ef916',
    ),
    SubmittedAlignedReadsDataFromReadGroup(
        src_id='b3601406-3676-4f76-9aa0-ed68ed6c3a05',
        dst_id='64f66bc3-1cee-41d7-ae86-cb443e84f30e',
    ),
    SubmittedAlignedReadsDataFromReadGroup(
        src_id='c7ca17cd-a4be-47da-a446-8efaf0f73272',
        dst_id='64f66bc3-1cee-41d7-ae86-cb443e84f30e',
    ),
    AlignmentWorkflowPerformedOnSubmittedAlignedReads(
        src_id='973bd442-04a0-4189-8f02-c8c7e041afe9',
        dst_id='b3601406-3676-4f76-9aa0-ed68ed6c3a05',
    ),
    AlignmentWorkflowPerformedOnSubmittedAlignedReads(
        src_id='973bd442-04a0-4189-8f02-c8c7e041afe9',
        dst_id='c7ca17cd-a4be-47da-a446-8efaf0f73272',
    ),
    AlignedReadsDataFromAlignmentWorkflow(
        src_id='a819133c-65c4-438c-93ae-a04e24e82626',
        dst_id='973bd442-04a0-4189-8f02-c8c7e041afe9',
    ),
    AlignedReadsDataFromAlignmentWorkflow(
        src_id='active-file-with-empty-acl',
        dst_id='973bd442-04a0-4189-8f02-c8c7e041afe9',
    ),
    ExposureDescribesCase(
        src_id='12af079f-da2c-4b48-86d4-c98fc0bf2a4f',
        dst_id='eda6d2d5-4199-4f76-a45b-1d0401b4e54c',
    ),
    DiagnosisDescribesCase(
        src_id='5880dfde-9cc4-4027-92ec-921148fd0d40',
        dst_id='eda6d2d5-4199-4f76-a45b-1d0401b4e54c',
    ),
    TreatmentDescribesDiagnosis(
        src_id='4768cc70-ca97-4af8-9e66-6947c75a9376',
        dst_id='5880dfde-9cc4-4027-92ec-921148fd0d40',
    ),
    DemographicDescribesCase(
        src_id='fe0dab0c-55d1-4721-8ebd-f5eb7b2c2f01',
        dst_id='eda6d2d5-4199-4f76-a45b-1d0401b4e54c',
    ),
    FamilyHistoryDescribesCase(
        src_id='b56a74f5-650e-4fa4-8870-b0cf1d19c40c',
        dst_id='eda6d2d5-4199-4f76-a45b-1d0401b4e54c',
    ),
    ClinicalDescribesCase(
        src_id='3239e85f-6be7-417b-b8e9-073c4d9c311c',
        dst_id='eda6d2d5-4199-4f76-a45b-1d0401b4e54c',
    ),
    AliquotDerivedFromAnalyte(
        src_id='7b017050-97d4-45bb-bf83-c89dab812e44',
        dst_id='3febc6c8-85ae-4d38-ba55-c959959846db',
        properties={}
    ),
    AliquotDerivedFromSample(
        src_id='aliquot-attached-to-sample',
        dst_id='c1e5beaa-6103-409d-bdd4-a86c0f210014',
    ),
    AliquotShippedToCenter(
        src_id='0395a62f-3f37-4068-bab6-4c1d29cef2d5',
        dst_id='956ca84c-1124-53ff-824f-fa0c84425425',
        properties={'plate_column': '11',
                    'plate_id': 'A135',
                    'plate_row': 'B',
                    'shipment_center_id': '09',
                    'shipment_datetime': 1299542400,
                    'shipment_reason': None}),
    AliquotShippedToCenter(
        src_id='0ffb3f3d-f20e-43d1-9867-7dc75ac24f3b',
        dst_id='6eba705a-0f00-5aa2-b1d0-04dbf62100cc',
        properties={'plate_column': '6',
                    'plate_id': 'A136',
                    'plate_row': 'C',
                    'shipment_center_id': '13',
                    'shipment_datetime': 1299542400,
                    'shipment_reason': None}),
    AliquotShippedToCenter(
        src_id='281bfaa0-3f3c-412f-a3f8-76f1aa6e53ed',
        dst_id='956ca84c-1124-53ff-824f-fa0c84425425',
        properties={'plate_column': '11',
                    'plate_id': 'A14P',
                    'plate_row': 'B',
                    'shipment_center_id': '09',
                    'shipment_datetime': 1304380800,
                    'shipment_reason': None}),
    AnalyteDerivedFromPortion(
        src_id='a58e8309-8346-4648-945d-e48efdc1a635',
        dst_id='5b2a99b7-e1a8-4739-acaf-d5f75cc47021',
        properties={}),
    AliquotDerivedFromAnalyte(
        src_id='281bfaa0-3f3c-412f-a3f8-76f1aa6e53ed',
        dst_id='a58e8309-8346-4648-945d-e48efdc1a635',
        properties={}),
    AnalyteDerivedFromPortion(
        src_id='3febc6c8-85ae-4d38-ba55-c959959846db',
        dst_id='40407260-e805-4c2e-b2a7-13862bc5e494',
        properties={}),
    SampleDerivedFromCase(
        src_id='c1e5beaa-6103-409d-bdd4-a86c0f210014',
        dst_id='eda6d2d5-4199-4f76-a45b-1d0401b4e54c',
        properties={}),
    AliquotShippedToCenter(
        src_id='008ba655-a0a3-42c4-8c72-f1341365ef02',
        dst_id='956ca84c-1124-53ff-824f-fa0c84425425',
        properties={'plate_column': '5',
                    'plate_id': 'A135',
                    'plate_row': 'B',
                    'shipment_center_id': '09',
                    'shipment_datetime': 1299542400,
                    'shipment_reason': None}),
    SlideDerivedFromPortion(
        src_id='3013e9be-aa3e-4986-990c-559982f00e36',
        dst_id='40407260-e805-4c2e-b2a7-13862bc5e494',
        properties={}),
    CaseMemberOfProject(
        src_id='eda6d2d5-4199-4f76-a45b-1d0401b4e54c',
        dst_id='1334612b-3d2e-5941-a476-d455d71b458f',
        properties={}),
    AliquotDerivedFromSample(
        src_id='0395a62f-3f37-4068-bab6-4c1d29cef2d5',
        dst_id='c1e5beaa-6103-409d-bdd4-a86c0f210014',
        properties={}),
    AliquotShippedToCenter(
        src_id='7b017050-97d4-45bb-bf83-c89dab812e44',
        dst_id='7ef3885b-37ce-5e16-8ba3-9d75b6690008',
        properties={'plate_column': '5',
                    'plate_id': 'A138',
                    'plate_row': 'B',
                    'shipment_center_id': '05',
                    'shipment_datetime': 1299542400,
                    'shipment_reason': None}),
    AliquotDerivedFromAnalyte(
        src_id='84df0f82-69c4-4cd3-a4bd-f40d2d6ef916',
        dst_id='07c974b3-3286-4c4f-8b67-6f8e425936f4',
        properties={}),
    AliquotDerivedFromAnalyte(
        src_id='008ba655-a0a3-42c4-8c72-f1341365ef02',
        dst_id='3febc6c8-85ae-4d38-ba55-c959959846db',
        properties={}),
    AnalyteDerivedFromPortion(
        src_id='344dffb3-2d2b-479d-8be5-9ead2728541b',
        dst_id='40407260-e805-4c2e-b2a7-13862bc5e494',
        properties={}),
    AliquotDerivedFromSample(
        src_id='84df0f82-69c4-4cd3-a4bd-f40d2d6ef916',
        dst_id='c1e5beaa-6103-409d-bdd4-a86c0f210014',
        properties={}),
    AliquotDerivedFromSample(
        src_id='008ba655-a0a3-42c4-8c72-f1341365ef02',
        dst_id='5fa9998b-deff-493e-8a8e-dc2422192a48',
        properties={}),
    AliquotShippedToCenter(
        src_id='84df0f82-69c4-4cd3-a4bd-f40d2d6ef916',
        dst_id='c8611490-4cbd-5651-8de2-64484a515eec',
        properties={'plate_column': '11',
                    'plate_id': 'A133',
                    'plate_row': 'B',
                    'shipment_center_id': '02',
                    'shipment_datetime': 1299542400,
                    'shipment_reason': None}),
    AliquotDerivedFromAnalyte(
        src_id='0395a62f-3f37-4068-bab6-4c1d29cef2d5',
        dst_id='07c974b3-3286-4c4f-8b67-6f8e425936f4',
        properties={}),
    AliquotDerivedFromAnalyte(
        src_id='05c45162-6c94-4a15-accc-b6239451064c',
        dst_id='3febc6c8-85ae-4d38-ba55-c959959846db',
        properties={}),
    AliquotDerivedFromAnalyte(
        src_id='2708315c-d58a-42d7-a914-d6299aa74936',
        dst_id='07c974b3-3286-4c4f-8b67-6f8e425936f4',
        properties={}),
    CaseProcessedAtTissueSourceSite(
        src_id='eda6d2d5-4199-4f76-a45b-1d0401b4e54c',
        dst_id='5e793cf6-1554-55db-b2ee-9c772717cea0',
        properties={}),
    AliquotDerivedFromSample(
        src_id='c7976361-e689-44f1-9e5a-2a07064f2f95',
        dst_id='5fa9998b-deff-493e-8a8e-dc2422192a48',
        properties={}),
    AliquotDerivedFromSample(
        src_id='0ffb3f3d-f20e-43d1-9867-7dc75ac24f3b',
        dst_id='5fa9998b-deff-493e-8a8e-dc2422192a48',
        properties={}),
    AliquotDerivedFromAnalyte(
        src_id='c7976361-e689-44f1-9e5a-2a07064f2f95',
        dst_id='3febc6c8-85ae-4d38-ba55-c959959846db',
        properties={}),
    AliquotDerivedFromSample(
        src_id='281bfaa0-3f3c-412f-a3f8-76f1aa6e53ed',
        dst_id='c1e5beaa-6103-409d-bdd4-a86c0f210014',
        properties={}),
    AliquotDerivedFromSample(
        src_id='2708315c-d58a-42d7-a914-d6299aa74936',
        dst_id='c1e5beaa-6103-409d-bdd4-a86c0f210014',
        properties={}),
    AliquotDerivedFromSample(
        src_id='c1fd82a9-f75f-4297-b2c2-ec91c40a57f4',
        dst_id='5fa9998b-deff-493e-8a8e-dc2422192a48',
        properties={}),
    PortionDerivedFromSample(
        src_id='40407260-e805-4c2e-b2a7-13862bc5e494',
        dst_id='5fa9998b-deff-493e-8a8e-dc2422192a48',
        properties={}),
    PortionDerivedFromSample(
        src_id='5b2a99b7-e1a8-4739-acaf-d5f75cc47021',
        dst_id='c1e5beaa-6103-409d-bdd4-a86c0f210014',
        properties={}),
    AliquotDerivedFromSample(
        src_id='05c45162-6c94-4a15-accc-b6239451064c',
        dst_id='5fa9998b-deff-493e-8a8e-dc2422192a48',
        properties={}),
    AliquotDerivedFromAnalyte(
        src_id='0ffb3f3d-f20e-43d1-9867-7dc75ac24f3b',
        dst_id='5f5b9bb2-3278-424f-9cf2-e26f0c3b0fd5',
        properties={}),
    AnalyteDerivedFromPortion(
        src_id='5f5b9bb2-3278-424f-9cf2-e26f0c3b0fd5',
        dst_id='40407260-e805-4c2e-b2a7-13862bc5e494',
        properties={}),
    AliquotShippedToCenter(
        src_id='c7976361-e689-44f1-9e5a-2a07064f2f95',
        dst_id='5069ce55-a23f-57c4-a28c-70a3c3cb0e4c',
        properties={'plate_column': '5',
                    'plate_id': 'A134',
                    'plate_row': 'B',
                    'shipment_center_id': '01',
                    'shipment_datetime': 1299542400,
                    'shipment_reason': None}),
    AliquotShippedToCenter(
        src_id='6d066a72-f59f-45a8-ab90-216000b36da4',
        dst_id='ee7a85b3-8177-5d60-a10c-51180eb9009c',
        properties={'plate_column': '6',
                    'plate_id': 'A137',
                    'plate_row': 'C',
                    'shipment_center_id': '07',
                    'shipment_datetime': 1299542400,
                    'shipment_reason': None}),
    SampleDerivedFromCase(
        src_id='5fa9998b-deff-493e-8a8e-dc2422192a48',
        dst_id='eda6d2d5-4199-4f76-a45b-1d0401b4e54c',
        properties={}),
    AliquotDerivedFromAnalyte(
        src_id='6d066a72-f59f-45a8-ab90-216000b36da4',
        dst_id='5f5b9bb2-3278-424f-9cf2-e26f0c3b0fd5',
        properties={}),
    AliquotShippedToCenter(
        src_id='2708315c-d58a-42d7-a914-d6299aa74936',
        dst_id='5069ce55-a23f-57c4-a28c-70a3c3cb0e4c',
        properties={'plate_column': '11',
                    'plate_id': 'A134',
                    'plate_row': 'B',
                    'shipment_center_id': '01',
                    'shipment_datetime': 1299542400,
                    'shipment_reason': None}),
    AnalyteDerivedFromPortion(
        src_id='07c974b3-3286-4c4f-8b67-6f8e425936f4',
        dst_id='5b2a99b7-e1a8-4739-acaf-d5f75cc47021',
        properties={}),
    AliquotShippedToCenter(
        src_id='05c45162-6c94-4a15-accc-b6239451064c',
        dst_id='c8611490-4cbd-5651-8de2-64484a515eec',
        properties={'plate_column': '5',
                    'plate_id': 'A133',
                    'plate_row': 'B',
                    'shipment_center_id': '02',
                    'shipment_datetime': 1299542400,
                    'shipment_reason': None}),
    AliquotDerivedFromAnalyte(
        src_id='c1fd82a9-f75f-4297-b2c2-ec91c40a57f4',
        dst_id='344dffb3-2d2b-479d-8be5-9ead2728541b',
        properties={}),
    AliquotDerivedFromSample(
        src_id='7b017050-97d4-45bb-bf83-c89dab812e44',
        dst_id='5fa9998b-deff-493e-8a8e-dc2422192a48',
        properties={}),
    AliquotShippedToCenter(
        src_id='c1fd82a9-f75f-4297-b2c2-ec91c40a57f4',
        dst_id='956ca84c-1124-53ff-824f-fa0c84425425',
        properties={'plate_column': '5',
                    'plate_id': 'A14P',
                    'plate_row': 'B',
                    'shipment_center_id': '09',
                    'shipment_datetime': 1304380800,
                    'shipment_reason': None}),
    AliquotDerivedFromSample(
        src_id='6d066a72-f59f-45a8-ab90-216000b36da4',
        dst_id='5fa9998b-deff-493e-8a8e-dc2422192a48',
        properties={}),
    SimpleSomaticMutationDataFromSomaticMutationCallingWorkflow(
        src_id='somatic_mutation_1',
        dst_id='somatic_mutation_calling_workflow_1',
    ),
    SomaticMutationCallingWorkflowPerformedOnAlignedReads(
        src_id='somatic_mutation_calling_workflow_1',
        dst_id='a819133c-65c4-438c-93ae-a04e24e82626',
    ),
    AnalysisMetadataDerivedFromFile(
        src_id='analysis-metadata-1',
        dst_id='live-file',
    ),
    RunMetadataDerivedFromFile(
        src_id='run-metadata-1',
        dst_id='live-file',
    ),
    ExperimentMetadataDerivedFromFile(
        src_id='experiment-metadata-1',
        dst_id='live-file',
    ),
    SubmittedTangentCopyNumberDerivedFromAliquot(
        src_id='cnv-file-1',
        dst_id='84df0f82-69c4-4cd3-a4bd-f40d2d6ef916',
    ),
    CopyNumberLiftoverWorkflowPerformedOnSubmittedTangentCopyNumber(
        src_id='cnv-workflow-1',
        dst_id='cnv-file-1',
    ),
    CopyNumberSegmentDerivedFromCopyNumberLiftoverWorkflow(
        src_id='cnv-segment-file-1',
        dst_id='cnv-workflow-1'
    ),

    # Prelude
    DataSubtypeMemberOfDataType(
        src_id='data_subtype_aligned_reads',
        dst_id='data_type_raw_sequencing',
    ),
    ProjectMemberOfProgram(
        src_id='1334612b-3d2e-5941-a476-d455d71b458f',
        dst_id='b80aa962-9650-5110-b3eb-bd087da808db',
    ),
]


def insert(g):
    with g.session_scope() as session:
        for node in NODES:
            session.merge(node)
        for edge in EDGES:
            session.merge(edge)

        to_delete = g.nodes(File).ids('to-delete-file').one()
        to_delete.sysan['to_delete'] = True
        session.merge(to_delete)
