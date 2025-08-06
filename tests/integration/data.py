"""
Test data that contains a mix of legacy and active files for the
builders to build indices from.  All new test data should go here to
verify that the both builders handle it correctly, as they both pull
from the same database in the real world.

"""

import hashlib
import random
import re
import uuid
from collections.abc import Iterable, Iterator, Sequence
from typing import Any, Protocol, runtime_checkable

import gdcdictionary
import psqlgraph
from gdcdatamodel2 import models
from psqlgraph import hydrator

from esbuild.graph.common import builder

DATA_FILE_CATEGORIES = builder.GraphIndexBuilder.data_file_categories
DATA_FILE_INDEXD_FIELDS = builder.GraphIndexBuilder.data_file_indexd_fields
# Populated each time get_node_id is called, Used for debugging missing ids
NODE_ID_TO_STRING: dict[str, str] = {}
# Defaults for the node factory
node_factory = hydrator.NodeFactory(models, gdcdictionary.gdcdictionary.schema)


def fuzzed(
    node_class: type[models.Node], node_id: str | None = None, **kwargs: Any
) -> models.Node:
    # Set some required properties if not provided
    kwargs["acl"] = kwargs.get("acl", ["phs000178"])
    kwargs["node_id"] = node_id or str(uuid.uuid4())
    kwargs["state"] = kwargs.get("state") or "released"

    return node_factory.create(node_class.get_label(), override=kwargs, all_props=True)


def get_node_id(string_id: str) -> str:
    node_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, string_id))
    NODE_ID_TO_STRING[node_id] = string_id  # need this side-effect for debugging =\
    return node_id


@runtime_checkable
class FileNode(Protocol):
    node_id: str
    md5sum: str
    file_name: str
    file_size: int

    @property
    def _dictionary(self) -> dict: ...


def _add_index_data(file_nodes: Iterable[FileNode]) -> Iterator[dict[str, Any]]:
    for node in file_nodes:
        urls = [f"s3://bucket/{node.md5sum}/{node.file_name}"]

        # Replace illegal md5sum with legal one:
        md5sum = str(getattr(node, "md5sum", None))
        if not re.findall(r"([a-fA-F\d]{32})", md5sum):
            node.md5sum = hashlib.md5(
                md5sum.encode("utf-8"), usedforsecurity=False
            ).hexdigest()

        # Patch file_size if none provided:
        if not getattr(node, "file_size", None):
            node.file_size = random.randint(int(1e6), int(1e7))

        indexd_did = node.node_id
        indexd_record = {
            "urls": urls,
            "did": indexd_did,
            "node_id": node.node_id,
        }

        for key in DATA_FILE_INDEXD_FIELDS:
            key_value = getattr(node, key, None)
            if key_value is None:
                continue
            # populate indexd record with the value from the node
            indexd_record[key] = key_value

            # Patch node.key with error value:
            if isinstance(key_value, str):
                setattr(node, key, "error")
            elif isinstance(key_value, list):
                setattr(node, key, ["error" for _ in getattr(node, key)])
            elif isinstance(key_value, int):
                setattr(node, key, -1)
            else:
                raise ValueError("Can not process the value:", getattr(node, key))

        yield indexd_record


def patch_test_data_get_indexd(
    nodes: Sequence[models.Node],
) -> tuple[Sequence[models.Node], Sequence[dict[str, Any]]]:
    """
    Takes effect only for file nodetypes:

    1. Will generate indexd data off of nodes
    2. Will patch nodes with error values for keys that are moved to indexd
       (for all file nodetypes and for all file metadata fields)
    3. Will patch illegal md5sum fields with random legal ones for all file nodes

    """
    file_nodes = (
        n
        for n in nodes
        if isinstance(n, FileNode)
        and n._dictionary.get("category") in DATA_FILE_CATEGORIES
    )
    indexd_data = tuple(_add_index_data(file_nodes))

    return nodes, indexd_data


NODES = (
    fuzzed(
        models.File,
        node_id=get_node_id("file-only-attached-to-archive-1"),
        acl=["phs0000178"],
        state="released",
        file_name="file-only-attached-to-archive-1.txt",
    ),
    fuzzed(
        models.Archive,
        acl=["phs000178"],
        state="released",
        node_id=get_node_id("archive_1"),
    ),
    fuzzed(
        models.AnnotatedSomaticMutation,
        node_id=get_node_id("annotated_somatic_mutation_1"),
        acl=["phs000178"],
        data_type="Annotated Somatic Mutation",
        state="released",
        file_name="annotated_somatci_mutation_1.bam",
    ),
    fuzzed(
        models.SomaticAnnotationWorkflow,
        node_id=get_node_id("somatic_annotation_workflow_1"),
        state="released",
    ),
    fuzzed(
        models.SimpleSomaticMutation,
        node_id=get_node_id("simple_somatic_mutation_1"),
        acl=["phs000178"],
        state="released",
        data_category="Combined Nucleotide Variation",
        file_name="simple_somatic_mutation_1.bam",
    ),
    fuzzed(
        models.SomaticMutationCallingWorkflow,
        node_id=get_node_id("somatic_mutation_calling_workflow_1"),
        state="released",
        workflow_type="MuSE",
    ),
    fuzzed(
        models.SubmittedTangentCopyNumber,
        node_id=get_node_id("cnv-file-1"),
        acl=["phs000178"],
        state="released",
        file_name="cnv-file-1.bam",
    ),
    fuzzed(
        models.CopyNumberLiftoverWorkflow,
        node_id=get_node_id("cnv-workflow-1"),
        acl=["phs000178"],
        state="released",
    ),
    fuzzed(
        models.CopyNumberSegment,
        node_id=get_node_id("cnv-segment-file-1"),
        acl=["phs000178"],
        state="released",
        data_type="Allele-specific Copy Number Segment",
        file_name="cnv-segment-file-1.ext",
    ),
    fuzzed(
        models.AnalysisMetadata,
        node_id=get_node_id("analysis-metadata-1"),
        acl=["phs000178"],
        data_category="Sequencing Data",
        data_format="SRA XML",
        file_name="analysis-metadata-1.xml",
        md5sum="d8e8fca2dc0f896fd7cb4cb0031ba249",
    ),
    fuzzed(
        models.RunMetadata,
        node_id=get_node_id("run-metadata-1"),
        acl=["phs000178"],
        file_name="run-metadata-1.xml",
        md5sum="d8e8fca2dc0f896fd7cb4cb0031ba249",
    ),
    fuzzed(
        models.ExperimentMetadata,
        node_id=get_node_id("experiment-metadata-1"),
        acl=["phs000178"],
        data_category="Sequencing Data",
        file_name="experiment-metadata-1.xml",
        md5sum="d8e8fca2dc0f896fd7cb4cb0031ba249",
    ),
    models.File(
        node_id=get_node_id("live-file"),
        acl=["phs000178"],
        project_id="TCGA-BRCA",
        file_name="TCGA-WR-A838-01A-12R-A406-31_rnaseq_fastq.tar",
        file_size=12916551680,
        md5sum="d7e6cbd40ef2f5b6607cb4af982280a9",
        state="live",
        file_state="submitted",
        state_comment=None,
        submitter_id="5cb6bc65-9cd5-45ac-9078-551bc7408906",
        error_type=None,
    ),
    models.File(
        node_id=get_node_id("harmonized-file"),
        acl=["phs000178"],
        project_id="TCGA-BRCA",
        file_name="TCGA-WR-A838-01A-12R-A406-31_aligned.bam",
        file_size=12916551680,
        md5sum="d3f6cbd40ef2f5b6607cb4af982280a9",
        state="live",
        submitter_id="3d16fb28-51b7-4fa2-b528-077716e5d64a",
        system_annotations=dict(
            source="target_wgs_alignment",
        ),
    ),
    fuzzed(
        models.File,
        node_id=get_node_id("index-file"),
        acl=["phs000178"],
        project_id="TCGA-BRCA",
        state="live",
        file_name="test_file.bam.bai",
    ),
    fuzzed(
        models.AlignedReadsIndex,
        node_id=get_node_id("index-file-2"),
        acl=["phs000178"],
        state="live",
        data_category="Sequencing Data",
        file_name="index-file-2.bam.bai",
    ),
    fuzzed(
        models.File,
        node_id=get_node_id("legacy-file-with-empty-acl"),
        acl=[],
        state="live",
        file_name="test-file-3.bam",
    ),
    fuzzed(
        models.AlignedReads,
        node_id=get_node_id("active-file-with-empty-acl"),
        state="released",
        acl=[],
        file_name="test-file-4.bam",
    ),
    fuzzed(
        models.File,
        node_id=get_node_id("related-file"),
        acl=["phs000178"],
        project_id="TCGA-BRCA",
        state="live",
        file_state="submitted",
        file_name="a_related_file.txt",
    ),
    fuzzed(
        models.File,
        node_id=get_node_id("non-live-file"),
        acl=["phs000178"],
        state="uploaded",
        file_name="non-live-file-foo-bar",
    ),
    models.File(
        node_id=get_node_id("to-delete-file"),
        acl=["phs000178"],
        project_id="TCGA-BRCA",
        file_name="a_file_to_be_deleted.txt",
        file_size=5,
        md5sum="foobar",
        state="live",
        file_state="submitted",
        state_comment=None,
        submitter_id="5cb6bc65-9cd5-45ac-9078-551bc7408906",
        error_type=None,
    ),
    fuzzed(
        models.AlignedReads,
        node_id=get_node_id("aligned-reads-2"),
        state="released",
        data_format="BAM",
        file_name="aligned-reads-2.bam",
        acl=["phs000178"],
    ),
    models.AlignedReads(
        node_id=get_node_id("aligned-reads-1"),
        acl=["phs000178"],
        data_category="Sequencing Reads",
        data_type="Aligned Reads",
        error_type="file_size",
        experimental_strategy="WGS",
        data_format="BAM",
        file_name="aligned-reads-1.bam",
        file_size=6977248,
        file_state="submitted",
        md5sum="i73t7p",
        project_id="c83dho",
        state="released",
        state_comment="qi8sh3",
        submitter_id="280msb",
    ),
    models.AlignmentCocleaningWorkflow(
        node_id=get_node_id("alignment_cocleaning_wf"),
        acl=["phs000178"],
        state="released",
    ),
    models.SubmittedAlignedReads(
        node_id=get_node_id("submitted-aligned-reads-1"),
        acl=["phs000178"],
        data_category="Sequencing Reads",
        data_type="Aligned Reads",
        error_type="file_size",
        experimental_strategy="WGS",
        data_format="BAM",
        file_name="submitted_aligned_reads1.bam",
        file_size=3007547,
        file_state="submitted",
        md5sum="5ot6ln",
        project_id="pmo7pt",
        state="released",
        state_comment="6665h3",
        submitter_id="submitted_aligned_reads1",
    ),
    models.SubmittedAlignedReads(
        node_id=get_node_id("submitted-aligned-reads-2"),
        acl=["phs000178"],
        data_category="Sequencing Reads",
        data_type="Aligned Reads",
        error_type="file_size",
        experimental_strategy="WGS",
        data_format="BAM",
        file_name="submitted_aligned_reads2.bam",
        file_size=3277108,
        file_state="submitted",
        md5sum="jo94nz",
        project_id="9q5ibr",
        state="released",
        state_comment="tl16c3",
        submitter_id="submitted_aligned_reads2",
    ),
    models.SubmittedAlignedReads(
        node_id=get_node_id("submitted-aligned-reads-without-downstream"),
        state="released",
        acl=["phs000178"],
        file_name="submitted-aligned-reads-without-downstream.bam",
    ),
    fuzzed(
        models.ReadGroupQc,
        node_id=get_node_id("read-group-qc-1"),
    ),
    fuzzed(
        models.ReadGroup,
        node_id=get_node_id("read-group-without-downstream"),
    ),
    models.ReadGroup(
        node_id=get_node_id("read-group-1"),
        adapter_name="j0o0ou",
        adapter_sequence="0ypboh",
        base_caller_name="7ycy5z",
        base_caller_version="ctfuts",
        experiment_name="o91rjj",
        flow_cell_barcode="rbqv3b",
        includes_spike_ins=True,
        instrument_model="454 GS FLX Titanium",
        is_paired_end=True,
        library_name="i3z5fz",
        library_preparation_kit_catalog_number="iyeuoq",
        library_preparation_kit_name="a51svh",
        library_preparation_kit_vendor="07yeqz",
        library_preparation_kit_version="e30pa1",
        library_selection="Hybrid Selection",
        library_strand="Unstranded",
        library_strategy="WGS",
        platform="Illumina",
        project_id="rmjpo8",
        read_group_name="1ros3k",
        read_length=4546829,
        sequencing_center="yzpdzm",
        sequencing_date="qisc3g",
        size_selection_range="7tl5qm",
        spike_ins_concentration="kdbjp1",
        spike_ins_fasta="0bxlsj",
        state="released",
        submitter_id="7yo0r1",
        target_capture_kit_catalog_number="lb3cvt",
        target_capture_kit_name="3gt57w",
        target_capture_kit_target_region="6o6lb3",
        target_capture_kit_vendor="es6bwd",
        target_capture_kit_version="nuoood",
        to_trim_adapter_sequence=False,
    ),
    models.ReadGroup(
        node_id=get_node_id("read-group-2"),
        state="released",
        project_id="TCGA-BRCA",
    ),
    models.Clinical(
        node_id=get_node_id("clinical-1"),
        state="released",
        project_id="TCGA-BRCA",
        age_at_diagnosis=34,
    ),
    models.Demographic(
        node_id=get_node_id("demographic-1"),
        project_id="TCGA-BRCA",
        ethnicity="hispanic or latino",
        state="released",
        gender="male",
        race="white",
        submitter_id="TCGA-AB-2846_demographicID1",
        year_of_birth=1951,
        year_of_death=-1,
    ),
    models.Exposure(
        node_id=get_node_id("exposure-1"),
        state="released",
        alcohol_history="Unknown",
        alcohol_intensity="Unknown",
        cigarettes_per_day=10.3,
        project_id="TCGA-BRCA",
        submitter_id="TCGA-49-AARO_exposure",
    ),
    models.FamilyHistory(
        node_id=get_node_id("family-history-1"),
        state="released",
        project_id="TCGA-DEV1",
        relationship_age_at_diagnosis=10,
        relationship_gender="male",
        relationship_primary_diagnosis="Colorectal Cancer",
        relationship_type="Nephew",
        submitter_id="TCGA-DEV-1-CASE-0011-FAMILY-HISTORY",
    ),
    models.Diagnosis(
        node_id=get_node_id("diagnosis-unknown-tumor-status"),
        state="released",
        age_at_diagnosis=47,
        classification_of_tumor="other",
        days_to_last_follow_up=-1,
        days_to_last_known_disease_status=-1,
        days_to_recurrence=-1,
        last_known_disease_status="Unknown tumor status",
        morphology="8255/3",
        primary_diagnosis="Abdominal fibromatosis",
        prior_malignancy="no",
        progression_or_recurrence="unknown",
        project_id="TCGA-BRCA",
        site_of_resection_or_biopsy="Abdominal esophagus",
        submitter_id="TCGA-49-AARO_diagnosis",
        tissue_or_organ_of_origin="Abdominal esophagus",
        tumor_grade="GB",
    ),
    models.Treatment(
        node_id=get_node_id("treatment-1"),
        state="released",
        days_to_treatment_end=None,
        project_id="TCGA-DEV3",
        submitter_id="TCGA-DEV-3-CASE-014-DIAG1-TR1",
        therapeutic_agents=None,
        treatment_intent_type=None,
        treatment_or_therapy="unknown",
    ),
    models.MolecularTest(
        node_id=get_node_id("molecular-test-1"),
        project_id="TCGA-BRCA",
        state="released",
        gene_symbol="CREBBP",
        molecular_analysis_method="FISH",
        test_result="Unknown",
    ),
    models.FollowUp(
        node_id=get_node_id("follow-up-1"),
        project_id="TCGA-BRCA",
        state="released",
        days_to_follow_up=888,
    ),
    models.Sample(
        node_id=get_node_id("sample-primary-tumor"),
        project_id="TCGA-BRCA",
        state="released",
        current_weight=None,
        days_to_collection=1416,
        days_to_sample_procurement=None,
        freezing_method=None,
        initial_weight=250.0,
        intermediate_dimension=None,
        longest_dimension=None,
        pathology_report_uuid="747FB91B-F523-4FA0-91DD-6014EF55643D",
        sample_type="Primary Tumor",
        shortest_dimension=None,
        submitter_id="TCGA-AR-A1AR-01A",
        time_between_clamping_and_freezing=None,
        time_between_excision_and_freezing=None,
        tumor_code_id=None,
    ),
    models.Aliquot(
        node_id=get_node_id("aliquot-1"),
        project_id="TCGA-BRCA",
        state="released",
        amount=13.0,
        concentration=0.18,
        source_center="23",
        submitter_id="TCGA-AR-A1AR-10A-01D-A133-02",
    ),
    models.Aliquot(
        node_id=get_node_id("aliquot-attached-to-sample"),
        project_id="TCGA-BRCA",
        state="released",
        amount=12.0,
        concentration=0.19,
        source_center="23",
        submitter_id="TCGA-AR-A1AR-10A-01D-A133-03",
    ),
    models.Analyte(
        node_id=get_node_id("analyte-repli-g-qiagen-dna"),
        project_id="TCGA-BRCA",
        state="released",
        a260_a280_ratio=None,
        amount=None,
        analyte_type="Repli-G (Qiagen) DNA",
        concentration=None,
        spectrophotometer_method=None,
        submitter_id="TCGA-AR-A1AR-01A-31W",
        well_number=None,
    ),
    models.Analyte(
        node_id=get_node_id("analyte-1"),
        project_id="TCGA-BRCA",
        a260_a280_ratio=1.94,
        state="released",
        amount=22.25,
        analyte_type="DNA",
        concentration=0.18,
        spectrophotometer_method="UV Spec",
        submitter_id="TCGA-AR-A1AR-10A-01D",
        well_number=None,
    ),
    models.Analyte(
        node_id=get_node_id("analyte-2"),
        project_id="TCGA-BRCA",
        state="released",
        a260_a280_ratio=None,
        amount=None,
        analyte_type="Repli-G (Qiagen) DNA",
        concentration=None,
        spectrophotometer_method=None,
        submitter_id="TCGA-AR-A1AR-10A-01W",
        well_number=None,
    ),
    models.Case(
        node_id=get_node_id("case-tcga-brca-breast"),
        project_id="TCGA-BRCA",
        state="released",
        submitter_id="TCGA-AR-A1AR",
        primary_site="Breast",
        disease_type="Blood Vessel Tumors",
    ),
    models.Case(
        node_id=get_node_id("unsubmitted-case"),
        project_id="TCGA-BRCA",
        state="validated",
        submitter_id="unsubmitted-case",
    ),
    models.Case(
        # floating case. has no neighbors
        node_id=get_node_id("case-floating-no-neighbours"),
        project_id="TCGA-BRCA",
        state="released",
        submitter_id="TCGA-AR-A2AR",
        primary_site="Breast",
        disease_type="Blood Vessel Tumors",
    ),
    models.Case(
        # released case in unreleased project
        node_id=get_node_id("released-case-in-unreleased-project"),
        project_id="INTERNAL-DEV1",
        state="released",
        submitter_id="INTERNAL-DEV-CASE-0001",
        primary_site="Bones, joints and articular cartilage of limbs",
        disease_type="Miscellaneous Bone Tumors",
    ),
    models.Case(
        # submitted case in AWG project
        node_id=get_node_id("submitted-awg-case"),
        project_id="INTERNAL-AWG-ONE",
        state="submitted",
        submitter_id="INTERNAL-AWG-ONE-CASE-0001",
        primary_site="Bones, joints and articular cartilage of limbs",
        disease_type="Miscellaneous Bone Tumors",
    ),
    models.Case(
        # released case in AWG project
        node_id=get_node_id("processed-awg-case"),
        project_id="INTERNAL-AWG-ONE",
        state="released",
        submitter_id="INTERNAL-AWG-ONE-CASE-0002",
        primary_site="Bones, joints and articular cartilage of limbs",
        disease_type="Miscellaneous Bone Tumors",
    ),
    models.Case(
        # fake case in fake active project
        node_id=get_node_id("fake_active_case_1"),
        project_id="TCGA-FAKE_ACTIVE",
        state="released",
        submitter_id="fake_submitter_1",
        primary_site="Prostate gland",
        disease_type="Adenomas and Adenocarcinomas",
    ),
    models.Case(
        # second fake case in fake active project
        node_id=get_node_id("fake_active_case_2"),
        project_id="TCGA-FAKE_ACTIVE",
        state="released",
        submitter_id="fake_submitter_2",
        primary_site="Rectum",
        disease_type="Adenomas and Adenocarcinomas",
    ),
    models.Case(
        # unreleased case in a released project
        node_id=get_node_id("unreleased-case-in-released-project"),
        project_id="TCGA-BRCA",
        state="submitted",
        submitter_id="unreleased_case_submitter_1",
        primary_site="Rectum",
        disease_type="Adenomas and Adenocarcinomas",
    ),
    models.Case(
        # TT-1044 blocking release
        node_id=get_node_id("blocking-release-case"),
        project_id="TCGA-BRCA",
        state="submitted",
        submitter_id="unreleased_case_submitter_2",
        primary_site="Rectum",
        disease_type="Adenomas and Adenocarcinomas",
    ),
    models.Case(
        # TT-1044 blocking release
        node_id=get_node_id("blocking-release-case-released"),
        project_id="TCGA-BRCA",
        state="submitted",
        submitter_id="unreleased_case_submitter_2",
        primary_site="Rectum",
        disease_type="Adenomas and Adenocarcinomas",
    ),
    models.Portion(
        node_id=get_node_id("portion-01"),
        project_id="TCGA-BRCA",
        creation_datetime=1293494400,
        state="released",
        is_ffpe=False,
        portion_number="01",
        submitter_id="TCGA-AR-A1AR-10A-01",
        weight=None,
    ),
    models.Aliquot(
        node_id=get_node_id("aliquot-2"),
        project_id="TCGA-BRCA",
        amount=6.67,
        state="released",
        concentration=0.18,
        source_center="23",
        submitter_id="TCGA-AR-A1AR-10A-01D-A134-01",
    ),
    models.Aliquot(
        node_id=get_node_id("aliquot-without-downstream"),
        project_id="TCGA-BRCA",
        state="released",
        amount=6.67,
        concentration=0.16,
        source_center="23",
        submitter_id="TCGA-AR-A1AR-01A-31D-A134-01",
    ),
    models.Aliquot(
        node_id=get_node_id("aliquot-3"),
        project_id="TCGA-BRCA",
        state="released",
        amount=20.0,
        concentration=0.16,
        source_center="23",
        submitter_id="TCGA-AR-A1AR-01A-31R-A136-13",
    ),
    models.Aliquot(
        node_id=get_node_id("aliquot-4"),
        project_id="TCGA-BRCA",
        state="released",
        amount=13.0,
        concentration=0.16,
        source_center="23",
        submitter_id="TCGA-AR-A1AR-01A-31D-A133-02",
    ),
    models.Analyte(
        node_id=get_node_id("analyte-dna"),
        project_id="TCGA-BRCA",
        state="released",
        a260_a280_ratio=1.98,
        amount=48.62,
        analyte_type="DNA",
        concentration=0.16,
        spectrophotometer_method="UV Spec",
        submitter_id="TCGA-AR-A1AR-01A-31D",
        well_number=None,
    ),
    models.Aliquot(
        node_id=get_node_id("aliquot-5"),
        project_id="TCGA-BRCA",
        state="released",
        amount=80.0,
        concentration=0.5,
        source_center="23",
        submitter_id="TCGA-AR-A1AR-10A-01W-A14P-09",
    ),
    models.Aliquot(
        node_id=get_node_id("aliquot-6"),
        project_id="TCGA-BRCA",
        state="released",
        amount=40.0,
        concentration=0.09,
        source_center="23",
        submitter_id="TCGA-AR-A1AR-10A-01D-A135-09",
    ),
    models.Aliquot(
        node_id=get_node_id("aliquot-7"),
        project_id="TCGA-BRCA",
        state="released",
        amount=26.7,
        concentration=0.16,
        source_center="23",
        submitter_id="TCGA-AR-A1AR-01A-31R-A137-07",
    ),
    models.Aliquot(
        node_id=get_node_id("aliquot-8"),
        project_id="TCGA-BRCA",
        state="released",
        amount=40.0,
        concentration=0.08,
        source_center="23",
        submitter_id="TCGA-AR-A1AR-01A-31D-A135-09",
    ),
    models.Slide(
        node_id=get_node_id("slide-top-1"),
        project_id="TCGA-BRCA",
        state="released",
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
        section_location="TOP",
        submitter_id="TCGA-AR-A1AR-01A-03-TSC",
    ),
    models.Aliquot(
        node_id=get_node_id("aliquot-9"),
        project_id="TCGA-BRCA",
        state="released",
        amount=26.7,
        concentration=0.16,
        source_center="23",
        submitter_id="TCGA-AR-A1AR-01A-31D-A138-05",
    ),
    models.Aliquot(
        node_id=get_node_id("aliquot-10"),
        project_id="TCGA-BRCA",
        state="released",
        amount=80.0,
        concentration=0.5,
        source_center="23",
        submitter_id="TCGA-AR-A1AR-01A-31W-A14P-09",
    ),
    models.Aliquot(
        node_id=get_node_id("aliquot-derived-from-unreleased-sample"),
        project_id="TCGA-BRCA",
        state="released",
        amount=80.0,
        concentration=0.5,
        source_center="23",
        submitter_id="TCGA-AR-A1AR-01A-31W-A14P-10",
    ),
    models.Portion(
        node_id=get_node_id("portion-31"),
        project_id="TCGA-BRCA",
        state="released",
        creation_datetime=1297728000,
        is_ffpe=False,
        portion_number="31",
        submitter_id="TCGA-AR-A1AR-01A-31",
        weight=30.0,
    ),
    models.Analyte(
        node_id=get_node_id("analyte-3"),
        project_id="TCGA-BRCA",
        state="released",
        a260_a280_ratio=1.82,
        amount=29.44,
        analyte_type="RNA",
        concentration=0.16,
        spectrophotometer_method="UV Spec",
        submitter_id="TCGA-AR-A1AR-01A-31R",
        well_number=None,
    ),
    models.Sample(
        node_id=get_node_id("sample-blood-derived-normal"),
        project_id="TCGA-BRCA",
        state="released",
        current_weight=None,
        days_to_collection=1416,
        days_to_sample_procurement=None,
        freezing_method=None,
        initial_weight=None,
        intermediate_dimension=None,
        longest_dimension=None,
        pathology_report_uuid="91C655D1-C777-41A9-B759-7ED12C72CF30",
        sample_type="Blood Derived Normal",
        shortest_dimension=None,
        submitter_id="TCGA-AR-A1AR-10A",
        time_between_clamping_and_freezing=None,
        time_between_excision_and_freezing=None,
        tumor_code_id=None,
    ),
    models.ProteinExpression(
        node_id=get_node_id("protein-expression-from-sample-released"),
        data_type="Protein Expression Quantification",
        state="released",
        acl=["phs000178"],
        submitter_id="protein-expression-from-sample-released",
        file_name="protein-expression-from-sample.tsv",
        data_category="Proteome Profiling",
        file_size=12345,
        md5sum=hashlib.md5(
            b"protein-expression-from-sample-released", usedforsecurity=False
        ).hexdigest(),
        data_format="TSV",
        platform="RPPA",
        project_id="TCGA-BRCA",
    ),
    models.Portion(
        node_id=get_node_id("protein-expression-portion"),
        project_id="TCGA-BRCA",
        creation_datetime=1293494401,
        state="released",
        is_ffpe=False,
        portion_number="01",
        submitter_id="protein-expression-portion",
        weight=None,
    ),
    models.ProteinExpression(
        node_id=get_node_id("protein-expression-from-portion-released"),
        data_type="Protein Expression Quantification",
        state="released",
        acl=["phs000178"],
        submitter_id="protein-expression-from-portion-released",
        file_name="protein-expression-from-portion.tsv",
        data_category="Proteome Profiling",
        file_size=23456,
        md5sum=hashlib.md5(
            b"protein-expression-from-portion-released", usedforsecurity=False
        ).hexdigest(),
        data_format="TSV",
        platform="RPPA",
        project_id="TCGA-BRCA",
    ),
    models.Sample(
        node_id=get_node_id("sample-unreleased"),
        project_id="TCGA-BRCA",
        state="submitted",
        current_weight=None,
        days_to_collection=1234,
        days_to_sample_procurement=None,
        freezing_method=None,
        intermediate_dimension=None,
        longest_dimension=None,
        pathology_report_uuid="ae0a5d09-2b5d-4ec5-9ff8-c591e0f77c83",
        sample_type="Additional Metastatic",
        shortest_dimension=None,
        submitter_id="TCGA-AR-A1AR-10A-02",
        time_between_clamping_and_freezing=None,
        time_between_excision_and_freezing=None,
        tumor_code_id=None,
    ),
    models.Annotation(
        node_id=get_node_id("annotation-approved-center-qc-failed"),
        category="Center QC failed",
        classification="CenterNotification",
        creator="test_creator",
        notes="RNA-seq:LOW 5/3 COVERAGE RATIO",
        state="released",
        status="Approved",
        submitter_id="0000",
    ),
    models.Annotation(
        node_id=get_node_id("rescinded-annotation"),
        state="released",
        status="Rescinded",
    ),
    models.Annotation(
        node_id=get_node_id("unreleased-annotation"),
        state="submitted",
        status="Approved",
    ),
    models.Annotation(
        node_id=get_node_id("rescinded-redaction-annotation"),
        category="Administrative Compliance",
        classification="Redaction",
        creator="annotator1",
        notes="Case temporarily redacted",
        state="released",
        submitter_id="18675",
        status="Rescinded",
    ),
    # TT-1044 blocking release
    models.Annotation(
        node_id=get_node_id("block-release-annotation"),
        state="submitted",
        status="Approved",
        classification="Blocking Release",
    ),
    models.Annotation(
        node_id=get_node_id("block-release-annotation-released"),
        state="released",
        status="Approved",
        classification="Blocking Release",
    ),
    models.Annotation(
        node_id=get_node_id("annotation-without-downstream"),
        state="released",
    ),
    fuzzed(
        models.SomaticMutationCallingWorkflow,
        node_id=get_node_id("somatic_mutation_calling_workflow_1"),
        state="released",
        workflow_type="SomaticSniper",
    ),
    fuzzed(
        models.SimpleSomaticMutation,
        node_id=get_node_id("somatic_mutation_1"),
        acl=["phs000178"],
        state="released",
        data_category="Combined Nucleotide Variation",
        file_name="somatic_mutation_1.vcf",
    ),
    fuzzed(
        models.BiospecimenSupplement,
        node_id=get_node_id("biospecimen_supplement_1"),
        acl=["phs000178"],
        data_category="Biospecimen",
        data_format="BCR XML",
        data_type="Biospecimen Supplement",
        file_name="nationwidechildrens.org_biospecimen.TCGA-A1-A1A1.xml",
        state="live",
    ),
    fuzzed(
        models.ClinicalSupplement,
        node_id=get_node_id("clinical_supplement_1"),
        acl=["phs000178"],
        data_category="Clinical",
        data_format="BCR XML",
        data_type="Clinical Supplement",
        file_name="nationwidechildrens.org_clinical.TCGA-A1-A1A1.xml",
        state="live",
    ),
    fuzzed(
        models.File,
        node_id=get_node_id("old-biospecimen-supplement-xml"),
        acl=["phs000178"],
        file_name="nationwidechildrens.org_biospecimen.TCGA-72-4234.xml",
        file_size=129165,
        md5sum="d7e6cbd40ef2f5b6607cb4af982280a9",
        state="live",
        file_state="submitted",
    ),
    fuzzed(
        models.SomaticAggregationWorkflow,
        node_id=get_node_id("somatic-aggregation-workflow-1"),
    ),
    fuzzed(
        models.AnnotatedSomaticMutation,
        node_id=get_node_id("annotated-somatic-mutation-2"),
        data_type="Annotated Somatic Mutation",
        file_name="annotated-somatic-mutation-2.vcf",
    ),
    fuzzed(
        models.AnnotatedSomaticMutation,
        node_id=get_node_id("annotated-somatic-mutation-3"),
        data_type="Annotated Somatic Mutation",
        file_name="annotated-somatic-mutation-3.vcf",
    ),
    fuzzed(
        models.AnnotatedSomaticMutation,
        node_id=get_node_id("annotated-somatic-mutation-4"),
        data_type="Annotated Somatic Mutation",
        file_name="annotated-somatic-mutation-4.vcf",
    ),
    fuzzed(
        models.AggregatedSomaticMutation,
        node_id=get_node_id("aggregated-somatic-mutation-1"),
        file_name="aggregated-somatic-mutation-1.vcf",
    ),
    models.File(
        node_id=get_node_id("slide-image-file"),
        file_name="TCGA-slide-file-1.svs",
        file_size=1245610777,
        md5sum="f03a67148479bccd32ac79c6181e5703",
        acl=["phs000178"],
        project_id="TCGA-BRCA",
        state="live",
        file_state="submitted",
    ),
    models.File(
        # SNV File: added for regression of removing case.files from the active
        # index
        node_id=get_node_id("snv-file"),
        acl=["phs000178"],
        created_datetime="2016-03-23T08:41:05.433262-05:00",
        file_name="genome.wustl.edu.TCGA-04-1332.snv.1aa2d1d8b9f44d7f9e15300c519bd419.vcf.gz",
        file_size=51758561,
        file_state="submitted",
        md5sum="645818642cfc77afb97cdb2975ccda2d",
        state="live",
        updated_datetime="2016-08-04T04:08:45.991704-05:00",
    ),
    # Methylation values
    models.SubmittedMethylationBetaValue(
        node_id=get_node_id("sub-methyl-beta-value"),
        acl=["open"],
        created_datetime="2016-09-29T22:03:22.817635+00:00",
        file_name="jhu-usc.edu_KIRC.HumanMethylation27.3.lvl-3.TCGA-BP-4761-11A-01D-1284-05.txt",
        data_category="DNA Methylation",
        data_type="Methylation Beta Value",
        data_format="TXT",
        experimental_strategy="Methylation Array",
        file_size=1283108,
        file_state="processed",
        md5sum="c5693b0ed22bfea43ed76f4b21c685e4",
        platform="Illumina Human Methylation 27",
        state="released",
        updated_datetime="2016-09-29T22:03:22.817635+00:00",
    ),
    models.MethylationLiftoverWorkflow(
        node_id=get_node_id("methyl-lift-wf"),
        workflow_type="Liftover",
        state="released",
        acl=["open"],
    ),
    models.MethylationBetaValue(
        node_id=get_node_id("methyl-beta-value"),
        acl=["open"],
        state="released",
        created_datetime="2016-09-29T22:03:22.817635+00:00",
        data_category="DNA Methylation",
        data_type="Methylation Beta Value",
        data_format="TXT",
        experimental_strategy="Methylation Array",
        file_name="jhu-usc.edu_KIRC.HumanMethylation27.3.lvl-3.TCGA-BP-4761-11A-01D-1284-05.gdc_hg38.txt",
        file_size=9952417,
        file_state="processed",
        platform="Illumina Human Methylation 27",
        md5sum="d7f89b0eeb11f7b1b119b8c301b50f86",
        updated_datetime="2016-09-29T22:03:22.817635+00:00",
    ),
    # Prelude nodes
    models.DataSubtype(
        node_id=get_node_id("data_subtype_aligned_reads"),
        name="Aligned reads",
    ),
    models.DataType(
        node_id=get_node_id("data_type_raw_sequencing"),
        name="Raw sequencing data",
    ),
    models.Platform(
        node_id=get_node_id("platform-illumina-hiseq"),
        name="Illumina HiSeq",
    ),
    models.ExperimentalStrategy(
        node_id=get_node_id("experimental-strategy-rna-seq"), name="RNA-Seq"
    ),
    models.Tag(
        node_id=get_node_id("tag-snv"),
        name="snv",
    ),
    models.Program(
        node_id=get_node_id("program-tcga"),
        dbgap_accession_number="phs000178",
        name="TCGA",
    ),
    models.Program(
        node_id=get_node_id("internal-program"),
        dbgap_accession_number="gdc000000",
        name="INTERNAL",
    ),
    models.Center(
        node_id=get_node_id("center-unc-edu"),
        code="07",
        namespace="unc.edu",
        name="University of North Carolina",
        short_name="UNC",
        center_type="CGCC",
    ),
    models.Center(
        node_id=get_node_id("center-broad-mit-edu"),
        code="01",
        namespace="broad.mit.edu",
        name="Broad Institute of MIT and Harvard",
        short_name="BI",
        center_type="CGCC",
    ),
    models.TissueSourceSite(
        node_id=get_node_id("tissue-source-site-breast-invasive-carcinoma"),
        project="Breast invasive carcinoma",
        bcr_id="NCH",
        code="AR",
        name="Mayo",
    ),
    models.Center(
        node_id=get_node_id("center-hms-harvard-edu"),
        code="02",
        namespace="hms.harvard.edu",
        name="Harvard Medical School",
        short_name="HMS",
        center_type="CGCC",
    ),
    models.Center(
        node_id=get_node_id("center-jhu-usc-edu"),
        code="05",
        namespace="jhu-usc.edu",
        name="Johns Hopkins / University of Southern California",
        short_name="JHU_USC",
        center_type="CGCC",
    ),
    models.Project(
        node_id=get_node_id("project-legacy-brca"),
        released=True,
        state="legacy",
        awg_review=False,
        code="BRCA",
        dbgap_accession_number=None,
        name="Breast Invasive Carcinoma",
    ),
    models.Project(
        node_id=get_node_id("fake_active_project"),
        released=True,
        state="open",
        awg_review=False,
        code="FAKE_ACTIVE",
        dbgap_accession_number=None,
        name="Made up active project",
    ),
    models.Project(
        node_id=get_node_id("unreleased-project"),
        released=False,
        state="open",
        awg_review=False,
        code="DEV1",
        dbgap_accession_number="gdc000001",
        name="Dev project",
    ),
    models.Project(
        node_id=get_node_id("awg-one-project"),
        released=False,
        state="open",
        awg_review=True,
        code="AWG-ONE",
        dbgap_accession_number=None,
        name="AWG project",
    ),
    models.Center(
        node_id=get_node_id("center-bcgsc-ca"),
        code="13",
        namespace="bcgsc.ca",
        name="Canada's Michael Smith Genome Sciences Centre",
        short_name="BCGSC",
        center_type="CGCC",
    ),
    models.Center(
        node_id=get_node_id("center-genome-wustl-ed"),
        center_type="GSC",
        code="09",
        name="Washington University School of Medicine",
        namespace="genome.wustl.ed",
        short_name="WUSM",
    ),
    # TT-1053 index redactions
    models.Annotation(
        node_id=get_node_id("redaction-annotation"),
        category="Administrative Compliance",
        classification="Redaction",
        creator="annotator1",
        notes="Case temporarily redacted",
        state="released",
        submitter_id="18675",
        status="Approved",
    ),
    models.Case(
        node_id=get_node_id("redaction-case-released"),
        project_id="TCGA-BRCA",
        state="released",
        submitter_id="released_case_submitter_2",
        primary_site="Rectum",
        disease_type="Adenomas and Adenocarcinomas",
    ),
    models.Annotation(
        node_id=get_node_id("withdrew-consent-annotation"),
        category="Subject withdrew consent",
        classification="Redaction",
        creator="annotator1",
        notes="Test subject withdrew consent",
        state="released",
        submitter_id="18675",
        status="Approved",
    ),
    models.Case(
        node_id=get_node_id("withdrew-consent-case-released"),
        project_id="TCGA-BRCA",
        state="released",
        submitter_id="released_case_submitter_2",
        primary_site="Rectum",
        disease_type="Adenomas and Adenocarcinomas",
    ),
    models.Annotation(
        node_id=get_node_id("released-rescinded-annotation"),
        category="Administrative Compliance",
        classification="Redaction",
        creator="annotator1",
        notes="Testing annotation released and rescinded",
        state="released",
        submitter_id="18675",
        status="Rescinded",
    ),
    models.Case(
        node_id=get_node_id("released-rescinded-case"),
        project_id="TCGA-BRCA",
        state="released",
        submitter_id="released_case_submitter_2",
        primary_site="Rectum",
        disease_type="Adenomas and Adenocarcinomas",
    ),
    models.Sample(
        node_id=get_node_id("tt-260-sample"),
        project_id="TCGA-BRCA",
        submitter_id="TT-260-SAMPLE",
        state="released",
    ),
    models.Portion(
        node_id=get_node_id("tt-260-portion"),
        project_id="TCGA-BRCA",
        state="released",
        submitter_id="TT-260-PORTION",
    ),
    models.Analyte(
        node_id=get_node_id("tt-260-analyte"),
        state="released",
        project_id="TCGA-BRCA",
        submitter_id="TT-260-ANALYTE",
    ),
    models.Aliquot(
        node_id=get_node_id("tt-260-aliquot"),
        state="released",
        project_id="TCGA-BRCA",
        submitter_id="TT-260-ALIQUOT",
    ),
    # DAT-2619
    # data_file skipped because of 'submitted_*' label
    fuzzed(
        models.SubmittedGenomicProfile,
        node_id=get_node_id("submitted-genomic-profile-released-1"),
        data_category="Genomic Profiling",
        file_name="submitted-genomic-profile-released-1.ext",
    ),
    # data_file skipped because of 'submitted_*' label
    fuzzed(
        models.SubmittedGenomicProfile,
        node_id=get_node_id("submitted-genomic-profile-released-2"),
        data_category="Genomic Profiling",
        file_name="submitted-genomic-profile-released-2.ext",
    ),
    # data_file skipped because of 'submitted_*' label and state
    fuzzed(
        models.SubmittedGenomicProfile,
        node_id=get_node_id("submitted-genomic-profile-submitted"),
        data_category="Genomic Profiling",
        state="submitted",
        file_name="submitted-genomic-profile-submitted.ext",
    ),
    fuzzed(
        models.GenomicProfileHarmonizationWorkflow,
        node_id=get_node_id("gen-profile-harmonization-released-1"),
        workflow_type="GENIE Copy Number Variation",
    ),
    fuzzed(
        models.GenomicProfileHarmonizationWorkflow,
        node_id=get_node_id("gen-profile-harmonization-released-2"),
        workflow_type="GENIE Simple Somatic Mutation",
    ),
    fuzzed(
        models.GenomicProfileHarmonizationWorkflow,
        node_id=get_node_id("gen-profile-harmonization-released-3"),
        workflow_type="GENIE Structural Variation",
    ),
    fuzzed(
        models.GenomicProfileHarmonizationWorkflow,
        node_id=get_node_id("gen-profile-harmonization-submitted"),
        workflow_type="GENIE Structural Variation",
    ),
    # data_file indexed
    fuzzed(
        models.AnnotatedSomaticMutation,
        node_id=get_node_id("genie-vcf-released"),
        data_type="Annotated Somatic Mutation",
        file_name="genie-vcf-released.vcf",
    ),
    # data_file indexed
    fuzzed(
        models.CopyNumberEstimate,
        node_id=get_node_id("genie-cne-released"),
        data_category="Copy Number Variation",
        file_name="genie-cne-released.ext",
    ),
    # data_file indexed
    fuzzed(
        models.StructuralVariation,
        node_id=get_node_id("genie-struct-var-released"),
        data_type="Structural Alteration",
        data_category="Somatic Structural Variation",
        file_name="genie-struct-var-released.ext",
    ),
    # data_file skipped because upstream isn't released
    fuzzed(
        models.StructuralVariation,
        node_id=get_node_id("genie-struct-var-submitted"),
        data_type="Structural Alteration",
        data_category="Somatic Structural Variation",
        file_name="genie-struct-var-submitted.ext",
    ),
)


EDGES = (
    models.SampleDerivedFromCase(
        src_id=get_node_id("tt-260-sample"),
        dst_id=get_node_id("fake_active_case_2"),
    ),
    models.PortionDerivedFromSample(
        src_id=get_node_id("tt-260-portion"),
        dst_id=get_node_id("tt-260-sample"),
    ),
    models.AnalyteDerivedFromSample(
        src_id=get_node_id("tt-260-analyte"),
        dst_id=get_node_id("tt-260-sample"),
    ),
    models.AliquotDerivedFromAnalyte(
        src_id=get_node_id("tt-260-aliquot"),
        dst_id=get_node_id("tt-260-analyte"),
    ),
    # Somatic mutation workflows
    models.SomaticAggregationWorkflowPerformedOnAnnotatedSomaticMutation(
        src_id=get_node_id("somatic-aggregation-workflow-1"),
        dst_id=get_node_id("annotated_somatic_mutation_1"),
    ),
    models.SomaticAggregationWorkflowPerformedOnAnnotatedSomaticMutation(
        src_id=get_node_id("somatic-aggregation-workflow-1"),
        dst_id=get_node_id("annotated-somatic-mutation-2"),
    ),
    models.SomaticAggregationWorkflowPerformedOnAnnotatedSomaticMutation(
        src_id=get_node_id("somatic-aggregation-workflow-1"),
        dst_id=get_node_id("annotated-somatic-mutation-3"),
    ),
    models.SomaticAggregationWorkflowPerformedOnAnnotatedSomaticMutation(
        src_id=get_node_id("somatic-aggregation-workflow-1"),
        dst_id=get_node_id("annotated-somatic-mutation-4"),
    ),
    models.AggregatedSomaticMutationDataFromSomaticAggregationWorkflow(
        src_id=get_node_id("aggregated-somatic-mutation-1"),
        dst_id=get_node_id("somatic-aggregation-workflow-1"),
    ),
    models.AnnotatedSomaticMutationDataFromSomaticAnnotationWorkflow(
        src_id=get_node_id("annotated_somatic_mutation_1"),
        dst_id=get_node_id("somatic_annotation_workflow_1"),
    ),
    models.SomaticAnnotationWorkflowPerformedOnSimpleSomaticMutation(
        src_id=get_node_id("somatic_annotation_workflow_1"),
        dst_id=get_node_id("simple_somatic_mutation_1"),
    ),
    models.SimpleSomaticMutationDataFromSomaticMutationCallingWorkflow(
        src_id=get_node_id("simple_somatic_mutation_1"),
        dst_id=get_node_id("somatic_mutation_calling_workflow_1"),
    ),
    models.SomaticMutationCallingWorkflowPerformedOnAlignedReads(
        src_id=get_node_id("somatic_mutation_calling_workflow_1"),
        dst_id=get_node_id("aligned-reads-1"),
    ),
    models.SomaticMutationCallingWorkflowPerformedOnAlignedReads(
        src_id=get_node_id("somatic_mutation_calling_workflow_1"),
        dst_id=get_node_id("aligned-reads-2"),
    ),
    # Supplement nodes
    models.FileDescribesCase(
        src_id=get_node_id("old-biospecimen-supplement-xml"),
        dst_id=get_node_id("case-tcga-brca-breast"),
    ),
    models.BiospecimenSupplementDerivedFromCase(
        src_id=get_node_id("biospecimen_supplement_1"),
        dst_id=get_node_id("case-tcga-brca-breast"),
    ),
    models.AnnotationAnnotatesCase(
        src_id=get_node_id("rescinded-redaction-annotation"),
        dst_id=get_node_id("case-tcga-brca-breast"),
    ),
    # TT-1044 blocking release
    models.AnnotationAnnotatesCase(
        src_id=get_node_id("block-release-annotation"),
        dst_id=get_node_id("blocking-release-case"),
    ),
    # TT-1044 blocking release
    models.AnnotationAnnotatesCase(
        src_id=get_node_id("block-release-annotation-released"),
        dst_id=get_node_id("blocking-release-case-released"),
    ),
    models.AnnotationAnnotatesCase(
        src_id=get_node_id("unreleased-annotation"),
        dst_id=get_node_id("unreleased-case-in-released-project"),
    ),
    models.ClinicalSupplementDerivedFromCase(
        src_id=get_node_id("clinical_supplement_1"),
        dst_id=get_node_id("case-tcga-brca-breast"),
    ),
    # Read Groups
    models.ReadGroupQcGeneratedFromReadGroup(
        src_id=get_node_id("read-group-qc-1"),
        dst_id=get_node_id("read-group-1"),
    ),
    models.ReadGroupDerivedFromAliquot(
        src_id=get_node_id("read-group-1"),
        dst_id=get_node_id("aliquot-1"),
    ),
    models.ReadGroupDerivedFromAliquot(
        src_id=get_node_id("read-group-without-downstream"),
        dst_id=get_node_id("aliquot-without-downstream"),
    ),
    models.SubmittedAlignedReadsDataFromReadGroup(
        src_id=get_node_id("submitted-aligned-reads-without-downstream"),
        dst_id=get_node_id("read-group-without-downstream"),
    ),
    models.ReadGroupDerivedFromAliquot(
        src_id=get_node_id("read-group-2"),
        dst_id=get_node_id("aliquot-2"),
    ),
    # Aligned Reads
    models.SubmittedAlignedReadsDataFromReadGroup(
        src_id=get_node_id("submitted-aligned-reads-1"),
        dst_id=get_node_id("read-group-1"),
    ),
    models.SubmittedAlignedReadsDataFromReadGroup(
        src_id=get_node_id("submitted-aligned-reads-2"),
        dst_id=get_node_id("read-group-2"),
    ),
    models.AlignmentCocleaningWorkflowPerformedOnSubmittedAlignedReads(
        src_id=get_node_id("alignment_cocleaning_wf"),
        dst_id=get_node_id("submitted-aligned-reads-1"),
    ),
    models.AlignmentCocleaningWorkflowPerformedOnSubmittedAlignedReads(
        src_id=get_node_id("alignment_cocleaning_wf"),
        dst_id=get_node_id("submitted-aligned-reads-2"),
    ),
    models.AlignedReadsDataFromAlignmentCocleaningWorkflow(
        src_id=get_node_id("aligned-reads-1"),
        dst_id=get_node_id("alignment_cocleaning_wf"),
    ),
    models.AlignedReadsDataFromAlignmentCocleaningWorkflow(
        src_id=get_node_id("aligned-reads-2"),
        dst_id=get_node_id("alignment_cocleaning_wf"),
    ),
    models.AlignedReadsDataFromAlignmentCocleaningWorkflow(
        src_id=get_node_id("active-file-with-empty-acl"),
        dst_id=get_node_id("alignment_cocleaning_wf"),
    ),
    models.AlignedReadsMatchedToSubmittedAlignedReads(
        src_id=get_node_id("aligned-reads-1"),
        dst_id=get_node_id("submitted-aligned-reads-1"),
    ),
    models.AlignedReadsMatchedToSubmittedAlignedReads(
        src_id=get_node_id("aligned-reads-2"),
        dst_id=get_node_id("submitted-aligned-reads-2"),
    ),
    # Clinical
    models.ExposureDescribesCase(
        src_id=get_node_id("exposure-1"),
        dst_id=get_node_id("case-tcga-brca-breast"),
    ),
    models.DiagnosisDescribesCase(
        src_id=get_node_id("diagnosis-unknown-tumor-status"),
        dst_id=get_node_id("case-tcga-brca-breast"),
    ),
    models.TreatmentDescribesDiagnosis(
        src_id=get_node_id("treatment-1"),
        dst_id=get_node_id("diagnosis-unknown-tumor-status"),
    ),
    models.DemographicDescribesCase(
        src_id=get_node_id("demographic-1"),
        dst_id=get_node_id("case-tcga-brca-breast"),
    ),
    models.FamilyHistoryDescribesCase(
        src_id=get_node_id("family-history-1"),
        dst_id=get_node_id("case-tcga-brca-breast"),
    ),
    models.ClinicalDescribesCase(
        src_id=get_node_id("clinical-1"),
        dst_id=get_node_id("case-tcga-brca-breast"),
    ),
    # Legacy edges
    models.FileMemberOfArchive(
        src_id=get_node_id("file-only-attached-to-archive-1"),
        dst_id=get_node_id("archive_1"),
    ),
    models.BiospecimenSupplementMemberOfArchive(
        src_id=get_node_id("biospecimen_supplement_1"),
        dst_id=get_node_id("archive_1"),
    ),
    models.ClinicalSupplementMemberOfArchive(
        src_id=get_node_id("clinical_supplement_1"),
        dst_id=get_node_id("archive_1"),
    ),
    models.AnnotationAnnotatesAliquot(
        src_id=get_node_id("annotation-approved-center-qc-failed"),
        dst_id=get_node_id("aliquot-1"),
    ),
    models.AnnotationAnnotatesAliquot(
        src_id=get_node_id("annotation-without-downstream"),
        dst_id=get_node_id("aliquot-without-downstream"),
    ),
    models.AnnotationAnnotatesAliquot(
        src_id=get_node_id("annotation-without-downstream"),
        dst_id=get_node_id("aliquot-without-downstream"),
    ),
    models.AnnotationAnnotatesAliquot(
        src_id=get_node_id("rescinded-annotation"),
        dst_id=get_node_id("aliquot-1"),
    ),
    models.FileMemberOfDataSubtype(
        src_id=get_node_id("live-file"),
        dst_id=get_node_id("data_subtype_aligned_reads"),
    ),
    models.FileRelatedToFile(
        src_id=get_node_id("live-file"),
        dst_id=get_node_id("index-file"),
    ),
    models.AlignedReadsIndexDerivedFromAlignedReads(
        src_id=get_node_id("index-file-2"),
        dst_id=get_node_id("aligned-reads-1"),
    ),
    models.FileRelatedToFile(
        src_id=get_node_id("live-file"),
        dst_id=get_node_id("related-file"),
    ),
    models.FileDataFromSlide(
        src_id=get_node_id("slide-image-file"),
        dst_id=get_node_id("slide-top-1"),
    ),
    models.FileDataFromAliquot(
        src_id=get_node_id("live-file"),
        dst_id=get_node_id("aliquot-1"),
    ),
    models.FileDataFromAliquot(
        src_id=get_node_id("legacy-file-with-empty-acl"),
        dst_id=get_node_id("aliquot-1"),
    ),
    models.FileDataFromAliquot(
        src_id=get_node_id("harmonized-file"),
        dst_id=get_node_id("aliquot-1"),
    ),
    models.FileDataFromFile(
        src_id=get_node_id("harmonized-file"),
        dst_id=get_node_id("live-file"),
    ),
    models.FileDataFromAliquot(
        src_id=get_node_id("non-live-file"),
        dst_id=get_node_id("aliquot-1"),
    ),
    models.FileDataFromAliquot(
        src_id=get_node_id("to-delete-file"),
        dst_id=get_node_id("aliquot-1"),
    ),
    models.FileDataFromAliquot(
        src_id=get_node_id("related-file"),
        dst_id=get_node_id("aliquot-1"),
    ),
    models.AliquotDerivedFromAnalyte(
        src_id=get_node_id("aliquot-9"),
        dst_id=get_node_id("analyte-dna"),
    ),
    models.AliquotDerivedFromSample(
        src_id=get_node_id("aliquot-attached-to-sample"),
        dst_id=get_node_id("sample-blood-derived-normal"),
    ),
    models.AliquotDerivedFromSample(
        src_id=get_node_id("aliquot-derived-from-unreleased-sample"),
        dst_id=get_node_id("sample-unreleased"),
    ),
    models.AliquotShippedToCenter(
        src_id=get_node_id("aliquot-6"),
        dst_id=get_node_id("center-genome-wustl-ed"),
    ),
    models.AliquotShippedToCenter(
        src_id=get_node_id("aliquot-3"),
        dst_id=get_node_id("center-bcgsc-ca"),
    ),
    models.AliquotShippedToCenter(
        src_id=get_node_id("aliquot-5"),
        dst_id=get_node_id("center-genome-wustl-ed"),
    ),
    models.AnalyteDerivedFromPortion(
        src_id=get_node_id("analyte-2"), dst_id=get_node_id("portion-01"), properties={}
    ),
    models.AliquotDerivedFromAnalyte(
        src_id=get_node_id("aliquot-5"), dst_id=get_node_id("analyte-2"), properties={}
    ),
    models.AnalyteDerivedFromPortion(
        src_id=get_node_id("analyte-dna"),
        dst_id=get_node_id("portion-31"),
    ),
    models.FileDataFromCase(
        # Added for regression of removing case.files from the active
        # index
        src_id=get_node_id("snv-file"),
        dst_id=get_node_id("case-tcga-brca-breast"),
    ),
    models.SampleDerivedFromCase(
        src_id=get_node_id("sample-blood-derived-normal"),
        dst_id=get_node_id("case-tcga-brca-breast"),
    ),
    models.SampleDerivedFromCase(
        src_id=get_node_id("sample-unreleased"),
        dst_id=get_node_id("unreleased-case-in-released-project"),
    ),
    models.AliquotShippedToCenter(
        src_id=get_node_id("aliquot-8"),
        dst_id=get_node_id("center-genome-wustl-ed"),
    ),
    models.SlideDerivedFromPortion(
        src_id=get_node_id("slide-top-1"),
        dst_id=get_node_id("portion-31"),
    ),
    models.CaseMemberOfProject(
        src_id=get_node_id("case-tcga-brca-breast"),
        dst_id=get_node_id("project-legacy-brca"),
    ),
    models.CaseMemberOfProject(
        src_id=get_node_id("unsubmitted-case"),
        dst_id=get_node_id("project-legacy-brca"),
    ),
    models.CaseMemberOfProject(
        src_id=get_node_id("released-case-in-unreleased-project"),
        dst_id=get_node_id("unreleased-project"),
    ),
    models.CaseMemberOfProject(
        src_id=get_node_id("submitted-awg-case"),
        dst_id=get_node_id("awg-one-project"),
    ),
    models.CaseMemberOfProject(
        src_id=get_node_id("processed-awg-case"),
        dst_id=get_node_id("awg-one-project"),
    ),
    models.AliquotDerivedFromSample(
        src_id=get_node_id("aliquot-6"),
        dst_id=get_node_id("sample-blood-derived-normal"),
    ),
    models.AliquotShippedToCenter(
        src_id=get_node_id("aliquot-9"),
        dst_id=get_node_id("center-jhu-usc-edu"),
    ),
    models.AliquotDerivedFromAnalyte(
        src_id=get_node_id("aliquot-1"), dst_id=get_node_id("analyte-1"), properties={}
    ),
    models.AliquotDerivedFromAnalyte(
        src_id=get_node_id("aliquot-8"),
        dst_id=get_node_id("analyte-dna"),
    ),
    models.AnalyteDerivedFromPortion(
        src_id=get_node_id("analyte-repli-g-qiagen-dna"),
        dst_id=get_node_id("portion-31"),
    ),
    models.AliquotDerivedFromSample(
        src_id=get_node_id("aliquot-1"),
        dst_id=get_node_id("sample-blood-derived-normal"),
    ),
    models.AliquotDerivedFromSample(
        src_id=get_node_id("aliquot-8"),
        dst_id=get_node_id("sample-primary-tumor"),
    ),
    models.AliquotShippedToCenter(
        src_id=get_node_id("aliquot-1"),
        dst_id=get_node_id("center-hms-harvard-edu"),
    ),
    models.AliquotDerivedFromAnalyte(
        src_id=get_node_id("aliquot-6"), dst_id=get_node_id("analyte-1"), properties={}
    ),
    models.AliquotDerivedFromAnalyte(
        src_id=get_node_id("aliquot-4"),
        dst_id=get_node_id("analyte-dna"),
    ),
    models.AliquotDerivedFromAnalyte(
        src_id=get_node_id("aliquot-2"),
        dst_id=get_node_id("analyte-dna"),
    ),
    models.CaseProcessedAtTissueSourceSite(
        src_id=get_node_id("case-tcga-brca-breast"),
        dst_id=get_node_id("tissue-source-site-breast-invasive-carcinoma"),
    ),
    models.AliquotDerivedFromSample(
        src_id=get_node_id("aliquot-without-downstream"),
        dst_id=get_node_id("sample-primary-tumor"),
    ),
    models.AliquotDerivedFromSample(
        src_id=get_node_id("aliquot-3"),
        dst_id=get_node_id("sample-primary-tumor"),
    ),
    models.AliquotDerivedFromAnalyte(
        src_id=get_node_id("aliquot-without-downstream"),
        dst_id=get_node_id("analyte-dna"),
    ),
    models.AliquotDerivedFromSample(
        src_id=get_node_id("aliquot-5"),
        dst_id=get_node_id("sample-blood-derived-normal"),
    ),
    models.AliquotDerivedFromSample(
        src_id=get_node_id("aliquot-2"),
        dst_id=get_node_id("sample-primary-tumor"),
    ),
    models.AliquotDerivedFromSample(
        src_id=get_node_id("aliquot-10"),
        dst_id=get_node_id("sample-primary-tumor"),
    ),
    models.PortionDerivedFromSample(
        src_id=get_node_id("portion-31"),
        dst_id=get_node_id("sample-primary-tumor"),
    ),
    models.PortionDerivedFromSample(
        src_id=get_node_id("portion-01"),
        dst_id=get_node_id("sample-blood-derived-normal"),
    ),
    models.AliquotDerivedFromSample(
        src_id=get_node_id("aliquot-4"),
        dst_id=get_node_id("sample-primary-tumor"),
    ),
    models.AliquotDerivedFromAnalyte(
        src_id=get_node_id("aliquot-3"), dst_id=get_node_id("analyte-3"), properties={}
    ),
    models.AnalyteDerivedFromPortion(
        src_id=get_node_id("analyte-3"), dst_id=get_node_id("portion-31"), properties={}
    ),
    models.AliquotShippedToCenter(
        src_id=get_node_id("aliquot-without-downstream"),
        dst_id=get_node_id("center-broad-mit-edu"),
    ),
    models.AliquotShippedToCenter(
        src_id=get_node_id("aliquot-7"),
        dst_id=get_node_id("center-unc-edu"),
    ),
    models.SampleDerivedFromCase(
        src_id=get_node_id("sample-primary-tumor"),
        dst_id=get_node_id("case-tcga-brca-breast"),
    ),
    models.AliquotDerivedFromAnalyte(
        src_id=get_node_id("aliquot-7"), dst_id=get_node_id("analyte-3"), properties={}
    ),
    models.AliquotShippedToCenter(
        src_id=get_node_id("aliquot-2"),
        dst_id=get_node_id("center-broad-mit-edu"),
    ),
    models.AnalyteDerivedFromPortion(
        src_id=get_node_id("analyte-1"), dst_id=get_node_id("portion-01"), properties={}
    ),
    models.AliquotShippedToCenter(
        src_id=get_node_id("aliquot-4"),
        dst_id=get_node_id("center-hms-harvard-edu"),
    ),
    models.AliquotDerivedFromAnalyte(
        src_id=get_node_id("aliquot-10"),
        dst_id=get_node_id("analyte-repli-g-qiagen-dna"),
    ),
    models.AliquotDerivedFromSample(
        src_id=get_node_id("aliquot-9"),
        dst_id=get_node_id("sample-primary-tumor"),
    ),
    models.AliquotShippedToCenter(
        src_id=get_node_id("aliquot-10"),
        dst_id=get_node_id("center-genome-wustl-ed"),
    ),
    models.AliquotDerivedFromSample(
        src_id=get_node_id("aliquot-7"),
        dst_id=get_node_id("sample-primary-tumor"),
    ),
    models.AnalysisMetadataDerivedFromFile(
        src_id=get_node_id("analysis-metadata-1"),
        dst_id=get_node_id("live-file"),
    ),
    # Somatic Mutation Calling
    models.SimpleSomaticMutationDataFromSomaticMutationCallingWorkflow(
        src_id=get_node_id("somatic_mutation_1"),
        dst_id=get_node_id("somatic_mutation_calling_workflow_1"),
    ),
    models.SomaticMutationCallingWorkflowPerformedOnAlignedReads(
        src_id=get_node_id("somatic_mutation_calling_workflow_1"),
        dst_id=get_node_id("aligned-reads-1"),
    ),
    # SRA metadata
    models.RunMetadataDerivedFromFile(
        src_id=get_node_id("run-metadata-1"),
        dst_id=get_node_id("live-file"),
    ),
    models.ExperimentMetadataDerivedFromFile(
        src_id=get_node_id("experiment-metadata-1"),
        dst_id=get_node_id("live-file"),
    ),
    # Copy Number
    models.SubmittedTangentCopyNumberDerivedFromAliquot(
        src_id=get_node_id("cnv-file-1"),
        dst_id=get_node_id("aliquot-1"),
    ),
    models.CopyNumberLiftoverWorkflowPerformedOnSubmittedTangentCopyNumber(
        src_id=get_node_id("cnv-workflow-1"),
        dst_id=get_node_id("cnv-file-1"),
    ),
    models.CopyNumberSegmentDerivedFromCopyNumberLiftoverWorkflow(
        src_id=get_node_id("cnv-segment-file-1"),
        dst_id=get_node_id("cnv-workflow-1"),
    ),
    models.SubmittedMethylationBetaValueDerivedFromAliquot(
        src_id=get_node_id("sub-methyl-beta-value"),
        dst_id=get_node_id("aliquot-1"),
    ),
    models.MethylationLiftoverWorkflowPerformedOnSubmittedMethylationBetaValue(
        src_id=get_node_id("methyl-lift-wf"),
        dst_id=get_node_id("sub-methyl-beta-value"),
    ),
    models.MethylationBetaValueDataFromMethylationLiftoverWorkflow(
        src_id=get_node_id("methyl-beta-value"),
        dst_id=get_node_id("methyl-lift-wf"),
    ),
    # Prelude
    models.DataSubtypeMemberOfDataType(
        src_id=get_node_id("data_subtype_aligned_reads"),
        dst_id=get_node_id("data_type_raw_sequencing"),
    ),
    models.ProjectMemberOfProgram(
        src_id=get_node_id("project-legacy-brca"),
        dst_id=get_node_id("program-tcga"),
    ),
    models.ProjectMemberOfProgram(
        src_id=get_node_id("unreleased-project"),
        dst_id=get_node_id("internal-program"),
    ),
    models.ProjectMemberOfProgram(
        src_id=get_node_id("awg-one-project"),
        dst_id=get_node_id("internal-program"),
    ),
    #  Ticket API-188
    models.ProjectMemberOfProgram(
        src_id=get_node_id("fake_active_project"),
        dst_id=get_node_id("program-tcga"),
    ),
    models.CaseMemberOfProject(
        src_id=get_node_id("fake_active_case_1"),
        dst_id=get_node_id("fake_active_project"),
    ),
    models.CaseMemberOfProject(
        src_id=get_node_id("fake_active_case_2"),
        dst_id=get_node_id("fake_active_project"),
    ),
    models.CaseMemberOfProject(
        src_id=get_node_id("unreleased-case-in-released-project"),
        dst_id=get_node_id("fake_active_project"),
    ),
    models.CaseMemberOfProject(
        src_id=get_node_id("blocking-release-case"),
        dst_id=get_node_id("fake_active_project"),
    ),
    models.CaseMemberOfProject(
        src_id=get_node_id("blocking-release-case-released"),
        dst_id=get_node_id("fake_active_project"),
    ),
    # TT-1053 index redactions
    models.AnnotationAnnotatesCase(
        src_id=get_node_id("redaction-annotation"),
        dst_id=get_node_id("redaction-case-released"),
    ),
    models.CaseMemberOfProject(
        src_id=get_node_id("redaction-case-released"),
        dst_id=get_node_id("fake_active_project"),
    ),
    models.AnnotationAnnotatesCase(
        src_id=get_node_id("withdrew-consent-annotation"),
        dst_id=get_node_id("withdrew-consent-case-released"),
    ),
    models.CaseMemberOfProject(
        src_id=get_node_id("withdrew-consent-case-released"),
        dst_id=get_node_id("fake_active_project"),
    ),
    models.AnnotationAnnotatesCase(
        src_id=get_node_id("released-rescinded-annotation"),
        dst_id=get_node_id("released-rescinded-case"),
    ),
    models.CaseMemberOfProject(
        src_id=get_node_id("released-rescinded-case"),
        dst_id=get_node_id("fake_active_project"),
    ),
    # API-716
    models.ProteinExpressionDerivedFromSample(
        src_id=get_node_id("protein-expression-from-sample-released"),
        dst_id=get_node_id("sample-blood-derived-normal"),
    ),
    models.PortionDerivedFromSample(
        src_id=get_node_id("protein-expression-portion"),
        dst_id=get_node_id("sample-blood-derived-normal"),
    ),
    models.ProteinExpressionDerivedFromPortion(
        src_id=get_node_id("protein-expression-from-portion-released"),
        dst_id=get_node_id("protein-expression-portion"),
    ),
    # DAT-2619
    models.SubmittedGenomicProfileDataFromReadGroup(
        src_id=get_node_id("submitted-genomic-profile-released-1"),
        dst_id=get_node_id("read-group-1"),
    ),
    models.SubmittedGenomicProfileDataFromReadGroup(
        src_id=get_node_id("submitted-genomic-profile-released-2"),
        dst_id=get_node_id("read-group-1"),
    ),
    models.SubmittedGenomicProfileDataFromReadGroup(
        src_id=get_node_id("submitted-genomic-profile-submitted"),
        dst_id=get_node_id("read-group-1"),
    ),
    models.GenomicProfileHarmonizationWorkflowPerformedOnSubmittedGenomicProfile(
        src_id=get_node_id("gen-profile-harmonization-released-1"),
        dst_id=get_node_id("submitted-genomic-profile-released-1"),
    ),
    models.GenomicProfileHarmonizationWorkflowPerformedOnSubmittedGenomicProfile(
        src_id=get_node_id("gen-profile-harmonization-released-2"),
        dst_id=get_node_id("submitted-genomic-profile-released-2"),
    ),
    models.GenomicProfileHarmonizationWorkflowPerformedOnSubmittedGenomicProfile(
        src_id=get_node_id("gen-profile-harmonization-released-3"),
        dst_id=get_node_id("submitted-genomic-profile-released-2"),
    ),
    models.GenomicProfileHarmonizationWorkflowPerformedOnSubmittedGenomicProfile(
        src_id=get_node_id("gen-profile-harmonization-submitted"),
        dst_id=get_node_id("submitted-genomic-profile-submitted"),
    ),
    models.AnnotatedSomaticMutationDataFromGenomicProfileHarmonizationWorkflow(
        src_id=get_node_id("genie-vcf-released"),
        dst_id=get_node_id("gen-profile-harmonization-released-2"),
    ),
    models.CopyNumberEstimateDerivedFromGenomicProfileHarmonizationWorkflow(
        src_id=get_node_id("genie-cne-released"),
        dst_id=get_node_id("gen-profile-harmonization-released-1"),
    ),
    models.StructuralVariationDataFromGenomicProfileHarmonizationWorkflow(
        src_id=get_node_id("genie-struct-var-released"),
        dst_id=get_node_id("gen-profile-harmonization-released-3"),
    ),
    models.StructuralVariationDataFromGenomicProfileHarmonizationWorkflow(
        src_id=get_node_id("genie-struct-var-submitted"),
        dst_id=get_node_id("gen-profile-harmonization-submitted"),
    ),
)


# Patch nodes, separate file metadata to indexd
NODES, INDEXD = patch_test_data_get_indexd(NODES)


def insert(g: psqlgraph.PsqlGraphDriver) -> None:
    with g.session_scope() as session:
        for node in NODES:
            session.merge(node)
        for edge in EDGES:
            session.merge(edge)

        to_delete = g.nodes(models.File).ids(get_node_id("to-delete-file")).one()
        to_delete.sysan["to_delete"] = True

        session.merge(to_delete)
