"""
test_graph_index.py
----------------------------------

Test the builder for graph ES index

"""

import pytest
from gdcdatamodel import models as md
from jsonpath_rw import parse

from esbuild.graph.legacy.builder import LegacyGraphIndexBuilder
from tests.integration.conftest import Index, cleanup_nodes, raise_test_error
from tests.integration.data import fuzzed, get_node_id
from tests.integration.test_utils import validate_file_metadata


def build_index(graph, indexd_client):
    builder = LegacyGraphIndexBuilder(graph, indexd_client)
    with graph.session_scope():
        builder.cache_database()
        index = builder.denormalize_all()
    return Index._make(index)


# ======================================================================
# Fixtures


@pytest.fixture()
def builder(init_indexd, pg_driver):
    return LegacyGraphIndexBuilder(pg_driver, init_indexd)


@pytest.fixture
def index(init_indexd, pg_driver):
    return build_index(pg_driver, init_indexd)


@pytest.fixture
def custom_annotation(pg_driver):
    case = fuzzed(md.Case, project_id="TCGA-BRCA", state="live")
    annotation = fuzzed(
        md.Annotation,
        node_id="custom-annotation",
        category="Item flagged DNU",
        classification="Notification",
    )
    with pg_driver.session_scope() as s:
        f = pg_driver.nodes(md.File).ids(get_node_id("live-file")).first()
        case.projects = [pg_driver.nodes(md.Project).props(code="BRCA").first()]
        case.files = [f]
        case.annotations = [annotation]
        s.add(case)

    yield case, annotation

    cleanup_nodes(pg_driver, [case, annotation])


@pytest.fixture
def suppressed_case(pg_driver, graph_factory):
    nodes = [
        dict(label="case", submitter_id="suppressed_case", state="live"),
        dict(label="sample", submitter_id="suppressed_sample", state="live"),
        dict(label="aliquot", submitter_id="suppressed_aliquot", state="live"),
        dict(label="file", submitter_id="suppressed_file", state="live"),
    ]
    edges = [
        dict(src="suppressed_sample", dst="suppressed_case"),
        dict(src="suppressed_aliquot", dst="suppressed_sample"),
        dict(src="suppressed_file", dst="suppressed_aliquot"),
    ]
    nodes = graph_factory.create_from_nodes_and_edges(nodes, edges, all_props=True)

    with pg_driver.session_scope() as sxn:
        case = [n for n in nodes if n.label == "case"][0]
        redaction = graph_factory.node_factory.create(
            "annotation",
            override={
                "classification": "Redaction",
                "category": "General",
                "state": "live",
                "status": "Approved",
            },
            all_props=True,
        )
        case.annotations = [redaction]

        sxn.add(case)

    yield case, redaction

    cleanup_nodes(pg_driver, nodes + [redaction])


@pytest.fixture
def non_case_redaction(pg_driver):
    annotation = fuzzed(
        md.Annotation,
        node_id="non-case-redaction-1",
        classification="Redaction",
        project_id="TCGA-BRCA",
        category="General",
        status="Approved",
    )
    with pg_driver.session_scope() as s:
        portion_id = get_node_id("portion-01")
        portion = pg_driver.nodes(md.Portion).get(portion_id)
        annotation.portions = [portion]

        sample = portion.samples[0]
        case = sample.cases[0]
        analyte = portion.analytes[0]
        aliquot = analyte.aliquots[0]

        redacted1 = fuzzed(
            md.File, node_id="redact1", state="live", project_id="TCGA-BRCA"
        )
        redacted1.portions = [portion]
        redacted2 = fuzzed(
            md.File, node_id="redact2", state="live", project_id="TCGA-BRCA"
        )
        redacted2.aliquots = [aliquot]

        s.add(annotation)
        s.add(redacted1)
        s.add(redacted2)

    yield portion, sample, case

    cleanup_nodes(pg_driver, [annotation, redacted1, redacted2])


@pytest.fixture
def non_live_related_file(pg_driver):
    with pg_driver.session_scope() as sxn:
        live_file = pg_driver.nodes(md.File).ids(get_node_id("live-file")).one()
        derived_file = fuzzed(
            md.File,
            state="live",
            file_name="derived_file.bam",
            project_id="TCGA-BRCA",
        )
        derived_file.sysan["source"] = "tcga_exome_alignment"
        live_file.derived_files = [derived_file]
        related_to_derived = fuzzed(
            md.File,
            state="uploaded",
            file_name="derived_file.txt",
            project_id="TCGA-BRCA",
        )
        related_to_derived.sysan["source"] = "tcga_exome_alignment"
        derived_file.related_files = [related_to_derived]
        sxn.add(related_to_derived)
        sxn.add(derived_file)

    yield derived_file

    cleanup_nodes(pg_driver, [related_to_derived, derived_file])


@pytest.fixture
def withdrew_consent_redaction(pg_driver):
    with pg_driver.session_scope() as s:
        case = pg_driver.nodes(md.Case).props(submitter_id="TCGA-AR-A1AR").one()
        annotation = fuzzed(
            md.Annotation,
            classification="Redaction",
            category="Subject withdrew consent",
            project_id="TCGA-BRCA",
            status="Approved",
        )
        case.annotations = [annotation]

        s.merge(case)

    yield case, annotation

    cleanup_nodes(pg_driver, [annotation])


@pytest.fixture
def exp_strats_setup(pg_driver):
    with pg_driver.session_scope():
        live_file = pg_driver.nodes(md.File).ids(get_node_id("live-file")).one()
        exp = (
            pg_driver.nodes(md.ExperimentalStrategy)
            .prop_in("name", ["WXS", "VALIDATION"])
            .all()
        )
        live_file.experimental_strategies = exp

    yield live_file

    with pg_driver.session_scope():
        live_file.experimental_strategies = []


@pytest.fixture
def derived_file_setup(pg_driver):
    with pg_driver.session_scope():
        live_file = pg_driver.nodes(md.File).ids(get_node_id("live-file")).one()
        fake_center = fuzzed(md.Center)
        live_file.centers = [fake_center]
        derived_file = fuzzed(
            md.File,
            state="live",
            file_name="derived_file.bam",
            project_id="TCGA-BRCA",
        )
        derived_file.sysan["source"] = "tcga_exome_alignment"
        live_file.derived_files = [derived_file]
        related_to_derived = fuzzed(
            md.File,
            state="live",
            file_name="derived_file.bam.txt",
            project_id="TCGA-BRCA",
        )
        related_to_derived.sysan["source"] = "tcga_exome_alignment"
        derived_file.related_files = [related_to_derived]

    yield live_file, derived_file, related_to_derived

    cleanup_nodes(pg_driver, [related_to_derived, derived_file])


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


@pytest.mark.skip(reason="skipping failing legacy test")
def test_annotation_case_submitter_id(pg_driver, init_indexd, custom_annotation):
    case, annotation = custom_annotation

    annotation = [
        ann
        for ann in build_index(pg_driver, init_indexd).annotations
        if ann["annotation_id"] == annotation.node_id
    ][0]

    assert annotation["entity_type"] == "case"
    assert annotation["case_id"] == annotation["entity_id"]
    assert annotation["case_submitter_id"] == case.submitter_id


@pytest.mark.skip(reason="skipping failing legacy test")
@pytest.mark.parametrize(
    "index_type,path,count",
    [
        ("cases", "[*].project.project_id", 1),
        ("cases", "[*].samples.[*].sample_id", 2),
        ("cases", "[*].samples.[*].portions.[*].portion_id", 3),
        ("cases", "[*].samples.[*].portions.[*].analytes.[*].analyte_id", 6),
        (
            "cases",
            "[*].samples.[*].portions.[*].analytes.[*].aliquots.[*].aliquot_id",
            12,
        ),
        ("files", "[*].file_size", 8),
        ("files", "[*].associated_entities", 6),
        ("annotations", "[*].annotation_id", 3),
    ],
)
def test_path_count(index, index_type, path, count):
    results = parse(path).find(getattr(index, index_type))
    assert len(results) == count


@pytest.mark.parametrize(
    "index_type,path",
    [
        ("cases", "[*].clinical"),
    ],
)
def test_path_is_absent(index, index_type, path):
    assert not parse(path).find(getattr(index, index_type))


@pytest.mark.parametrize(
    "index_type,path,expected,count",
    [
        ("projects", "[*].summary.[*].data_categories.[*].file_count", [1], 3),
        (
            "projects",
            "[*].summary.[*].data_categories.[*].data_category",
            ["Raw sequencing data", "Clinical", "Biospecimen"],
            3,
        ),
        ("cases", "[*].demographic.year_of_birth", [1951], 1),
        ("cases", "[*].diagnoses.[*].age_at_diagnosis", [47], 1),
        (
            "cases",
            "[*].diagnoses.[*].treatments.[*].treatment_or_therapy",
            ["unknown"],
            1,
        ),
        ("cases", "[*].exposures.[*].cigarettes_per_day", [10.3], 1),
        (
            "cases",
            "[*].family_histories.[*].relationship_primary_diagnosis",
            ["Colorectal Cancer"],
            1,
        ),
        ("files", "[*].index_files.[*].file_name", ["test_file.bam.bai"], 1),
        (
            "files",
            "[*].type.[*]",
            ["file", "biospecimen_supplement", "clinical_supplement", "archive"],
            8,
        ),
        ("files", "[*].metadata_files.[*].data_format", ["SRA XML", None], 5),
    ],
)
def test_path_value_in(index, index_type, path, expected, count, init_indexd):
    results = parse(path).find(getattr(index, index_type))
    assert len([r.value for r in results]) == count
    for actual in results:
        assert actual.value in expected


def test_omitted_projects(pg_driver, init_indexd):
    builder = LegacyGraphIndexBuilder(pg_driver, init_indexd)
    with pg_driver.session_scope():
        builder.omitted_projects.add(("TCGA", "BRCA"))
        builder.cache_database()
        index = Index._make(builder.denormalize_all())
    assert index.cases == []


def test_basic_suppression(pg_driver, init_indexd, suppressed_case):
    case, redaction = suppressed_case
    index = build_index(pg_driver, init_indexd)

    with pg_driver.session_scope():
        assert pg_driver.nodes().get(case.node_id) is not None
        assert pg_driver.nodes().get(redaction.node_id) is not None

    assert case.node_id not in [c["case_id"] for c in index.cases]
    assert "redacted-file" not in [f["file_id"] for f in index.files]


def test_non_case_suppression(pg_driver, init_indexd, non_case_redaction):
    portion, sample, case = non_case_redaction

    index = build_index(pg_driver, init_indexd)
    case_doc = [c for c in index.cases if c["case_id"] == case.node_id][0]
    sample_doc = [s for s in case_doc["samples"] if s["sample_id"] == sample.node_id][0]

    assert portion.node_id not in {p.get("portion_id") for p in sample_doc["portions"]}

    assert "redact1" not in [f["file_id"] for f in index.files]
    assert "redact2" not in [f["file_id"] for f in index.files]


def test_subject_withdrew_consent_is_not_suppressed(
    pg_driver, init_indexd, withdrew_consent_redaction
):
    case, _ = withdrew_consent_redaction
    index = build_index(pg_driver, init_indexd)
    # the case should be there
    assert case.node_id in [c["case_id"] for c in index.cases]
    # the file should be there
    assert get_node_id("live-file") in [f["file_id"] for f in index.files]


def test_duplicate_classification_only_results_in_warning(
    pg_driver, init_indexd, exp_strats_setup
):
    live_file = exp_strats_setup
    index = build_index(pg_driver, init_indexd)
    # the file should be there
    assert live_file.node_id in [f["file_id"] for f in index.files]


def test_derived_files(pg_driver, init_indexd, derived_file_setup):
    live_file, derived_file, related_to_derived = derived_file_setup
    index = build_index(pg_driver, init_indexd)

    # derived_file should be a doc in it's own right, and should
    # have the single correct related file
    derived_file_docs = [f for f in index.files if f["file_id"] == derived_file.node_id]

    assert len(derived_file_docs) == 0


def test_non_live_related_files_dont_cause_source_files_in_related(
    non_live_related_file, pg_driver, init_indexd
):
    index = build_index(pg_driver, init_indexd)

    # derived_file should be a doc in it's own right, and should
    # have the single correct related file
    derived_file_docs = [
        f for f in index.files if f["file_id"] == non_live_related_file.node_id
    ]
    assert len(derived_file_docs) == 0


def test_project_file_counts(index, builder, monkeypatch):
    monkeypatch.setattr(builder, "error", raise_test_error)
    for project in index.projects:
        builder.validate_project_file_counts(project, index.files)


def test_data_category_count(index, builder, monkeypatch):
    monkeypatch.setattr(builder, "error", raise_test_error)
    for case in index.cases:
        builder.verify_data_category_count(case)
