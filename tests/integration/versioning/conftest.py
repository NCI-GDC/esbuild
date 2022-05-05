import pytest
from addict import Dict
from gdcdatamodel.models.submission import TransactionLog, TransactionSnapshot

from tests.integration.conftest import cleanup_nodes
from tests.integration.data import get_node_id


def is_file(node):
    return node._dictionary.get('category', '').endswith('_file')


def generate_urls_metadata(node_id, filename):
    return {
        's3://cleversafe.service.consul/bucket/TCGA/BRCA/{}/{}'.format(node_id,filename): {
            'type': 'cleversafe',
            'state': 'validated',
        }
    }


def create_indexd_for_node(client, node, version, release, baseid):
    urls_metadata = generate_urls_metadata(node.node_id, node.file_name)

    json_doc = {
        'did': node.node_id,
        'hashes': {'md5': node.md5sum},
        'size': node.file_size,
        'file_name': node.file_name,
        'urls': list(urls_metadata.keys()),
        'urls_metadata': urls_metadata,
        'acl': ['phs000178'],
        'metadata': {'gencode_version': 'neutral'}
    }
    if version:
        json_doc['version'] = version
    if release:
        json_doc['metadata'].update({'release_number': release})
    if baseid:
        json_doc['baseid'] = baseid

    doc = client.create(**json_doc)
    return doc


def link_factory_nodes(graph, nodes, links, map_key='submitter_id'):
    nodes_map = {getattr(n, map_key): n for n in nodes}
    with graph.session_scope() as sxn:
        for link in links:
            src_id = link[0]
            dst_id = link[1]
            root = graph.nodes().get(dst_id)
            child = nodes_map[src_id]
            for pg_edge_name, pg_edge_def in root._pg_edges.items():
                if pg_edge_def['type'] == child.__class__:
                    getattr(root, pg_edge_name).append(child)
            sxn.merge(root)


def create_transaction(graph, node, old_props, action='version'):
    program, project = node.project_id.split('-', 1)
    tl = TransactionLog(program=program, project=project, is_dry_run=False,
                        state='SUCCEEDED', role='create')
    ts = TransactionSnapshot(
        id=node.node_id, action=action, old_props=old_props,
        new_props=node._props)
    tl.entities.append(ts)

    with graph.session_scope() as sxn:
        sxn.add(tl)

    return tl


@pytest.fixture
def make_subgraph(graph_factory, pg_driver, indexd_client):
    graph_nodes = []

    def wrapper(nodes, edges, root_links, make_versions=False):
        """
        :param nodes: list of nodes metadata
        :param edges: list of edges metadata
        :param root_links: links to existing via (submitter_id, node_id) pair
        :param make_versions: create older versions
        :return: (created nodes, created docs, previously released docs)
        """
        graph_nodes.extend(
            graph_factory.create_from_nodes_and_edges(nodes, edges,
                                                      all_props=True)
        )
        with pg_driver.session_scope() as sxn:
            for n in graph_nodes:
                sxn.add(n)

        link_factory_nodes(pg_driver, graph_nodes, root_links)

        cur_docs, prev_docs = [], []
        for n in graph_nodes:
            if not n._dictionary.get('category', '').endswith('_file'):
                continue

            baseid = None
            release = '1.0'
            version = '1'
            # create a previously released version
            if make_versions:
                prev = graph_factory.node_factory.create(
                    n.label, all_props=True,
                    override={'submitter_id': n.submitter_id}
                )
                create_transaction(pg_driver, n, prev._props)

                prevd = create_indexd_for_node(indexd_client, prev, version,
                                               release, None)
                baseid = prevd.baseid

                # If node in graph is released, we should also release the doc
                released = n.state == 'released'
                release = '2.0' if released else None
                version = '2' if released else None
                prev_docs.append(prevd)
            else:
                create_transaction(pg_driver, n, {}, action='create')

            curd = create_indexd_for_node(indexd_client, n, version, release,
                                          baseid)
            cur_docs.append(curd)

        return graph_nodes, cur_docs, prev_docs

    yield wrapper

    cleanup_nodes(pg_driver, graph_nodes)


@pytest.fixture
def create_aligned_reads(indexd_client, make_subgraph):
    def wrapper(workflow_state='released', make_versions=True,
                reads_state='submitted'):
        """
        This fixture creates 2 subtrees starting from SUR and SAR.
        AlignedReads/AlignedReadsIndex nodes under SUR are always released and
        AlignedReads/AlignedReadsIndex nodes under SAR have variable states
        AlignmentWorkflow nodes for both subtrees also vary (submitted/released)

        Subtree structures:
            SAR <- AWF <- AR <- ARI
            SUR <- AWF <- AR <- ARI

        :param workflow_state: AlignmentWorkflow nodes state for both subtrees
        :param make_versions: Make version for AR/ARI for SAR subtree
        :param reads_state: node state for AR/ARI for SAR subtree
        :return: tuple containing:
            0: all created nodes
            1: latest indexd docs (potentially unreleased)
            2: previous versions of indexd (always released)
        """
        nodes = [
            dict(label='submitted_aligned_reads', submitter_id='sar1'),
            dict(label='submitted_unaligned_reads', submitter_id='sur1'),
            dict(label='alignment_workflow', submitter_id='wf_sar1',
                 state=workflow_state),
            dict(label='alignment_workflow', submitter_id='wf_sur1',
                 state=workflow_state),
            dict(label='aligned_reads', submitter_id='ar_sar1',
                 state=reads_state),
            dict(label='aligned_reads', submitter_id='ar_sur1'),
            dict(label='aligned_reads_index', submitter_id='ari_sar1',
                 state=reads_state),
            dict(label='aligned_reads_index', submitter_id='ari_sur1'),
        ]

        edges = [
            dict(src='wf_sar1', dst='sar1'),
            dict(src='ar_sar1', dst='wf_sar1'),
            dict(src='ari_sar1', dst='ar_sar1'),
            dict(src='wf_sur1', dst='sur1'),
            dict(src='ar_sur1', dst='wf_sur1'),
            dict(src='ari_sur1', dst='ar_sur1'),
        ]
        links = [
            ('sar1', get_node_id('read-group-2')),
            ('sur1', get_node_id('read-group-2')),
        ]
        nodes, latest, previous = make_subgraph(
            nodes=nodes, edges=edges, root_links=links,
            make_versions=make_versions,
        )
        return nodes, latest, previous

    return wrapper


@pytest.fixture(params=[
    Dict(workflow_state='released', reads_state='released', make_versions=True),
    Dict(workflow_state='released', reads_state='released', make_versions=False),
    Dict(workflow_state='released', reads_state='submitted', make_versions=True),
    Dict(workflow_state='released', reads_state='submitted', make_versions=False),
    Dict(workflow_state='submitted', reads_state='released', make_versions=True),
    Dict(workflow_state='submitted', reads_state='released', make_versions=False),
    Dict(workflow_state='submitted', reads_state='submitted', make_versions=True),
    Dict(workflow_state='submitted', reads_state='submitted', make_versions=False),
])
def versioned_reads_setup(request, pg_driver, create_aligned_reads):
    """
    A fixture that generates different data setups.
    Yields a tuple:
        0: all created nodes in graph
        1: nodes that are expected to have previous versions
        2: IndexD documents corresponding to the above nodes
        3: fixture params

    workflow    | reads_state   | make_versions | expected doc diffs
    ============|===============|===============|====================
    released    | released      | True          | []
    released    | released      | False         | []
    released    | submitted     | True          | [ar_sar1, ari_sar1]
    released    | submitted     | False         | []
    submitted   | released      | True          | []
    submitted   | released      | False         | []
    submitted   | submitted     | True          | [ar_sar1, ari_sar1]
    submitted   | submitted     | False         | []
    """
    nodes, latest, previous = create_aligned_reads(**request.param.to_dict())

    if request.param.make_versions and request.param.reads_state != 'released':
        expected = [n for n in nodes if is_file(n) and n.state == 'submitted']
    else:
        expected = []

    latest_map = {d.did: d for d in latest}
    previous_map = {d.baseid: d for d in previous}

    versioned_docs = {}

    for exp in expected:
        ldid, ldoc = exp.node_id, latest_map[exp.node_id]
        baseid = ldoc.baseid
        if baseid in previous_map:
            versioned_docs[ldid] = previous_map[baseid]

    yield nodes, expected, versioned_docs, request.param


@pytest.fixture
def versioned_reads_expectations(versioned_reads_setup, indexd_client):
    """
    Fixture that generates ES document expectations in terms of metadata from
    IndexD. Yields a mapping in a form: {graph_node_id: expected_indexd_doc}

    workflow    | reads_state   | make_versions | expected
    ============|===============|===============|=======================
    released    | released      | True          | ar_sur1_v2, ar_sar1_v2
    released    | released      | False         | ar_sur1_v1, ar_sar1_v1
    released    | submitted     | True          | ar_sur1_v2, ar_sar1_v1
    released    | submitted     | False         | ar_sur1_v1
    submitted   | released      | True          | None
    submitted   | released      | False         | None
    submitted   | submitted     | True          | None
    submitted   | submitted     | False         | None

    """
    nodes, exp_nodes, exp_docs, params = versioned_reads_setup

    if params['workflow_state'] != 'released':
        expectations = {}
    elif params['reads_state'] == 'released':
        ars = [n for n in nodes if n.label == 'aligned_reads']
        expectations = {
            ar.node_id: indexd_client.get_latest_version(ar.node_id)
            for ar in ars
        }
    elif params['make_versions']:
        ars = [n for n in nodes if n.label == 'aligned_reads']
        expectations = {
            ar.node_id: indexd_client.get_latest_version(ar.node_id, True)
            for ar in ars
        }
    else:
        ar = [n for n in nodes
              if n.label == 'aligned_reads' and n.state == 'released'][0]
        expectations = {ar.node_id: indexd_client.get(ar.node_id)}

    yield expectations
