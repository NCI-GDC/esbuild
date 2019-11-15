import pytest
from addict import Dict
from gdcdictionary import gdcdictionary
from gdcdatamodel import models
from gdcdatamodel.models.submission import TransactionLog, TransactionSnapshot
from psqlgraph import mocks

from tests.data import get_node_id


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
    }
    if version:
        json_doc['version'] = version
    if release:
        json_doc['metadata'] = {'release_number': release}
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
            for pg_link_name, pg_link_def in child._pg_links.items():
                if pg_link_def['dst_type'] == root.__class__:
                    getattr(child, pg_link_name).append(root)
                    break
            sxn.merge(root)


def create_transaction(node, old_props, action='version'):
    program, project = node.project_id.split('-', 1)
    tl = TransactionLog(program=program, project=project, is_dry_run=False,
                        state='SUCCEEDED', role='create')
    ts = TransactionSnapshot(
        id=node.node_id, action=action, old_props=old_props,
        new_props=node._props)
    tl.entities.append(ts)
    return tl


@pytest.fixture(scope='session')
def graph_factory():
    graph_globals = {
        'properties': {
            'project_id': 'TCGA-BRCA',
            'state': 'released',
            'batch_id': 1,
            'experimental_strategy': 'WXS',
        }
    }
    factory = mocks.GraphFactory(models, gdcdictionary, graph_globals)

    yield factory


@pytest.fixture
def make_subgraph(graph_factory, graph, indexd_client):
    def wrapper(nodes, edges, root_links, make_versions=False,
                latest_released=True):
        """
        :param nodes: list of nodes metadata
        :param edges: list of edges metadata
        :param root_links: links to existing via (submitter_id, node_id) pair
        :param make_versions: create older versions
        :param latest_released: release latest document as well
        :return: (created nodes, created docs, previously released docs)
        """
        graph_nodes = graph_factory.create_from_nodes_and_edges(nodes, edges,
                                                                all_props=True)
        with graph.session_scope() as sxn:
            for n in graph_nodes:
                sxn.add(n)

        link_factory_nodes(graph, graph_nodes, root_links)

        cur_docs, prev_docs = [], []
        for n in graph_nodes:
            if not n._dictionary.get('category', '').endswith('_file'):
                continue

            baseid = None
            release = '1.0'
            version = '1'
            # create a previously released version
            if make_versions:
                prev = graph_factory.node_factory.create(n.label,
                                                         all_props=True)
                tl = create_transaction(n, prev._props)
                with graph.session_scope() as sxn:
                    sxn.add(tl)

                prevd = create_indexd_for_node(indexd_client, prev, '1', '0.0',
                                               None)
                baseid = prevd.baseid
                if latest_released:
                    release = '2.0'
                    version = '2'
                prev_docs.append(prevd)

            curd = create_indexd_for_node(indexd_client, n, version, release,
                                          baseid)
            cur_docs.append(curd)

        return graph_nodes, cur_docs, prev_docs

    return wrapper


@pytest.fixture
def create_aligned_reads(graph, indexd_client, make_subgraph):
    def wrapper(workflow_state='released', make_versions=True,
                released_reads=False):
        nodes = [
            dict(label='submitted_aligned_reads', submitter_id='sar1'),
            dict(label='submitted_unaligned_reads', submitter_id='sur1'),
            dict(label='alignment_workflow', submitter_id='wf_sar1',
                 state=workflow_state),
            dict(label='alignment_workflow', submitter_id='wf_sur1',
                 state=workflow_state),
            dict(label='aligned_reads', submitter_id='ar_sar1',
                 state='submitted'),
            dict(label='aligned_reads', submitter_id='ar_sur1'),
            dict(label='aligned_reads_index', submitter_id='ari_sar1',
                 state='submitted'),
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
            latest_released=released_reads,
        )
        return nodes, latest, previous

    return wrapper


@pytest.fixture(params=[
    Dict(workflow_state='released', released_reads=False, make_versions=True),
    Dict(workflow_state='submitted', released_reads=False, make_versions=True),
    Dict(workflow_state='released', released_reads=False, make_versions=False),
    Dict(workflow_state='submitted', released_reads=False, make_versions=False),
    Dict(workflow_state='submitted', released_reads=True, make_versions=False),
    Dict(workflow_state='released', released_reads=True, make_versions=False),
])
def versioned_reads_setup(request, graph, create_aligned_reads):
    nodes, latest, previous = create_aligned_reads(
        workflow_state=request.param.workflow_state,
        released_reads=request.param.released_reads,
        make_versions=request.param.make_versions,
    )

    with graph.session_scope() as sxn:
        for n in nodes:
            if not graph.nodes().get(n.node_id):
                sxn.add(n)

    if request.param.make_versions and not request.param.released_reads:
        expected = [n for n in nodes if is_file(n) and n.state == 'submitted']
    else:
        expected = []

    latest_map = {d.did: d for d in latest}
    previous_map = {d.baseid: d for d in previous}

    expected_docs = {}
    for ldid, ldoc in latest_map.items():
        baseid = ldoc.baseid
        if baseid in previous_map:
            expected_docs[ldid] = previous_map[baseid]

    yield nodes, expected, expected_docs

    with graph.session_scope() as sxn:
        for n in nodes:
            nobj = graph.nodes().get(n.node_id)
            if nobj:
                sxn.delete(nobj)
