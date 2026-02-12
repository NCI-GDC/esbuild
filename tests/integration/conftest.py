"""Setup esbuild tests."""

import itertools
import logging
import os
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence, Set
from importlib import resources
from typing import Any, NamedTuple, NoReturn

import elasticsearch
import gdcdictionary
import gdcmodels
import psqlgraph
import pytest
import yaml
from datadog import statsd
from elasticsearch import exceptions
from gdc_ng_models.models import misc, submission
from gdcdatamodel2 import models, viz
from indexclient import client
from psqlgraph import hydrator
from testcontainers import compose

from esbuild import utils
from esbuild.graph.active import builder
from tests.integration import data, es_data

# ======================================================================
# Test Settings


TEST_DIR = os.path.dirname(os.path.realpath(__file__))
DATA_DIR = os.path.join(TEST_DIR, "data")
INDEX_TYPES = ("annotation", "case", "file", "project")


# ======================================================================
# Util

logger = logging.getLogger("conftest")
logger.setLevel(logging.DEBUG)


class Index(NamedTuple):
    cases: Sequence[dict]
    files: Sequence[dict]
    annotations: Sequence[dict]
    projects: Sequence[dict]


class TestError(Exception):
    """Monkeypatch exception for testing exception handling."""

    pass


def raise_test_error(*args: Any, **kwargs: Any) -> NoReturn:
    """For monkeypatching to test exception handling."""
    raise TestError(f"{args} {kwargs}")


def render_database(pg_driver: psqlgraph.PsqlGraphDriver) -> None:
    """Save PDF graph of test suite data."""
    with pg_driver.session_scope():
        dot = viz.create_graphviz(pg_driver.nodes())
        dot.render("tests/integration/test_suite_data.gv")


def get_all_indices(es: elasticsearch.Elasticsearch) -> Set[str]:
    return frozenset(
        index
        for index in itertools.chain(
            # closed indices
            es.cluster.state()["blocks"].get("indices", {}).keys(),
            # opened indices:
            es.indices.stats()["indices"].keys(),
        )
        # An index which is automatically included w/in the docker's elasticsearch instance.
        if index != ".geoip_databases"
    )


def cleanup_indices(
    es: elasticsearch.Elasticsearch, indices: Iterable[str] | None = None
) -> None:
    """Cleanup Elasticsearch cluster
    :param es: ES client
    :param indices: list of indices to delete.
    """
    for _ in range(10):
        try:
            es.cluster.health(wait_for_status="yellow")
            break
        except exceptions.ElasticsearchException:
            time.sleep(0.1)
    else:
        health = es.cluster.health()
        # Default timeout is 30 seconds, 10 iterations ~ 5 minutes
        raise Exception(f"Elasticsearch cluster offline after 5 minutes: {health}")

    if not indices:
        indices = get_all_indices(es)

    for index in indices:
        es.indices.delete(index=index, ignore=(404, 400))

    es.indices.refresh()


# region ================================= Fixtures ==========================================

# region ================================ Containers =========================================


@pytest.fixture(scope="session")
def containers() -> Iterator[Any]:
    if os.getenv("CI_COMMIT_REF_NAME"):
        yield None
        return

    docker_compose_resource = resources.files("tests.integration") / "docker"

    with (
        resources.as_file(docker_compose_resource) as p,
        compose.DockerCompose(p, compose_file_name="docker-compose.yaml") as containers,
    ):
        # indexd hosts
        indexd_port = containers.get_service_port("indexd", 80)
        indexd_host = f"http://localhost:{indexd_port}"
        os.environ["INDEXD_HOST"] = indexd_host
        containers.wait_for(url=f"{indexd_host}/_status")

        # postgres hosts
        pg_port = containers.get_service_port("postgres", 5432)
        os.environ["PG_HOST"] = f"localhost:{pg_port}"
        os.environ["PG_INDEXD_HOST"] = f"localhost:{pg_port}"

        # elasticsearch hosts
        es_port = containers.get_service_port("elasticsearch", 9200)
        es_host = f"http://localhost:{es_port}"
        os.environ["ES_HOST"] = es_host
        containers.wait_for(url=es_host)

        yield containers


# endregion ============================= Containers =========================================

# region ================================== Indexd ===========================================


@pytest.fixture
def indexd_client(
    containers: Any,
    # refresh_indexd_database: Any
) -> Iterator[client.IndexClient]:
    indexd = client.IndexClient(
        baseurl=os.environ["INDEXD_HOST"],
        auth=(os.environ["INDEXD_USER"], os.environ["INDEXD_PASS"]),
    )

    try:
        yield indexd
    finally:
        for doc in indexd.list():
            doc.delete()


CreateIndexdDocuments = Callable[[Iterable[dict]], Sequence[client.Document]]


@pytest.fixture
def create_indexd_documents(
    indexd_client: client.IndexClient,
) -> CreateIndexdDocuments:
    def _inner(records: Iterable[dict]) -> Sequence[client.Document]:
        docs = []

        # Insert indexd data:
        for record in map(dict, records):
            urls = record["urls"]
            # NOTE: 'file_state' is stored as 'state' in indexd.
            # However, this is not important as esbuild does not pay attention to 'file_state'
            # and it is removed from resulting elasticsearch documents. See PRTL-2109
            urls_metadata = {urls[0]: {"state": record.get("file_state", "validated")}}
            if "gencode_version" not in record:
                record["gencode_version"] = "neutral"

            docs.append(
                indexd_client.create(
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

        return docs

    return _inner


@pytest.fixture
def init_indexd(
    indexd_client: client.IndexClient, create_indexd_documents: CreateIndexdDocuments
) -> client.IndexClient:
    create_indexd_documents(data.INDEXD)

    return indexd_client


# endregion =============================== Indexd ===========================================

# region ================================== Graph ============================================


@pytest.fixture(scope="session")
def graph(containers: Any) -> Iterator[psqlgraph.PsqlGraphDriver]:
    pg_conn = psqlgraph.PsqlGraphDriver(
        host=os.environ["PG_HOST"],
        user=os.environ["PG_USER"],
        password=os.environ["PG_PASS"],
        database=os.environ["PG_NAME"],
    )
    engine = pg_conn.engine

    psqlgraph.create_all(engine)
    models.helpers.versioned_nodes.Base.metadata.create_all(engine)
    submission.Base.metadata.create_all(engine)
    misc.FileReport.metadata.create_all(engine)

    try:
        yield pg_conn
    finally:
        psqlgraph.drop_all(engine)
        models.helpers.versioned_nodes.Base.metadata.drop_all(engine)
        submission.Base.metadata.drop_all(engine)
        misc.FileReport.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def pg_driver(graph: psqlgraph.PsqlGraphDriver) -> Iterator[psqlgraph.PsqlGraphDriver]:
    """Add all test data to the database.

    Attempt to render a PDF representation of the test suite.

    """
    engine = graph.engine

    psqlgraph.create_all(engine)

    data.insert(graph)

    try:
        render_database(graph)
    except Exception as exc:
        logger.error("Failed to write updated database viz files: %s", exc)

    try:
        yield graph
    finally:
        psqlgraph.drop_all(engine)


@pytest.fixture
def ro_pg_driver(
    pg_driver: psqlgraph.PsqlGraphDriver,
) -> Iterator[psqlgraph.PsqlGraphDriver]:
    """Creates a read only user and returns a driver w/ said login."""
    with pg_driver.engine.connect() as conn:
        ro_user = os.environ["RO_PG_USER"]
        ro_pass = os.environ["RO_PG_PASS"]
        db_name = os.environ["PG_NAME"]
        host = os.environ["PG_HOST"]

        commands = (
            f"create user {ro_user} with password '{ro_pass}'",
            f"grant connect on database {db_name} to {ro_user}",
            f"grant select on all tables in schema public to {ro_user}",
        )

        for cmd in commands:
            conn.execute(cmd)

    try:
        yield psqlgraph.PsqlGraphDriver(
            host=host,
            user=ro_user,
            password=ro_pass,
            database=db_name,
        )
    finally:
        with pg_driver.engine.connect() as conn:
            commands = (
                f"revoke all on all tables in schema public from {ro_user}",
                f"revoke all on database {db_name} from {ro_user}",
                f"drop user {ro_user}",
            )

            for cmd in commands:
                conn.execute(cmd)


@pytest.fixture(scope="session")
def graph_factory() -> hydrator.GraphFactory:
    graph_globals = {
        "properties": {
            "project_id": "TCGA-BRCA",
            "state": "released",
            "batch_id": 1,
            "experimental_strategy": "WXS",
        }
    }

    return hydrator.GraphFactory(models, gdcdictionary.gdcdictionary, graph_globals)


# endregion =============================== Graph ============================================


@pytest.fixture
def es_client(containers: Any) -> elasticsearch.Elasticsearch:
    return elasticsearch.Elasticsearch(os.environ["ES_HOST"])


@pytest.fixture(scope="session")
def graph_models() -> Mapping[str, gdcmodels.ModelMapper]:
    return gdcmodels.get_es_models()["gdc_from_graph"]


@pytest.fixture
def test_index_data(
    es_client: elasticsearch.Elasticsearch,
    graph_models: Mapping[str, gdcmodels.ModelMapper],
) -> Iterator[tuple[elasticsearch.Elasticsearch, str]]:
    """Generate data index as a fixture for re-use between tests."""
    # Create test index with dummy docs
    index_prefix = "test_index_data"
    index_names = utils.get_index_names(index_prefix, INDEX_TYPES)

    cleanup_indices(es_client, index_names.values())

    # Create dummy esbuild docs
    for index_type in INDEX_TYPES:
        mapping = graph_models[index_type]

        es_client.indices.create(
            index=index_names[index_type],
            mappings=mapping.mappings,
            settings=mapping.settings,
        )
        es_client.indices.refresh(index=index_names[index_type])

        for doc in es_data.DOCS[index_type]:
            doc_id = doc["project_id"] if index_type == "project" else None

            es_client.index(
                index=index_names[index_type],
                document=doc,
                id=doc_id,
            )

    es_client.indices.refresh()

    # Make sure that docs are created:
    for index_type in INDEX_TYPES:
        count = es_client.count(index=index_names[index_type])["count"]

        assert count == len(es_data.DOCS[index_type])

    yield es_client, index_prefix

    cleanup_indices(es_client, index_names.values())


@pytest.fixture
def es_after_deletion(
    test_index_data: tuple[elasticsearch.Elasticsearch, str],
) -> tuple[elasticsearch.Elasticsearch, str, Set[str], Iterable[str]]:
    """Deletes some projects from the index but not updates the metadata,
    leaving build_metadata inconsistent purposefully.
    """
    es, index_prefix = test_index_data
    helper = utils.ReleaseHelper(es, audit_index="build_metadata_test")

    # Will delete these projects' data
    projects_to_delete: Iterable[str] = ("TCGA-STAD", "FM-AD")

    # Get project list before deletion
    projects_before = helper.get_project_ids(index_prefix)

    index_names = utils.get_index_names(index_prefix, INDEX_TYPES)
    # Delete documents associated with selected projects from index
    for index_type, index_name in index_names.items():
        helper.delete_docs_from_index(index_name, index_type, projects_to_delete)

    es.indices.refresh()

    return es, index_prefix, projects_before, projects_to_delete


@pytest.fixture
def setup_test(
    pg_driver: psqlgraph.PsqlGraphDriver, es_client: elasticsearch.Elasticsearch
) -> Iterator[elasticsearch.Elasticsearch]:
    cleanup_indices(es_client)

    yield es_client

    cleanup_indices(es_client)


# endregion =========================== Elasticsearch ========================================

# region ================================ Scenarios ==========================================


GenerateScenario = Callable[[str], tuple[Sequence[psqlgraph.Node], Sequence[client.Document]]]


@pytest.fixture
def generate_scenario(
    graph_factory: hydrator.GraphFactory,
    pg_driver: psqlgraph.PsqlGraphDriver,
    create_indexd_documents: CreateIndexdDocuments,
) -> GenerateScenario:
    def _from_file(
        scenario: str,
    ) -> tuple[Sequence[psqlgraph.Node], Sequence[client.Document]]:
        path = os.path.join(DATA_DIR, scenario)

        with open(path) as f:
            nodes_meta = yaml.safe_load(f)

        nodes = graph_factory.create_from_nodes_and_edges(
            nodes=nodes_meta["nodes"],
            edges=nodes_meta["edges"],
            all_props=True,
        )

        for n in nodes:
            n.acl = ["phs000178"]

        nodes, records = data.patch_test_data_get_indexd(nodes)
        docs = create_indexd_documents(records)

        case_nodes = (n for n in nodes if n.label == "case")

        with pg_driver.session_scope() as session:
            project = pg_driver.nodes(models.Project).props(code="BRCA").one()
            project.cases.extend(case_nodes)

            session.commit()

        return nodes, docs

    return _from_file


ScenarioIndex = Callable[[str], Index]


@pytest.fixture
def scenario_index(
    pg_driver: psqlgraph.PsqlGraphDriver,
    init_indexd: client.IndexClient,
    generate_scenario: GenerateScenario,
) -> ScenarioIndex:
    def make_graph(filename: str):
        generate_scenario(filename)

        active_builder = builder.ActiveGraphIndexBuilder(pg_driver, init_indexd)

        with pg_driver.session_scope():
            active_builder.cache_database()

        index = active_builder.denormalize_all()

        return Index(*index)

    return make_graph


@pytest.fixture
def apply_gencode_to_indexd(
    pg_driver: psqlgraph.PsqlGraphDriver,
    init_indexd: client.IndexClient,
    generate_scenario: GenerateScenario,
) -> client.IndexClient:
    gencode_versions = (
        ("gv_ge_0", "v22"),
        ("gv_ge_1", "v36"),
        ("gv_ge_2", None),
    )

    generate_scenario("gencode_version.yaml")

    with pg_driver.session_scope() as session:
        # remove gencode_version for all clinical_supplement to test submittable files
        cs_nodes = pg_driver.nodes(models.ClinicalSupplement).all()
        cs_docs = init_indexd.bulk_request(dids=[n.node_id for n in cs_nodes])
        for cs_doc in cs_docs:
            cs_doc.metadata["gencode_version"] = None
            cs_doc.patch()

        # apply specified gencode_version to GeneExpression to test pick up by gencode
        for submitter_id, gencode in gencode_versions:
            node = (
                pg_driver.nodes(models.GeneExpression).props(submitter_id=submitter_id).one()
            )
            doc = init_indexd.get(node.node_id)
            doc.metadata["gencode_version"] = gencode
            doc.patch()

        session.commit()

    return init_indexd


# endregion =============================== Scenarios ========================================

# region ================================== Misc =============================================


@pytest.fixture(autouse=True)
def mocked_statsd(monkeypatch: pytest.MonkeyPatch) -> None:
    def event_mock(*_, **__):
        pass

    monkeypatch.setattr(statsd, "event", event_mock)


# endregion =============================== Misc =============================================

# endregion ============================== Fixtures ==========================================
