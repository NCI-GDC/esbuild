"""
Setup esbuild tests
"""
import logging
import os
import time
from typing import NamedTuple, Sequence

import psqlgraph
import pytest
import yaml
from datadog import statsd
from elasticsearch.exceptions import ElasticsearchException
from gdcdatamodel import models
from gdcdatamodel.viz import create_graphviz
from gdcdictionary import gdcdictionary
from indexclient.types import IndexData
from psqlgraph import Edge, Node, PsqlGraphDriver, mocks
from pytest_elasticsearch import factories as es_factories
from pytest_postgresql import factories

from esbuild.graph.active.builder import ActiveGraphIndexBuilder
from esbuild.utils import ReleaseHelper, get_index_names
from tests.integration import data, es_data

# ======================================================================
# Test Settings
pytest_plugins = ("pytest_indexd.plugin",)


TEST_DIR = os.path.dirname(os.path.realpath(__file__))
DATA_DIR = os.path.join(TEST_DIR, "data")

if os.getenv("USE_RUNNING_ES", "true").lower() == "true":
    elasticsearch_server_esbuild = es_factories.elasticsearch_noproc(
        host=os.getenv("ES_HOST", "localhost"), port=os.getenv("ES_PORT", "9200")
    )
else:
    elasticsearch_server_esbuild = es_factories.elasticsearch_proc(
        executable=os.getenv(
            "ES_EXECUTABLE", "/usr/share/elasticsearch/bin/elasticsearch"
        )
    )
elasticsearch_esbuild = es_factories.elasticsearch("elasticsearch_server_esbuild")

# ======================================================================
# Util

logger = logging.getLogger("conftest")
logger.setLevel(logging.DEBUG)


class Index(NamedTuple):
    cases: Sequence[dict]
    files: Sequence[dict]
    annotations: Sequence[dict]
    projects: Sequence[dict]


def create_all(engine):
    psqlgraph.create_all(engine)
    models.versioned_nodes.Base.metadata.create_all(engine)
    models.submission.Base.metadata.create_all(engine)
    models.FileReport.metadata.create_all(engine)


def db_loader(host, port, user, dbname, password):
    pg_conn = PsqlGraphDriver(
        host=f"{host}:{port}",
        user=user,
        password=password,
        database=dbname,
    )
    create_all(pg_conn.engine)


if os.getenv("USE_RUNNING_PG", "true").lower() == "true":
    postgresql_server_esbuild = factories.postgresql_noproc(
        host=os.getenv("PG_ESBUILD_HOST", "localhost"),
        user=os.getenv("PG_ESBUILD_USER", "postgres"),
        password=os.getenv("PG_ESBUILD_PASS", "test"),
        dbname=os.getenv("PG_ESBUILD_NAME", "esbuild_test"),
        load=[db_loader],
    )
else:
    postgresql_server_esbuild = factories.postgresql_proc(
        dbname=os.getenv("PG_ESBUILD_NAME", "esbuild_test"), load=[db_loader]
    )
postgresql_esbuild = factories.postgresql(
    "postgresql_server_esbuild",
    dbname=os.getenv("PG_ESBUILD_NAME", "esbuild_test"),
)


@pytest.fixture
def graph(postgresql_esbuild):

    pg_conn = PsqlGraphDriver(
        host=f"{postgresql_esbuild.info.host}:{postgresql_esbuild.info.port}",
        user=postgresql_esbuild.info.user,
        password=postgresql_esbuild.info.password,
        database=postgresql_esbuild.info.dbname,
    )

    yield pg_conn


@pytest.fixture
def create_indexd_documents(indexd_client, indexd_loader):
    def _inner(records):

        record_dicts = (dict(record) for record in records)

        processed_records = []

        # Insert indexd data:
        for record in record_dicts:
            urls = record["urls"]
            # NOTE: 'file_state' is stored as 'state' in indexd.
            # However, this is not important as esbuild does not pay attention to 'file_state'
            # and it is removed from resulting elasticsearch documents. See PRTL-2109
            urls_metadata = {urls[0]: {"state": record.get("file_state", "validated")}}
            if "gencode_version" not in record:
                record["gencode_version"] = "neutral"

            processed_records.append(
                IndexData(
                    did=record["did"],
                    acl=record["acl"],
                    hashes={"md5": record["md5sum"]},
                    size=record["file_size"],
                    file_name=record.get("file_name", None),
                    urls=urls,
                    metadata=record,
                    urls_metadata=urls_metadata,
                )
            )

        return indexd_loader(resource=processed_records)

    return _inner


@pytest.fixture
def init_indexd(indexd_client, create_indexd_documents):

    create_indexd_documents(data.INDEXD)

    return indexd_client


class TestError(Exception):
    """Monkeypatch exception for testinting exception handling"""

    pass


def raise_test_error(*args, **kwargs):
    """For monkeypatching to test exception handling"""

    raise TestError(f"{args} {kwargs}")


def render_database(pg_driver):
    """Save PDF graph of test suite data"""

    with pg_driver.session_scope():
        dot = create_graphviz(pg_driver.nodes())
        dot.render("test_suite_data.gv")


# ======================================================================
# Fixtures


@pytest.fixture(autouse=True)
def environment(monkeypatch, postgresql_esbuild, elasticsearch_server_esbuild):
    """Monkeypatch the script environment"""

    monkeypatch.setenv("ES_HOST", elasticsearch_server_esbuild.host)
    monkeypatch.setenv("ES_PORT", elasticsearch_server_esbuild.port)
    monkeypatch.setenv("ES_USER", "")
    monkeypatch.setenv("ES_PASSWORD", "")
    monkeypatch.setenv(
        "PG_HOST", f"{postgresql_esbuild.info.host}:{postgresql_esbuild.info.port}"
    )
    monkeypatch.setenv("PG_USER", postgresql_esbuild.info.user)
    monkeypatch.setenv("PG_PASS", postgresql_esbuild.info.password)
    monkeypatch.setenv("PG_NAME", postgresql_esbuild.info.dbname)


@pytest.fixture
def pg_driver(graph):
    """Add all test data to the database.

    Attempt to render a PDF representation of the test suite.

    """
    data.insert(graph)

    try:
        render_database(graph)
    except Exception as exc:
        logger.error("Failed to write updated database viz files: %s", exc)

    yield graph


@pytest.fixture
def ro_pg_driver(pg_driver, postgresql_esbuild):
    with pg_driver.engine.connect() as conn:
        ro_user = "ro_test"
        ro_pass = "ro_test"
        commands = [
            f"create user {ro_user} with password '{ro_pass}'",
            f"grant connect on database {postgresql_esbuild.info.dbname} to {ro_user}",
            f"grant select on all tables in schema public to {ro_user}",
        ]
        for cmd in commands:
            conn.execute(cmd)

    ro_pg_conn = PsqlGraphDriver(
        host=f"{postgresql_esbuild.info.host}:{postgresql_esbuild.info.port}",
        user=ro_user,
        password=ro_pass,
        database=postgresql_esbuild.info.dbname,
    )

    yield ro_pg_conn

    with pg_driver.engine.connect() as conn:
        commands = [
            f"revoke all on all tables in schema public from {ro_user}",
            f"revoke all on database {postgresql_esbuild.info.dbname} from {ro_user}",
            f"drop user {ro_user}",
        ]

        for cmd in commands:
            conn.execute(cmd)


@pytest.fixture(scope="session")
def graph_factory():
    graph_globals = {
        "properties": {
            "project_id": "TCGA-BRCA",
            "state": "released",
            "batch_id": 1,
            "experimental_strategy": "WXS",
        }
    }
    factory = mocks.GraphFactory(models, gdcdictionary, graph_globals)

    return factory


# ======================================================================
# Elasticsearch test index


def get_all_indices(es):
    return (
        # closed indices
        list(es.cluster.state()["blocks"].get("indices", {}).keys())
        +
        # opened indices:
        list(es.indices.stats()["indices"].keys())
    )


def cleanup_indices(es, indices=None):
    """
    Cleanup Elasticsearch cluster
    :param es: ES client
    :param indices: list of indices to delete
    """
    for _ in range(10):
        try:
            es.cluster.health(wait_for_status="yellow")
            break
        except ElasticsearchException:
            time.sleep(0.1)
    else:
        health = es.cluster.health()
        # Default timeout is 30 seconds, 10 iterations ~ 5 minutes
        raise Exception(f"Elasticsearch cluster offline after 5 minutes: {health}")

    if not indices:
        indices = get_all_indices(es)

    for index in indices:
        if index == ".geoip_databases":
            es.cluster.put_settings(
                {"persistent": {"ingest.geoip.downloader.enabled": False}}
            )
        else:
            es.indices.delete(index, ignore=(404, 400))

    es.indices.refresh()


@pytest.fixture(scope="session")
def index_types():
    return ["annotation", "case", "file", "project"]


@pytest.fixture
def es_client(elasticsearch_esbuild):
    return elasticsearch_esbuild


@pytest.fixture
def test_index_data(index_types, es_client):
    """Generate data index as a fixture for re-use between tests"""

    # Create test index with dummy docs
    index_prefix = "test_index_data"

    index_names = get_index_names(index_prefix, index_types)

    cleanup_indices(es_client, index_names.values())

    # Create dummy esbuild docs
    for index_type in index_types:
        mapping = es_data.get_mapping(index_type)

        es_client.indices.create(
            index=index_names[index_type], ignore=400, body=es_data.get_index_settings()
        )
        es_client.indices.refresh(index=index_names[index_type])
        es_client.indices.put_mapping(index=index_names[index_type], body=mapping)

        for doc in getattr(es_data, f"{index_type}_docs"):
            doc_id = doc["project_id"] if index_type == "project" else None

            es_client.index(
                index=index_names[index_type],
                body=doc,
                id=doc_id,
            )

    es_client.indices.refresh()

    # Make sure that docs are created:
    for index_type, counts in [
        ["case", len(es_data.case_docs)],
        ["file", len(es_data.file_docs)],
        ["project", len(es_data.project_docs)],
        ["annotation", len(es_data.annotation_docs)],
    ]:
        while True:
            count = es_client.count(index=index_names[index_type])["count"]
            if count == counts:
                break
            time.sleep(0.1)

    yield es_client, index_prefix

    cleanup_indices(es_client, index_names.values())


@pytest.fixture
def es_after_deletion(test_index_data, index_types):
    """
    Deletes some projects from the index but not updates the metadata,
    leaving build_metadata inconsistent purposefully
    """
    es, index_prefix = test_index_data
    helper = ReleaseHelper(es, audit_index="build_metadata_test")

    # Will delete these projects' data
    projects_to_delete = ["TCGA-STAD", "FM-AD"]

    # Get project list before deletion
    projects_before = helper.get_project_ids(index_prefix)

    index_names = get_index_names(index_prefix, index_types)
    # Delete documents associated with selected projects from index
    for index_type, index_name in index_names.items():
        helper.delete_docs_from_index(index_name, index_type, projects_to_delete)

    es.indices.refresh()

    return es, index_prefix, projects_before, projects_to_delete


@pytest.fixture
def setup_test(pg_driver, es_client):
    cleanup_indices(es_client)

    yield es_client

    cleanup_indices(es_client)


@pytest.fixture(autouse=True)
def mocked_statsd(monkeypatch):
    def event_mock(*_, **__):
        pass

    monkeypatch.setattr(statsd, "event", event_mock)


@pytest.fixture
def generate_scenario(graph_factory, pg_driver, create_indexd_documents):
    nodes = []

    def _from_file(scenario):
        path = os.path.join(DATA_DIR, scenario)

        with open(path) as f:
            nodes_meta = yaml.safe_load(f)

        x_nodes = graph_factory.create_from_nodes_and_edges(
            nodes=nodes_meta["nodes"],
            edges=nodes_meta["edges"],
            all_props=True,
        )

        for n in x_nodes:
            n.acl = ["phs000178"]

        x_nodes, records = data.patch_test_data_get_indexd(x_nodes)
        nodes.extend(x_nodes)
        docs = create_indexd_documents(records)

        case_nodes = [n for n in x_nodes if n.label == "case"]

        with pg_driver.session_scope():
            project = pg_driver.nodes(models.Project).props(code="BRCA").one()
            project.cases.extend(case_nodes)

        return x_nodes, docs

    yield _from_file


@pytest.fixture
def scenario_index(pg_driver, init_indexd, generate_scenario):
    def make_graph(filename):
        generate_scenario(filename)

        builder = ActiveGraphIndexBuilder(pg_driver, init_indexd)

        with pg_driver.session_scope():
            builder.cache_database()

        index = builder.denormalize_all()

        return Index._make(index)

    return make_graph


@pytest.fixture
def gencode_version_graph(generate_scenario):
    generate_scenario("gencode_version.yaml")


@pytest.fixture
def apply_gencode_to_indexd(pg_driver, init_indexd, gencode_version_graph):
    gencode_versions = [
        ["gv_ge_0", "v22"],
        ["gv_ge_1", "v36"],
        ["gv_ge_2", None],
    ]
    with pg_driver.session_scope():
        # remove gencode_version for all clinical_supplement to test submittable files
        cs_nodes = pg_driver.nodes(models.ClinicalSupplement).all()
        cs_docs = init_indexd.bulk_request(dids=[n.node_id for n in cs_nodes])
        for cs_doc in cs_docs:
            cs_doc.metadata["gencode_version"] = None
            cs_doc.patch()

        # apply specified gencode_version to GeneExpression to test pick up by gencode
        for submitter_id, gencode in gencode_versions:
            node = (
                pg_driver.nodes(models.GeneExpression)
                .props(submitter_id=submitter_id)
                .one()
            )
            doc = init_indexd.get(node.node_id)
            doc.metadata["gencode_version"] = gencode
            doc.patch()

    return init_indexd
