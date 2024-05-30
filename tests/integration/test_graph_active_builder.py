"""
test_graph_index.py
----------------------------------

Test the builder for graph ES index

"""

import operator
from functools import reduce

import jmespath
import psqlgraph
import pytest
from gdcdatamodel2 import models
from indexclient import client

from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.graph.common.builder import GraphIndexBuilder
from tests.integration.conftest import Index, raise_test_error
from tests.integration.data import get_node_id
from tests.integration.test_utils import validate_file_metadata

DATA_FILE_CATEGORIES = GraphIndexBuilder.data_file_categories
DATA_FILE_INDEXD_FIELDS = GraphIndexBuilder.data_file_indexd_fields


# Define the number of files that should be loaded as documents
N_FILES = 15
N_OUTPUT_FILES = 6
N_INPUT_FILES = 9

# Whenever a new file is added under Aliquot.node_id == get_node_id('aliquot-1')
# this needs to be updated
N_FILES_UNDER_ALIQUOT_1 = 10

# ======================================================================
# Fixtures


@pytest.fixture
def index(init_indexd, pg_driver):
    builder = ActiveGraphIndexBuilder(pg_driver, init_indexd)
    with pg_driver.session_scope():
        builder.cache_database()
    index = builder.denormalize_all()
    return Index._make(index)


@pytest.fixture
def cached_builder(init_indexd, pg_driver):
    with pg_driver.session_scope():
        builder = ActiveGraphIndexBuilder(pg_driver, init_indexd)
        builder.cache_database()
        yield builder


@pytest.fixture()
def builder(init_indexd, pg_driver):
    return ActiveGraphIndexBuilder(pg_driver, init_indexd)


@pytest.fixture
def aligned_reads(index):
    return [d for d in index.files if d["type"] == "aligned_reads"]


@pytest.fixture
def simple_somatic_mutations(index):
    return [d for d in index.files if d["type"] == "simple_somatic_mutation"]


@pytest.fixture
def inconsistent_slides(generate_scenario):
    generate_scenario("slide_two_cases_scenario.yaml")


@pytest.fixture
def diagnosis_annotations(generate_scenario):
    generate_scenario("diagnosis_annotation_scenario.yaml")


# ======================================================================
# Tests


def test_get_file_metadata_from_indexd(index):
    """
    Test that file metadata fields are taken from indexd
    (by checking that their value is not 'error' or -1 which are values in the graph)
    """
    for f in index.files:
        for key, value in f.items():
            validate_file_metadata(key, value)


def test_selective_caching(init_indexd, ro_pg_driver):
    """
    Tests that partial graph data caching is working in subset build scenario
    """
    projects_subset = {"TCGA-BRCA", "TCGA-DEV1"}
    builder1 = ActiveGraphIndexBuilder(
        ro_pg_driver,
        init_indexd,
        build_projects=projects_subset,
        selective_caching=True,
    )
    builder1.cache_database()

    built_projects = {
        n.project_id for n in builder1.G.nodes() if "project_id" in n.props
    }
    assert built_projects == projects_subset

    builder2 = ActiveGraphIndexBuilder(
        ro_pg_driver, init_indexd, selective_caching=True
    )
    builder2.cache_database()

    all_projects = {n.project_id for n in builder2.G.nodes() if "project_id" in n.props}

    assert built_projects.issubset(all_projects)
    assert built_projects != all_projects


def test_awg_build(init_indexd, pg_driver):
    """
    Tests AWG build mode
    """
    build_projects = {"TCGA-LUAD", "INTERNAL-AWG-ONE"}
    builder = ActiveGraphIndexBuilder(
        pg_driver, init_indexd, build_awg=True, build_projects=build_projects
    )
    builder.cache_database()

    # Check that only AWG nodes were built
    built_nodes = {}
    for node in builder.G.nodes():
        built_nodes.setdefault(node.label, set())
        built_nodes[node.label].update([node.node_id])

    assert built_nodes == {
        "case": {get_node_id("submitted-awg-case"), get_node_id("processed-awg-case")},
        "project": {get_node_id("awg-one-project")},
        "program": {get_node_id("internal-program")},
    }


@pytest.mark.parametrize(
    "gencode,expected_number",
    [
        ["v22", 17],
        ["v36", 18],
    ],
)
def test_gencode_version(apply_gencode_to_indexd, pg_driver, gencode, expected_number):
    builder = ActiveGraphIndexBuilder(
        psqlgraph_driver=pg_driver,
        indexd_client=apply_gencode_to_indexd,
        build_projects={"TCGA-BRCA"},
        allowed_gencode_versions=frozenset(["neutral", gencode]),
    )
    builder.cache_database()

    index_docs = builder.denormalize_all()
    assert len(index_docs[1]) == expected_number

    submitter_ids = [file.get("submitter_id") for file in index_docs[1]]
    include_v36 = gencode == "v36"
    for v36_submitter_id in ["gv_ge_1", "gv_secondary_exp_1"]:
        assert (v36_submitter_id in submitter_ids) is include_v36


@pytest.mark.parametrize(
    "index_type,path",
    [
        ("cases", "[].clinical"),
        ("cases", "[].files[].file_state"),
        ("files", "[].file_state"),
        ("annotations", "[].creator"),
    ],
)
def test_path_is_absent(index, index_type, path):
    assert not jmespath.search(path, getattr(index, index_type))


@pytest.mark.parametrize(
    "index_type,path,count",
    [
        ("projects", "[].primary_site", 2),
        ("projects", "[].disease_type", 2),
        ("cases", "[].primary_site", 5),
        ("cases", "[].disease_type", 5),
        ("cases", "[].project.project_id", 5),
        ("cases", "[].project.disease_type", 5),
        ("cases", "[].project.primary_site", 5),
        ("cases", "[].project_id", 0),
        ("cases", "[].metadata_files", 0),
        ("cases", "[].samples[].project_id", 0),
        ("cases", "[].samples[].portions[].portion_id", 6),
        ("cases", "[].samples[].portions[].analytes[].analyte_id", 7),
        (
            "cases",
            "[].samples[].portions[].analytes[].aliquots[].project_id",
            0,
        ),
        ("cases", "[].samples[].sample_id", 3),
        (
            "cases",
            "[].samples[].portions[].analytes[].aliquots[].aliquot_id",
            13,
        ),
        ("files", "[].[file_size,file_name,file_id][]", N_FILES * 3),
        ("files", "[].uploaded_datetime", 0),
        ("files", "[].project_id", 0),
        ("files", "[].cases[].project_id", 0),
        ("files", "[].annotations[].case_id", N_FILES_UNDER_ALIQUOT_1),
        ("annotations", "[].project_id", 0),
        ("annotations", "[].annotation_id", 3),
        ("files", "[].associated_entities[].entity_type", N_FILES + 3),
    ],
)
def test_path_count(index, index_type, path, count):
    results = jmespath.search(path, getattr(index, index_type))
    assert len(results) == count


@pytest.mark.parametrize(
    "index_type, count",
    [("annotations", 3), ("projects", 2), ("cases", 5), ("files", N_FILES)],
)
def test_basic_counts(index, index_type, count):
    data = getattr(index, index_type)
    assert len(data) == count


@pytest.mark.parametrize(
    "index_type,path,count,expected",
    [
        (
            "projects",
            "[].name",
            2,
            {"Breast Invasive Carcinoma", "Made up active project"},
        ),
        (
            "projects",
            "[].summary[].data_categories[].file_count",
            9,
            {1, 2, 3},
        ),  # 3 CNV
        (
            "projects",
            "[].summary[].data_categories[].data_category",
            9,
            {
                "Simple Nucleotide Variation",
                "Sequencing Reads",
                "Biospecimen",
                "Clinical",
                "Combined Nucleotide Variation",
                "Copy Number Variation",
                "DNA Methylation",
                "Proteome Profiling",
                "Somatic Structural Variation",
            },
        ),
        (
            "cases",
            "[].submitter_id",
            5,
            {
                "TCGA-AR-A1AR",
                "fake_submitter_1",
                "fake_submitter_2",
                "released_case_submitter_2",
            },
        ),
        ("cases", "[].demographic.year_of_birth", 1, {1951}),
        ("cases", "[].diagnoses[].age_at_diagnosis", 1, {47}),
        (
            "cases",
            "[].diagnoses[].treatments[].treatment_or_therapy",
            1,
            {"unknown"},
        ),
        ("cases", "[].exposures[].cigarettes_per_day", 1, {10.3}),
        (
            "cases",
            "[].family_histories[].relationship_primary_diagnosis",
            1,
            {"Colorectal Cancer"},
        ),
        (
            "cases",
            "[].files[].analysis[].metadata[].read_groups[].read_group_id",
            2,
            {get_node_id("read-group-1"), get_node_id("read-group-2")},
        ),
        (
            "cases",
            "[].disease_type",
            5,
            {"Blood Vessel Tumors", "Adenomas and Adenocarcinomas"},
        ),
        ("cases", "[].primary_site", 5, {"Breast", "Prostate gland", "Rectum"}),
        (
            "files",
            "[].analysis.metadata.read_groups[].read_group_qcs[].read_group_qc_id",
            1,
            {get_node_id("read-group-qc-1")},
        ),
        ("files", "[].index_files[].file_name", 1, {"index-file-2.bam.bai"}),
        (
            "files",
            "[].analysis[].input_files[].data_category",
            N_INPUT_FILES,
            {
                "Sequencing Reads",
                "Simple Nucleotide Variation",
                "Combined Nucleotide Variation",
            },
        ),
        (
            "files",
            "[].downstream_analyses[].output_files[].access",
            N_OUTPUT_FILES,
            {"controlled"},
        ),
        (
            "files",
            "[].analysis[].input_files[].access",
            N_INPUT_FILES,
            {"controlled"},
        ),
        (
            "files",
            "[].downstream_analyses[].output_files[].data_category",
            N_OUTPUT_FILES,
            {"Simple Nucleotide Variation", "Combined Nucleotide Variation"},
        ),
        (
            "files",
            "[].downstream_analyses[].output_files[].state",
            N_OUTPUT_FILES,
            {"released"},
        ),
        (
            "files",
            "[].type",
            N_FILES,
            {
                "simple_somatic_mutation",
                "aligned_reads",
                "biospecimen_supplement",
                "clinical_supplement",
                "copy_number_segment",
                "annotated_somatic_mutation",
                "aggregated_somatic_mutation",
                "methylation_beta_value",
                "protein_expression",
                "copy_number_estimate",
                "structural_variation",
            },
        ),
    ],
)
def test_path_value_set_equals(index, index_type, path, expected, count):
    results = jmespath.search(path, getattr(index, index_type))
    actual = frozenset(results)
    assert actual == expected
    assert len(results) == count


@pytest.mark.parametrize(
    "index_type,path,cls,node_ids",
    [
        (
            "files",
            "[].file_id",
            models.Aliquot,
            [get_node_id("aliquot-derived-from-unreleased-sample")],
        ),
        (
            "cases",
            "[].case_id",
            models.Case,
            [get_node_id("released-case-in-unreleased-project")],
        ),
        (
            "cases",
            "[].samples[].sample_id",
            models.Sample,
            [get_node_id("sample-unreleased")],
        ),
        (
            "cases",
            "[].annotations[].annotation_id",
            models.Annotation,
            [get_node_id("unreleased-annotation")],
        ),
    ],
)
def test_unreleased_nodes_not_indexed(
    pg_driver, index, index_type, path, cls, node_ids
):
    with pg_driver.session_scope():
        for node_id in node_ids:
            node = pg_driver.nodes(cls).ids(node_id).one()
            assert node.state in ["submitted", "released"]

    results = frozenset(jmespath.search(path, getattr(index, index_type)))

    assert len(results & frozenset(node_ids)) == 0


@pytest.mark.parametrize(
    "index_type,path,count,expected",
    [
        (
            "projects",
            "[].disease_type",
            2,
            {"Blood Vessel Tumors", "Adenomas and Adenocarcinomas"},
        ),
        ("projects", "[].primary_site", 2, {"Breast", "Prostate gland", "Rectum"}),
    ],
)
def test_path_value_set_equals_set(index, index_type, path, expected, count):
    results = jmespath.search(path, getattr(index, index_type))
    # reduce the dimensionality because we only really care about the
    # existing values here and the count
    actual = reduce(operator.or_, map(lambda x: frozenset(x), results))
    assert actual == expected
    assert len(results) == count


@pytest.mark.parametrize(
    "node_cls", [(models.SubmittedAlignedReads), (models.SubmittedMethylationBetaValue)]
)
def test_no_submitted_types(pg_driver, index, node_cls):
    with pg_driver.session_scope():
        f_ids = {n.node_id for n in pg_driver.nodes(node_cls).all()}
        assert not [d for d in index.files if d["file_id"] in f_ids]


def test_aligned_reads_analysis_input_files(index, simple_somatic_mutations):
    for doc in simple_somatic_mutations:
        assert doc["analysis"].get("input_files")
        assert len(doc["analysis"]["input_files"]) == 2
        for f in doc["analysis"]["input_files"]:
            assert f["file_name"]
            assert f["data_format"]


def test_aligned_reads_analysis_read_group(index, aligned_reads):
    for doc in aligned_reads:
        assert doc["analysis"].get("metadata")
        read_groups = doc["analysis"]["metadata"]["read_groups"]
        assert len(read_groups) == 1
        for rg in read_groups:
            assert rg["read_group_id"]


def test_project_file_counts(index, builder, monkeypatch):
    monkeypatch.setattr(builder, "error", raise_test_error)
    for project in index.projects:
        builder.validate_project_file_counts(project, index.files)


def test_data_category_count(index, builder, monkeypatch):
    monkeypatch.setattr(builder, "error", raise_test_error)
    for case in index.cases:
        builder.verify_data_category_count(case)


def test_case_summary_data_category_counts(index):
    for case in index.cases:
        actual_counts = {}
        for f in case["files"]:
            category = f["data_category"]
            actual_counts[category] = actual_counts.get(category, 0) + 1

        for entry in case["summary"]["data_categories"]:
            category, count = entry["data_category"], entry["file_count"]
            assert category in actual_counts
            assert actual_counts[category] == count, category


def test_case_summary_file_counts(index):
    for case in index.cases:
        actual_count = len(
            [f for f in index.files if f["cases"][0]["case_id"] == case["case_id"]]
        )
        assert actual_count == case["summary"]["file_count"]


def test_get_file_read_groups(pg_driver, index):
    with pg_driver.session_scope():
        f_ids = {n.node_id for n in pg_driver.nodes(models.SubmittedAlignedReads).all()}
        assert not [d for d in index.files if d["file_id"] in f_ids]


@pytest.mark.parametrize(
    "cls,count",
    [
        (models.AlignmentWorkflow, 2),
        (models.SomaticMutationCallingWorkflow, 2),
    ],
)
def test_get_analysis_read_groups(pg_driver, cached_builder, cls, count):
    for workflow in pg_driver.nodes(cls).all():
        read_groups = list(cached_builder.get_analysis_read_groups(workflow))
        assert len(read_groups) == count
        for read_group in read_groups:
            assert read_group.label == "read_group"


@pytest.mark.parametrize(
    "cls,count",
    [
        (models.AlignedReads, 1),
        (models.CopyNumberSegment, 1),
        (models.RunMetadata, 1),
        (models.ExperimentMetadata, 1),
    ],
)
def test_get_file_associated_entities(pg_driver, cached_builder, cls, count):
    for node in pg_driver.nodes(cls).all():
        if cached_builder.is_file_indexed(node):
            entities = list(cached_builder.get_file_associated_entities(node))
            assert len(entities) == count


@pytest.mark.parametrize(
    "cls,count",
    [
        (models.BiospecimenSupplement, 0),
        (models.ClinicalSupplement, 0),
    ],
    scope="module",
)
def test_add_related_files(pg_driver, cached_builder, cls, count):
    for node in pg_driver.nodes(cls).all():
        if cached_builder.is_file_indexed(node):
            doc = {}
            cached_builder.add_related_files(node, doc)
            assert len(doc.get("metadata_files", [])) == count


@pytest.mark.parametrize(
    "cls,has_archive",
    [
        (models.BiospecimenSupplement, True),
        (models.ClinicalSupplement, True),
        (models.AlignedReads, False),
        (models.CopyNumberSegment, False),
    ],
    scope="module",
)
def test_add_archive(pg_driver, cached_builder, cls, has_archive):
    for node in pg_driver.nodes(cls).all():
        if cached_builder.is_file_indexed(node):
            doc = {}
            cached_builder.add_archives(node, doc)
            assert ("archive" in doc) == has_archive


def test_aligned_reads_count(aligned_reads):
    assert len(aligned_reads) == 2


def test_aligned_reads_associated_entities(index, aligned_reads):
    for f in aligned_reads:
        assert len(f["associated_entities"]) == 1


def test_aligned_reads_ancestor_sample_types(index, aligned_reads):
    for f in aligned_reads:
        assert len(f["cases"]) == 1
        assert len(f["cases"][0]["samples"]) == 1


def test_no_duplicate_top_level_ids(index):
    for case in index.cases:
        aliquot_ids = case.get("aliquot_ids", [])
        assert len(aliquot_ids) == len(set(aliquot_ids))


def test_somatic_aggregation_workflow_read_groups(index):
    aggregated_somatic_mutations = [
        doc for doc in index.files if doc["data_type"] == "Aggregated Somatic Mutation"
    ]
    assert aggregated_somatic_mutations
    for asm in aggregated_somatic_mutations:
        assert not asm["analysis"].get("metadata", {}).get("read_groups", [])


def test_sample_analyte_indexed(index):
    """Tests to verify that aliquots under the subtree case.sample.analyte are indexed"""
    case_affected = None
    for case in index.cases:
        if case["submitter_id"] == "fake_submitter_2":
            case_affected = case
            break
    assert len(case_affected["aliquot_ids"]) == 1
    aliquot_ids = case_affected["aliquot_ids"]
    assert aliquot_ids[0] == get_node_id("tt-260-aliquot")


def test_inconsistent_slides_in_graph(pg_driver, init_indexd, inconsistent_slides):
    """
    Make sure that regardless of the order in which we cache Slide node relations
    to cases, the caching still completes as expected.

    Before the fix, there was an early return in the `_cache_entity_cases`,
    which resulted in inconsistent caching, because the results depended on when
    we'd run into the early return.

    This makes sure that regardless of the order, we always cache entity cases,
    except for the ones that are inconsistent
    """

    class MyBuilderA(ActiveGraphIndexBuilder):
        def nodes_labeled(self, labels):
            # always returns Slide nodes first
            results = [n for n in super().nodes_labeled(labels)]
            slides = [n for n in results if n.label == "slide"]
            results = slides + [n for n in results if n.label != "slide"]
            return results

    class MyBuilderB(ActiveGraphIndexBuilder):
        def nodes_labeled(self, labels):
            # always returns Slide nodes last
            results = [n for n in super().nodes_labeled(labels)]
            slides = [n for n in results if n.label == "slide"]
            results = [n for n in results if n.label != "slide"] + slides
            return results

    builderA = MyBuilderA(pg_driver, init_indexd)
    with pg_driver.session_scope():
        builderA.cache_database()
        labeled = builderA.nodes_labeled(builderA.possible_associated_entities)
        assert labeled and all(n.label == "slide" for n in labeled[:3])

    builderB = MyBuilderB(pg_driver, init_indexd)
    with pg_driver.session_scope():
        builderB.cache_database()
        labeled = builderB.nodes_labeled(builderB.possible_associated_entities)
        assert labeled and all(n.label == "slide" for n in labeled[-3:])

    # Comparing that 2 maps are the same
    assert builderA.entity_cases == builderB.entity_cases

    cached_slide_ids = {n.submitter_id for n in builderA.entity_cases}

    # Making sure that 'slide_1' wasn't picked up, since it's linked to 2 cases
    assert "slide_1" not in cached_slide_ids
    assert "slide_2" in cached_slide_ids
    assert len(builderA.entity_cases) == 27

    _, filesA, _, _ = builderA.denormalize_all()
    slide_image_filesA = [f for f in filesA if f["type"] == "slide_image"]

    assert len(slide_image_filesA) == 2

    si1 = [f for f in slide_image_filesA if f["submitter_id"] == "slide_image_1"][0]
    si2 = [f for f in slide_image_filesA if f["submitter_id"] == "slide_image_2"][0]

    si1_entities = si1.get("associated_entities")
    si2_entities = si2.get("associated_entities")

    # Making sure that 'associated_entities' is populated where expected
    assert not si1_entities, si1_entities
    assert si2_entities, si2_entities

    # Make sure that correct entities got linked
    si2_entity_ids = [ae["entity_submitter_id"] for ae in si2_entities]
    assert "slide_2" in si2_entity_ids


@pytest.mark.usefixtures("diagnosis_annotations")
def test_diagnosis_annotation_has_extra_data(pg_driver, init_indexd):
    builder = ActiveGraphIndexBuilder(pg_driver, init_indexd)

    with pg_driver.session_scope():
        builder.cache_database()

    cases, _, _, _ = builder.denormalize_all()

    target_case = [c for c in cases if c["submitter_id"] == "da_case_1"][0]

    assert len(target_case["diagnoses"]) == 1
    assert len(target_case["diagnoses"][0]["annotations"]) == 1

    diag_ann = target_case["diagnoses"][0]["annotations"][0]

    # NOTE: SV-1753 validation
    assert "entity_id" in diag_ann
    assert "entity_submitter_id" in diag_ann
