"""esbuild.graph.common.builder.

Defines :class:`GraphIndexBuilder` for use building the primary GDC
graph index.

"""

import collections
import copy
import functools
import hashlib
import itertools
import logging
import re
import traceback
import types
import uuid
from collections.abc import (
    Collection,
    Container,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    Set,
)
from typing import Any, Optional, TypeVar, Union, cast

import more_itertools
import networkx as nx
import progressbar
import psqlgraph
from datadog.dogstatsd.base import statsd
from gdcdatamodel2 import models
from indexclient import client
from sqlalchemy import orm

from esbuild.graph.common import mappings, validators

PTree = dict[models.Node, "PTree"]
TDocument = TypeVar("TDocument", dict, list[dict])

log = logging.getLogger(__name__)

AVAILABLE_GENCODE_VERSIONS = frozenset(["neutral", "v22", "v36"])
"""All possible gencode versions."""
FILE_MISSING_GENCODE: dict[str, str] = {
    "error": "no gencode_version for generated data files"
}
"""The error message associated with file which have no associated gencode version."""
ENTRY_FOR_WRONG_GENCODE = {"ignore": "wrong gencode_version for generated data files"}
"""The error message associated with file which have no document associated with an
appropriate gencode version.
"""
FIELD_ALLOWLIST = frozenset({"wgs_coverage", "specimen_type"})
"""Special fields which must be whitelisted to be included.
NOTE: New models should make this redundant.
"""
INDEX_FILE_EXTENSIONS: Set[str] = frozenset(
    (
        ".bai",
        ".tbi",
    )
)
"""File extensions associated with index files."""
POSSIBLE_ASSOCIATED_ENTITIES: Collection[str] = (
    "portion",
    "aliquot",
    "case",
    "slide",
)
"""All possible node types which can be considered associated entities."""
DATA_FILE_INDEXD_FIELDS = ("acl", "file_size", "file_name", "file_state", "md5sum")
"""The fields associated with indexd records which should be included in the file
document.
"""
DIFFERENTIATED_EDGES: Set[tuple[str, str, str]] = frozenset(
    (
        ("file", "member_of", "archive"),
        ("archive", "member_of", "file"),
        ("file", "describes", "case"),
        ("case", "describes", "file"),
        ("file", "related_to", "file"),
    )
)
"""Edges which will need extra data associated with them cached."""
INDEXD_URL_TYPE = "cleversafe"
"""The url type associated with files to be indexed in the build."""
FLATTENED_OBJECTS = types.MappingProxyType(
    {
        "tag": "name",
        "platform": "name",
        "data_format": "name",
        "data_subtype": "name",
        "experimental_strategy": "name",
        "data_level": "name",
    }
)
"""Nested object's who's associated property will be included in the indexed document of
the parent. E.g. the tag node's name property will be pulled up into the parent node's
document representation in the final indexed document.
"""
OMITTED_PROJECTS: Set[tuple[str, str]] = frozenset(
    (
        ("TCGA", "CNTL"),
        ("TCGA", "MISC"),
        ("TCGA", "TEST"),
        ("TCGA", "DEV1"),
        ("TCGA", "DEV2"),
        ("TCGA", "DEV3"),
        ("TCGA", "FPPP"),
        ("GDC", "INTERNAL"),
        ("UAT08", "BROAD-BCR"),
        ("TARGET", "AML-IF"),
        ("CCLE", "CCLE_V2"),
        ("CCLE", "ALL-P1"),
        ("CCLE", "ACC"),
        ("CCLE", "DLBC"),
        ("CCLE", "READ"),
        ("CCLE", "GBM"),
        ("CCLE", "THCA"),
        ("CCLE", "BLCA"),
        ("CCLE", "UCEC"),
        ("CCLE", "PCPG"),
        ("CCLE", "LCML"),
        ("CCLE", "CESC"),
        ("CCLE", "UCS"),
        ("CCLE", "THYM"),
        ("CCLE", "LIHC"),
        ("CCLE", "CHOL"),
        ("CCLE", "HNSC"),
        ("CCLE", "STAD"),
        ("CCLE", "SKCM"),
        ("CCLE", "COAD"),
        ("CCLE", "UVM"),
        ("CCLE", "PAAD"),
        ("CCLE", "TGCT"),
        ("CCLE", "LUSC"),
        ("CCLE", "CNTL"),
        ("CCLE", "MISC"),
        ("CCLE", "MESO"),
        ("CCLE", "FPPP"),
        ("CCLE", "OV"),
        ("CCLE", "ESCA"),
        ("CCLE", "LCLL"),
        ("CCLE", "MM"),
        ("CCLE", "SARC"),
        ("CCLE", "KIRP"),
        ("CCLE", "LGG"),
        ("CCLE", "LAML"),
        ("CCLE", "PRAD"),
        ("CCLE", "LUAD"),
        ("CCLE", "BRCA"),
        ("CCLE", "KIRC"),
        ("CCLE", "KICH"),
    )
)
"""Projects which should always be omitted from the build."""
SUPPLEMENT_PATTERNS = tuple(
    map(
        lambda s: re.compile(s),
        (
            r"nationwidechildrens.org_biospecimen.([a-zA-Z0-9-]+).xml",
            r"nationwidechildrens.org_control.([a-zA-Z0-9-]+).xml",
            r"genome.wustl.edu_biospecimen.([a-zA-Z0-9-]+).xml",
            r"genome.wustl.edu_control.([a-zA-Z0-9-]+).xml",
            r"nationwidechildrens.org_clinical.([a-zA-Z0-9-]+).xml",
            r"genome.wustl.edu_clinical.([a-zA-Z0-9-]+).xml",
        ),
    )
)
"""The patterns which match older supplement file names."""


@functools.lru_cache(maxsize=32)
def dfs_to_parent(node, target="case"):
    if node.label == target:
        return node
    for edge in node.edges_out:
        found = dfs_to_parent(edge.dst)
        if found:
            return found
    return None


def _get_gencode_version(doc: Optional[client.Document]) -> Optional[str]:
    if not doc:
        return None

    gencode_version = doc.to_json().get("metadata", {}).get("gencode_version")

    return gencode_version


def _load_hidden_properties() -> Iterator[tuple[str, Set[str]]]:
    default_properties = frozenset(("batch_id", "file_state"))
    labels = (t.label for t in models.Node.get_subclasses() if t.label != "annotation")

    for label in labels:
        yield label, default_properties

    yield "annotation", frozenset(("creator", *default_properties))


HIDDEN_PROPERTIES = types.MappingProxyType(dict(_load_hidden_properties()))
"""A mapping of node types to the properties which should be omitted from the final
indexed document."""


class GraphIndexBuilder:
    """Build graph index from gdc psqlgraph.

    The Process Explained:

    This class handles all the JSON production for the GDC
    portal. Currently, the entire postgresql database is cached to
    memory.  To save space, edge labels are only maintained if we need
    to distinguish between two different types of edges between a
    single pair of node types.

    Currently, the entire batch of JSON documents is produced at once
    for reasons that follow. There are two topmost denormalization
    functions that are called, denormalize_cases() and
    denormalize_projects(). The former produces all the
    case, file, and annotations documents. The latter produces
    the project summaries.

    The case denormalization takes the case tree from
    gdcdatamodel and, starting at a case, walks recursively to
    all possible children.  Each child's properties are added to the
    case document at the appropriate level depending on the
    correlation (one to one=singleton, or one to many=list).  The leaf
    node for most paths from case are files, which have a
    special denormalization.

    When a file is gathered from walking the case path, a deep
    copy is both added to the cases file list returned for
    later collection.  Denormalizing a case produces a list of
    files and annotations. Each file is upserted into a persisting
    list of files.  If after denormalizing case 1 who produced
    file A, the upsert involves adding to A the list if not present.
    If we have already gotten file A from another case, it
    means that the file came from multiple cases, and we have to
    update file A to also reference case 1.

    In order to make decrease the processing time, there are a lot of
    caching initiatives.  The paths from cases to files are
    cached. The set of files using each data type and experimental
    strategy are cached.  There is also a caching scheme for
    remembering which nodes are walked through a lot and remembering
    which neighbors they have with a given label.

    Args:
        psqlgraph_driver: The driver for interacting with the graph.
        indexd_client: The client for accessing indexd documents.
        index_prefix: The prefix of the index name being created (used for logging
            only.)
        build_projects: The projects which should be included in the build.
        build_awg: A flag indicating if this is an AWG build.
        selective_caching: A flag indicating if selective caching functionality
            should be used.
        versioned_files: Versioned files that haven't been released yet.
        allowed_gencode_versions: The gencode version allowed when selecting file
            objects to index.
        case_to_file_paths: All possible paths from a case node to all relevant file
            nodes.
        file_labels: All of the node labels which are associated with files to be
            included in the build.
        unindexed_by_property: A mapping of filtered nodes which if their properties
            are a superset of any of the dictionaries listed here are removed from
            being indexed.
    """

    def __init__(
        self,
        psqlgraph_driver: psqlgraph.PsqlGraphDriver,
        indexd_client: client.IndexClient,
        index_prefix: Optional[str],
        build_projects: Iterable[str],
        build_awg: bool,
        selective_caching: bool,
        versioned_files: Mapping[str, Mapping[str, Any]],
        allowed_gencode_versions: Set[str],
        case_to_file_paths: Iterable[Sequence[str]] = (),
        file_labels: Collection[str] = (),
        unindexed_by_property: Mapping[
            str, Iterable[Mapping[str, Any]]
        ] = types.MappingProxyType({}),
    ) -> None:
        self.g = psqlgraph_driver
        self.indexd = indexd_client
        self.index_prefix = index_prefix

        self.versioned_files = versioned_files

        if not (allowed_gencode_versions <= AVAILABLE_GENCODE_VERSIONS):
            raise NotImplementedError(
                f"{allowed_gencode_versions} is not a valid gencode_version requirement"
                f"The available gencode_versions are {AVAILABLE_GENCODE_VERSIONS}"
            )

        self.allowed_gencode_versions = allowed_gencode_versions
        self.build_awg = build_awg
        self.selective_caching = selective_caching
        # The original project ids are split into program/project name as tuples
        # E.g. "TCGA-ACC" -> ("TCGA", "ACC")
        self.build_projects: Iterable[tuple[str, str]] = tuple(
            cast(tuple[str, str], tuple(p.split("-", 1))) for p in build_projects
        )

        self.case_to_file_paths = case_to_file_paths
        self.file_to_case_paths = tuple(
            tuple(more_itertools.value_chain(reversed(l[:-1]), "case"))
            for l in self.case_to_file_paths
        )
        """A calculated field based on the case to file paths reversed."""
        self.file_labels = file_labels
        self.unindexed_by_property = unindexed_by_property

        # VARIOUS CACHES
        self.annotation_entities: dict[models.Node, dict[str, dict]] = {}
        """A cache mapping a node to to a mapping of annotation ids which are mapped
        themselves to their denormalized doc.
        """
        self.annotations: Collection[models.Node] = ()
        """A cache of the annotations for the build."""
        self.cases: Sequence[models.Node] = ()
        """A cache of the cases for the build."""
        self.data_categories: dict[str, set[models.Node]] = collections.defaultdict(set)
        """A cache of data categories mapped to their associated files nodes."""
        self.entity_cases: dict[models.Node, models.Node] = {}
        """A cache possible associated entities mapped to their associated case."""
        self.experimental_strategies: dict[
            str, set[models.Node]
        ] = collections.defaultdict(set)
        """A cache of experimental strategies mapped to their associated files."""
        self.file_metadata: dict[str, dict] = {}
        """A cache of file metadata from indexd."""
        self.G = nx.Graph()
        """A cache of the data within the actual gdc graph."""
        self.popular_nodes: dict[
            models.Node, dict[tuple[str, ...], Set[models.Node]]
        ] = collections.defaultdict(dict)
        """A cache of common neighbors to a particular node. The node is mapped to a
        mapping of particular sets of labels which in turn are mapped to the nodes of
        those types associated with the original node.
        """
        self.projects: Collection[models.Node] = ()
        """A cache of project nodes."""
        self.relevant_nodes: dict[models.Node, Set[models.Node]] = {}
        """A cache which maps file nodes to their associated cased nodes."""
        self.skipped_nodes: dict[
            str, list[Union[models.Node, tuple[models.Node, str]]]
        ] = collections.defaultdict(list)
        """A cache of nodes skipped in the build and the reason for skipping them."""

    def warning(self, title: str, text: str, tags: Optional[list[str]] = None) -> None:
        tags = tags or []
        tags.append(f"index_group:{self.index_prefix}")

        log.warning(f"{title}: {text}")
        statsd.event(
            title,
            text,
            source_type_name="esbuild",
            alert_type="warning",
            tags=tags,
        )

    def error(self, title: str, text: str, tags: Optional[list[str]] = None):
        tags = tags or []
        tags.append(f"index_group:{self.index_prefix}")

        log.error(f"{title}: {text}")
        statsd.event(
            title,
            text,
            source_type_name="esbuild",
            alert_type="error",
            tags=tags,
        )

    def pbar(self, title: str, maxval: int) -> progressbar.ProgressBar:
        """Create and initialize a custom progressbar.

        :param str title: The text of the progress bar
        :param int maxval: The maximum value of the progress bar

        """
        maxval = maxval or 1  # prevent maxal of 0
        pbar = progressbar.ProgressBar(
            widgets=[
                title,
                progressbar.Percentage(),
                " ",
                progressbar.Bar(marker="#", left="[", right="]"),
                " ",
                progressbar.ETA(),
                " ",
            ],
            max_value=maxval,
        )
        pbar.update(0)
        return pbar

    ###################################################################
    #                        Tree functions
    ###################################################################

    def create_tree(self, node: models.Node, mapping: Mapping, tree: PTree) -> PTree:
        """Recursively walk a mapping to create a walkable tree."""
        if node.label in ("center", "tissue_source_site"):
            return {}
        submap = mapping[node.label]
        corr, plural = submap["corr"]
        for child in self.G.neighbors(node):
            if child.label not in submap:
                continue
            tree[child] = {}
            self.create_tree(child, submap, tree[child])
        return tree

    def walk_tree(
        self,
        node: models.Node,
        tree: dict[models.Node, dict],
        mapping: dict[str, dict],
        doc: TDocument,
        level: int = 0,
        ids: Optional[Mapping[str, set[str]]] = None,
    ) -> TDocument:
        """Add the properties of node neighbors to doc.

        Recursively walk from a node to all possible neighbors that are
        allowed in the tree structure.  Add the node's properties to the doc.

        """
        corr, plural = mapping[node.label]["corr"]

        # NOTE: we need to add some extra properties for deeply nested annotation
        #   documents.
        if node.label == "annotation":
            subdoc = self.denormalize_annotation(node)
        else:
            subdoc = self._get_base_doc(node)

        for child in tree[node]:
            child_corr, child_plural = mapping[node.label][child.label]["corr"]
            if child_plural not in subdoc and child_corr == mappings.ONE_TO_ONE:
                subdoc[child_plural] = {}
            elif child_plural not in subdoc:
                subdoc[child_plural] = []
            self.walk_tree(
                child,
                tree[node],
                mapping[node.label],
                subdoc[child_plural],
                level + 1,
                ids=ids,
            )

            # Aggregate ids as we walk the tree
            if ids is not None and child.label in mappings.TOP_LEVEL_IDS:
                ids[f"{child.label}_ids"].add(child.node_id)
                sub_id = child._props.get("submitter_id")
                if sub_id is not None:
                    ids[f"submitter_{child.label}_ids"].add(sub_id)

        if corr == mappings.ONE_TO_MANY:
            assert isinstance(doc, list)
            doc.append(subdoc)
        else:
            assert isinstance(doc, dict)
            doc.update(subdoc)
        return doc

    def copy_tree(self, original: PTree, new: PTree) -> PTree:
        """Recursively copy the tree so that it can later be pruned per file."""
        for node in original:
            new[node] = {}
            self.copy_tree(original[node], new[node])
        return new

    def _get_base_doc(self, node: models.Node, include_id: bool = True) -> dict:
        """Create a dictionary with all the properties of a node.

        This is the basic document generator.  Take all the properties of a
        node and add it to the result.  The result doc will have *_id
        where * is the node type.

        """
        base = {}
        old_props = self.versioned_files.get(node.node_id, {})

        if include_id and node.label in self.file_labels:
            base.update({"file_id": old_props.get("file_id") or node.node_id})

        elif include_id and node._dictionary["category"] == "analysis":
            base.update({"analysis_id": node.node_id})

        elif include_id:
            base.update({f"{node.label}_id": node.node_id})

        base.update(
            {
                key: old_props.get(key) or value
                for key, value in node._props.items()
                # Only use props in the pinned version of the dictionary
                # Also include manually included fields form allowlist.
                if (key in node.__pg_properties__ or key in FIELD_ALLOWLIST)
                # Ignore certain keys by type
                and key not in HIDDEN_PROPERTIES.get(node.label, ())
                # Hide project_id for all nodes but project, viz. PGDC-1550
                and (key != "project_id" or node.label == "project")
            }
        )

        return base

    ###################################################################
    #                        Path functions
    ###################################################################

    def walk_path(
        self, node: models.Node, path: Sequence[str], whole: bool = False
    ) -> Iterator[models.Node]:
        """Get a node from end of a path or all the nodes along the path.

        Given a list of strings, treat it as a path, and yield the end of
        possible traversals.  If `whole` is true, return every node
        along the traversal.

        """
        if path:
            for neighbor in self.neighbors_labeled(node, path[0]):
                if whole or (len(path) == 1 and path[0] == neighbor.label):
                    yield neighbor

                yield from self.walk_path(neighbor, path[1:], whole)

    def walk_paths(
        self, node: models.Node, paths: Iterable[Sequence[str]], whole: bool = False
    ) -> Set[models.Node]:
        """Get nodes from walking paths.

        Given a list of paths, yield the result of walking each path. If
        `whole` is true, return every node along each traversal.

        """
        return frozenset(
            itertools.chain.from_iterable(
                self.walk_path(node, path, whole=whole) for path in paths
            )
        )

    def remove_bam_index_files(self, files: Iterable[models.Node]) -> Set[models.Node]:
        return {f for f in files if not self.is_index_file(f)}

    ###################################################################
    #                          Cases
    ##################################################################

    def remove_hidden_nodes(self, nodes: Iterable[models.Node]) -> Set[models.Node]:
        """Get subset of nodes whose self.is_node_hidden(node) is False.

        Returns a subset of :param:`nodes` for which
        ``self.is_node_hidden(node)`` is not True.

        :param nodes: iterable of nodes to filter
        :returns: subset set of :param:`nodes`

        """
        return {node for node in nodes if not validators.is_node_hidden(node)}

    def get_case_files(self, node: models.Node) -> Collection[models.Node]:
        """Return a list of file nodes by walking out from case."""
        files: Iterable[models.Node] = self.walk_paths(node, self.case_to_file_paths)
        # Set file metadata fields from indexd as node properties
        files = (self.add_file_metadata_from_indexd(f) for f in files)

        files = self.remove_bam_index_files(files)
        files = self.remove_hidden_nodes(files)

        return files

    def get_case_tree(self, node: models.Node) -> tuple[dict, PTree]:
        """Use tree to create nested json.

        :returns: doc, ptree, visited_ids

        """
        ptree = self.get_case_ptree(node)
        visited_ids: Mapping[str, set[str]] = collections.defaultdict(set)
        doc = self.walk_tree(
            node, ptree, mappings.CASE_TREE, cast(list[dict], []), ids=visited_ids
        )[0]

        # Inject a dictionary of ids for each visited entity (in
        # TOP_LEVEL_IDS)
        # Convert to list for later serialization
        doc.update((key, list(ids)) for key, ids in visited_ids.items())

        return doc, ptree

    def get_case_ptree(self, node: models.Node) -> PTree:
        """Walk graph naturally for tree of node objects."""
        return {node: self.create_tree(node, mappings.CASE_TREE, {})}

    def denormalize_case(self, node: models.Node) -> tuple[dict, list[dict], list]:
        """Get the entire case document for a case node.

        Given a case node, return the entire case document,
        the files belonging to that case, and the annotations
        that were aggregated to those files.

        """
        # Walk from case to leaves (not files) and create a case doc,
        # a participant tree, and a list of visited ids
        case, ptree = self.get_case_tree(node)

        # Get the file nodes related to the case
        files = self.get_case_files(node)

        # Create case summary
        case["summary"] = self.get_case_summary(files)

        # Take any out of place nodes and put then in correct place in tree
        self.reconstruct_biospecimen_paths(case)
        case = self.reconstruct_diagnoses_paths(case)

        # Get the case's project
        project = self.patch_project(case["project"])

        # Denormalize the cases files
        returned_files = self.get_case_file_docs(ptree, files)

        # Add files to cases
        # Do not add cases, annotations and associated entities to case.files
        case["files"] = [
            {
                k: f[k]
                for k in f
                if k not in ["cases", "annotations", "associated_entities"]
            }
            for f in copy.deepcopy(returned_files)
        ]

        # Do not include input_files in case.files.analysis (TT-928)
        for f in case["files"]:
            if "analysis" in f:
                f["analysis"].pop("input_files", None)

        self.validate_case(node, case)

        return case, returned_files, []

    def get_case_file_docs(
        self, ptree: PTree, files: Iterable[models.Node]
    ) -> list[dict]:
        """Given a list of files, return a list of file docs."""
        return [self.denormalize_file(file_, ptree) for file_ in files]

    def get_exp_strats(self, files: Iterable[models.Node]) -> Iterator[dict]:
        """Get files experimental strategies.

        Get the set of experimental_strategies where intersection of the
        set `files` and the set of files that relate to that
        experimental_strategy is non-null

        """
        for exp_strat, file_list in self.experimental_strategies.items():
            intersection = file_list.intersection(files)
            if intersection:
                yield {
                    "experimental_strategy": exp_strat,
                    "file_count": len(intersection),
                }

    def get_data_categories(self, files: Iterable[models.Node]) -> Iterator[dict]:
        """Get files data category.

        Get the set of data_categories where intersection of the
        set `files` and the set of files that relate to that
        data_category is non-null

        """
        for data_category, file_list in self.data_categories.items():
            intersection = file_list.intersection(files)
            if intersection:
                yield {
                    # data_type is renamed data_category, viz.
                    # https://jira.opensciencedatacloud.org/browse/PGDC-1472
                    "data_category": data_category,
                    "file_count": len(intersection),
                }

    def get_case_summary(self, files: Collection[models.Node]) -> dict:
        """Create a dictionary with summary information about case files.

        Generate a dictionary containing a summary of a cases files
        and file classifications

        """
        return {
            "file_count": len(files),
            "file_size": sum(f["file_size"] or 0 for f in files),
            "experimental_strategies": list(self.get_exp_strats(files)),
            # data_type is renamed data_category, viz.
            # https://jira.opensciencedatacloud.org/browse/PGDC-1472
            "data_categories": list(self.get_data_categories(files)),
        }

    @staticmethod
    def reconstruct_diagnoses_paths(case: dict) -> dict:
        """Reconstruct path for molecular tests.

        There are two different paths from diagnoses to molecular tests:
        1. diagnoses -> molecular test
        2. diagnoses -> follow up -> molecular test
        For those nodes in path 1, add a dummy `follow up` nodes, so that it can be
        reached through `case.follow_ups.molecular_tests`

        Args:
            case: dictionary of case node

        Returns:
            updated case dictionary
        """
        case_copy = copy.deepcopy(case)
        correct_molecular_tests = set()
        for follow_up in case_copy.get("follow_ups", []):
            for molecular_test in follow_up.get("molecular_tests", []):
                correct_molecular_tests.add(molecular_test["molecular_test_id"])

        for diagnosis in case_copy.get("diagnoses", []):
            molecular_tests = diagnosis.pop("molecular_tests", [])
            for molecular_test in molecular_tests:
                molecular_test_id = molecular_test["molecular_test_id"]
                if molecular_test_id not in correct_molecular_tests:
                    log.info(f"Moving {molecular_test_id} to correct location")
                    case_copy["follow_ups"] = case_copy.get("follow_ups", [])
                    case_copy["follow_ups"].append(
                        {
                            "follow_up_id": get_namespaced_uuid(
                                ns="molecular_tests",
                                seed=molecular_test_id,
                            ),
                            "molecular_tests": [molecular_test],
                        }
                    )
        return case_copy

    def reconstruct_biospecimen_paths(self, case: dict) -> None:
        """For each sample.aliquot or sample.slide, reconstruct entire path.

        Note: the path is culled in common/mappings.py
        in get_case_mapping. The new path(s) need to be popped
        there or tests will fail.
        """
        # Get all the "correct" aliquots and slides, save them
        # so we can differentiate between these and the other
        # linked ones
        samples = case.get("samples", [])
        correct_aliquots = set()
        correct_slides = set()
        correct_analytes = set()
        for sample in samples:
            for portion in sample.get("portions", []):
                for slide in portion.get("slides", []):
                    correct_slides.add(slide["slide_id"])
                for analyte in portion.get("analytes", []):
                    correct_analytes.add(analyte["analyte_id"])
                    for aliquot in analyte.get("aliquots", []):
                        correct_aliquots.add(aliquot["aliquot_id"])

        for sample in samples:
            sample["portions"] = sample.get("portions", [])

            # Get all analytes connected to samples (TT-260)
            sample_analytes = sample.pop("analytes", [])
            for analyte in sample_analytes:
                # put analyte under portion
                if analyte["analyte_id"] not in correct_analytes:
                    log.info(
                        "Moving {} to correct location".format(analyte["analyte_id"])
                    )
                    sample["portions"].append(
                        {
                            "portion_id": get_namespaced_uuid(
                                ns="analytes", seed=analyte["analyte_id"]
                            ),
                            "analytes": [analyte],
                        }
                    )

            # Get all slides connected to samples (SVT-249)
            sample_slides = sample.pop("slides", [])
            for slide in sample_slides:
                # Put slide under portion
                if slide["slide_id"] not in correct_slides:
                    log.info("Moving {} to correct location".format(slide["slide_id"]))
                    sample["portions"].append(
                        {
                            "portion_id": get_namespaced_uuid(
                                ns="slides", seed=slide["slide_id"]
                            ),
                            "slides": [slide],
                        }
                    )

            # Get all aliquots connected to samples
            sample_aliquots = sample.pop("aliquots", [])
            for aliquot in sample_aliquots:
                # Put aliquot under analyte
                if aliquot["aliquot_id"] not in correct_aliquots:
                    analyte_id = get_namespaced_uuid(
                        ns="aliquots", seed=aliquot["aliquot_id"]
                    )
                    portion_id = get_namespaced_uuid(ns="analytes", seed=analyte_id)
                    new_dict: dict = {
                        "analytes": [{"analyte_id": analyte_id, "aliquots": [aliquot]}]
                    }
                    # check if another entry already added the fake id
                    if "portion_id" not in sample["portions"]:
                        new_dict["portion_id"] = portion_id
                    sample["portions"].append(new_dict)

            for portion in sample["portions"]:
                portion["analytes"] = portion.get("analytes", [])

                # Get aliquots connected to portions
                portion_aliquots = portion.pop("aliquots", [])
                for aliquot in portion_aliquots:
                    # Put aliquot under analyte
                    if aliquot["aliquot_id"] not in correct_aliquots:
                        portion["analytes"].append(
                            [
                                {
                                    "analyte_id": get_namespaced_uuid(
                                        ns="aliquots", seed=aliquot["aliquot_id"]
                                    ),
                                    "aliquots": [aliquot],
                                }
                            ]
                        )

    def patch_project(self, project_doc: dict) -> dict:
        # Delete some keys from project document
        for key in mappings.HIDDEN_PROJECT_KEYS:
            project_doc.pop(key, None)

        # Populate project_id
        code = project_doc.pop("code")
        program = project_doc["program"]["name"]
        project_id = f"{program}-{code}"
        project_doc["project_id"] = project_id

        return project_doc

    ###################################################################
    #                       File denormalization
    ###################################################################

    def denormalize_file(self, node: models.Node, ptree: PTree) -> dict:
        """Given a cases tree and a file node, create the file json document."""
        # Add file metadata fields from indexd
        node = self.add_file_metadata_from_indexd(node)

        # Create a copy to avoid mutation of passed argument
        ptree = self.copy_tree(ptree, {})

        # Create base file doc
        cases = list(ptree.keys())
        case_id = cases[0].node_id if cases else None
        doc = self._get_base_doc(node)

        # Add file fields
        self.add_node_type(node, doc)
        self.add_file_neighbors(node, doc)
        self.add_data_category(node, doc)
        self.add_related_files(node, doc)
        self.add_index_files(node, doc)
        self.add_archives(node, doc)
        doc["cases"] = []
        relevant = self.add_cases(node, ptree, doc)
        self.add_file_associated_entities(node, doc)
        self.add_annotations(relevant, doc)
        self.add_acl(node, doc)
        self.add_file_data_format(node, doc)

        return doc

    def has_allowed_gencode_version(
        self, node: models.Node, gencode_version: Optional[str]
    ) -> bool:
        # submittable nodes should always be included
        if node._dictionary.get("submittable", False):
            return True

        return gencode_version in self.allowed_gencode_versions

    def add_file_metadata_from_indexd(self, node: models.Node) -> models.Node:
        """Read file metadata from indexd and sets it to node."""
        if node.node_id in self.versioned_files:
            for key, value in self.versioned_files[node.node_id].items():
                setattr(node, key, value)
            return node

        if node.node_id in self.file_metadata:
            record = self.file_metadata[node.node_id]
        else:
            document = self.indexd.get(node.node_id)

            if not document:
                if node.sysan.get("to_delete"):
                    self.file_metadata[node.node_id] = {"error": "to_delete file"}
                else:
                    self.warning(
                        f"No indexd data found for {node}, ignoring",
                        f"node_type: {node.label} node_id: {node.node_id}",
                        tags=[f"node:{node.label}"],
                    )
                    self.file_metadata[node.node_id] = {"error": "no indexd record"}
                return node

            gencode_version = _get_gencode_version(document)
            if not self.has_allowed_gencode_version(node, gencode_version):
                if gencode_version:
                    self.file_metadata[node.node_id] = ENTRY_FOR_WRONG_GENCODE
                    return node
                else:
                    self.warning(
                        title="indexd data with no gencode_version found, ignoring",
                        text=f"node_type: {node.label} node_id: {node.node_id}",
                        tags=[f"node:{node.label}"],
                    )
                    self.file_metadata[node.node_id] = FILE_MISSING_GENCODE
                    return node

            # Cache indexd record
            record = self.file_metadata.setdefault(node.node_id, document.to_json())

        # for to_delete nodes and nodes with wrong gencode_version
        if "error" in record or "ignore" in record:
            return node

        # Set node file metadata attributes according to indexd record
        for key in DATA_FILE_INDEXD_FIELDS:
            # Try to pick basic value
            value = record.get(key)
            if value is None:
                value = record["metadata"].get(key)
            if key == "file_state":
                for s3_url in record["urls_metadata"].keys():
                    if record["urls_metadata"][s3_url].get("type") == INDEXD_URL_TYPE:
                        value = record["urls_metadata"][s3_url].get("state")

            # Special values
            if key == "file_size":
                value = record.get("size")
            elif key == "md5sum":
                value = record["hashes"].get("md5")
            # Set node attribute from indexd record
            setattr(node, key, value)

        return node

    def add_node_type(self, node: models.Node, doc: dict) -> None:
        doc["type"] = node.label

    def get_data_format(self, node: models.Node) -> Optional[str]:
        """Get data format of a file node.

        Return the ``data_format`` given a file node based on

        1. its properties (data_format or file_format)
        2. an edge to a DataFormat node

        """
        if "data_format" in node._props:
            format_ = node._props["data_format"]

        elif "file_format" in node._props:
            format_ = node._props["file_format"]

        else:
            # get data_format from edge to DataFormat
            formats = list(self.neighbors_labeled(node, "data_format"))

            # Get the first format
            if formats:
                format_ = formats.pop()._props["name"]
            else:
                format_ = None

            # If there are still formats in a list, record warning
            if formats:
                self.warning(
                    f"{node} has mulitple data_formats",
                    f"{node} has additional data_formats: {formats}",
                    tags=[f"file_id:{node.node_id}"],
                )

        return format_

    def prune_case(
        self, relevant_nodes: Set[models.Node], ptree: PTree, keys: Container[str]
    ) -> None:
        """Remove node (whose label in keys but is not in relavent_nodes) from ptree.

        Start with whole case tree and remove any nodes that did not
        contribute the creation of this file.

        .. note:: :param:`ptree` is edited **in place*

        Args:
            relevant_nodes: The ancestors that should not be pruned from the tree (most
                likely self.relevant_nodes[some_file])
            ptree: The canonical ptree dict tree containing a the descendents of a case.
            keys: Only prune a given node ``node`` if ``node.label`` in keys.
        """
        for node in list(ptree.keys()):
            if ptree[node]:
                self.prune_case(relevant_nodes, ptree[node], keys)
            if node.label in keys and node not in relevant_nodes:
                ptree.pop(node)

    def add_file_data_format(self, node: models.Node, doc: dict) -> None:
        """Add (or overwrite) the data format if found."""
        data_format = self.get_data_format(node)
        if data_format:
            doc["data_format"] = data_format

    def add_file_neighbors(self, node: models.Node, doc: dict) -> None:
        """Add specified neighbors to file doc[label].

        Given a file, walk to all of its neighbors specified by the schema
        and add them to the document.

        """
        auto_neighbors = [
            n
            for n in mappings.FILE_TREE["file"].keys()
            if n not in ["archive", "portion", "file"]
        ]
        for neighbor in set(self.neighbors_labeled(node, auto_neighbors)):
            corr, label = mappings.FILE_TREE["file"][neighbor.label]["corr"]  # type: ignore
            if neighbor.label in FLATTENED_OBJECTS:
                base = neighbor[FLATTENED_OBJECTS[neighbor.label]]
            else:
                base = self._get_base_doc(neighbor)

            # Annotation nodes need special denormalization, so use the
            # pre-denormalized copy if we have one.
            if neighbor.label == "annotation":
                denormalized_annotation = self.annotation_entities.get(node, {}).get(
                    neighbor.node_id
                )

                if denormalized_annotation:
                    base = denormalized_annotation
                else:
                    log.warning(
                        "Missing denormalized annotation %s for node %s",
                        base.get("annotation_id"),
                        node.node_id,
                    )

            if corr == mappings.ONE_TO_ONE:
                if label in doc:
                    self.warning(
                        f"Duplicate edge on {node.node_id}",
                        (
                            "File {} has more than one {}, this is unexpected.".format(
                                node, label
                            )
                        ),
                        tags=[f"file_id:{node.node_id}"],
                    )
                else:
                    doc[label] = base
            else:
                if label not in doc:
                    doc[label] = []
                doc[label].append(base)

    def is_index_file(self, node: models.Node) -> bool:
        """Given a node, return whether it is considered an 'index file'.

        :returns: bool

        """
        # Active index files
        if node._dictionary["category"] == "index_file":
            return True

        # Legacy index files
        elif node.label == "file":
            # Set file metadata fields
            node = self.add_file_metadata_from_indexd(node)

            for extension in INDEX_FILE_EXTENSIONS:
                if getattr(node, "file_name", "").endswith(extension):
                    return True

        return False

    def get_file_index_files(self, node: models.Node) -> Iterator[models.Node]:
        """Given a file, return any neighboring index files."""
        return (
            n
            for n in list(self.neighbors_labeled(node, "file"))
            if self.G[node][n].get("label") == "related_to" and self.is_index_file(n)
        )

    def add_index_files(self, node: models.Node, doc: dict) -> None:
        """Add neighboring index files to file doc["index_files"].

        Given a file, walk to any neighboring index files and add
        them to the index_files section of the document.

        """
        index_file_docs = []
        index_files = self.get_file_index_files(node)

        for index_file in index_files:
            index_file_doc = self._get_base_doc(index_file)
            index_file_doc["data_format"] = self.get_data_format(index_file)

            index_file_docs.append(index_file_doc)

        if index_file_docs:
            doc["index_files"] = index_file_docs

    def add_related_files(self, node: models.Node, doc: dict) -> None:
        """Add neighboring files to file doc["metadata_files"].

        Given a file, walk to any (non data-from) neighboring files and add
        them to the related_files section of the document.

        ..note::
            Index files, e.g. ``.bai`` files, are added by
            :func:`self.add_index_files`

        """
        rf_docs = []

        metadata_labels = (
            "analysis_metadata",
            "run_metadata",
            "experiment_metadata",
        )

        # Get related_files
        related_files = [
            n
            for n in list(self.neighbors_labeled(node, "file"))
            if self.G[node][n].get("label") == "related_to"
            and not self.is_index_file(n)
        ]

        related_files += list(self.neighbors_labeled(node, metadata_labels))

        for related_file in related_files:
            # Add file metadata fields from indexd
            related_file = self.add_file_metadata_from_indexd(related_file)

            rf_doc = self._get_base_doc(related_file, include_id=False)
            rf_doc["file_id"] = rf_doc.get("file_id") or related_file.node_id

            # Data types
            data_subtypes = self.neighbors_labeled(
                related_file,
                "data_subtype",
            )

            for dst in data_subtypes:
                # data_subtype is renamed data_type, viz.
                # https://jira.opensciencedatacloud.org/browse/PGDC-1472
                rf_doc["data_type"] = dst["name"]
                self.add_data_category(related_file, rf_doc)

            # Type
            if related_file._props.get("file_name", "").endswith(".sdrf.txt"):
                rf_doc["type"] = "magetab"
            else:
                rf_doc["type"] = None

            # Access
            self.add_file_access(related_file, rf_doc)

            rf_doc["data_format"] = self.get_data_format(related_file)

            rf_docs.append(rf_doc)

        # Legacy files have two different types of relationships to
        # file, one that is `member_of` (which goes into
        # file.archives) and one that is `related_to` (which goes
        # here).  For now, we don't do this for non-legacy files.
        if node.label == "file":
            for archive in set(self.neighbors_labeled(node, "archive")):
                if self.G[node][archive].get("label") != "member_of":
                    name = "{}.{}.0.tar.gz".format(
                        archive["submitter_id"], archive["revision"]
                    )
                    rf_docs.append(
                        {
                            "file_id": archive.node_id,
                            "file_name": name,
                            "type": "magetab",
                            "access": "open",
                        }
                    )

        if rf_docs:
            # related_files is renamed metadata_files,
            # viz. https://jira.opensciencedatacloud.org/browse/PGDC-1838
            doc["metadata_files"] = rf_docs

    def add_archives(self, node: models.Node, doc: dict) -> None:
        """Add attached archive to file doc["archive"].

        For each archive attached to a given file node, multixplex on
        whether it is a containing or related archive and add it to the
        respective places in the doc.

        """
        for archive in set(self.neighbors_labeled(node, "archive")):
            is_skipped_legacy_edge = (
                node.label == "file"
                and self.G[node][archive].get("label") != "member_of"
            )

            if is_skipped_legacy_edge:
                continue

            if "archive" in doc:
                return self.warning(
                    f"Duplicate archives for {node}",
                    (f"File {node} has more than archive."),
                    tags=[f"file_id:{node.node_id}"],
                )

            archive_doc = self._get_base_doc(archive)

            # Archive is a file_doc for the legacy index, so it
            # will have `file_id` not `archive_id`.  If so, coerce
            # it back here.
            if "file_id" in archive_doc:
                archive_doc["archive_id"] = archive_doc.pop("file_id")

            doc["archive"] = archive_doc

    def add_data_category(self, node: models.Node, doc: dict) -> None:
        """Add the data_subtype to the file document with child data_category."""
        data_categories = [
            data_category
            for data_category, files in self.data_categories.items()
            if node in files
        ]
        if data_categories:
            # data_type is renamed data_category, viz.
            # https://jira.opensciencedatacloud.org/browse/PGDC-1472
            doc["data_category"] = data_categories[0]

    def add_cases(
        self, node: models.Node, ptree: dict[models.Node, dict], doc: dict
    ) -> Collection[models.Node]:
        """Add cases to file doc['cases'].

        Given a file and a case tree, re-insert the case as a
        child of file with only the biospecimen entities that are
        direct ancestors of the file.

        """
        if not ptree:
            log.warning("No ptree (case tree) for %s", node)
            return ()

        if node not in self.relevant_nodes:
            log.warning("No relevant cases for %s", node)
            return ()

        relevant = self.relevant_nodes[node]
        prune_keys = ["sample", "portion", "analyte", "aliquot", "file"]

        self.prune_case(relevant, ptree, prune_keys)

        doc["cases"] = [
            self.walk_tree(path, ptree, mappings.CASE_TREE, cast(list[dict], []))[0]
            for path in ptree
        ]

        for case in doc["cases"]:
            self.patch_project(case["project"])
            self.reconstruct_biospecimen_paths(case)

        doc["cases"] = [self.reconstruct_diagnoses_paths(case) for case in doc["cases"]]

        return relevant

    def add_annotations(self, relevant: Iterable[models.Node], doc: dict) -> None:
        """Loop relevant, get all annotation docs and add them to doc["annotations"].

        Given a file node, aggregate all the annotations from a pruned
        case tree and insert them at the root level of the file
        document.

        """
        annotations = doc.pop("annotations", [])

        for relevant_node in relevant:
            ann_docs = self.annotation_entities.get(relevant_node, {})
            annotations.extend(ann_docs.values())

        if annotations:
            doc["annotations"] = annotations

    def add_acl(self, node: models.Node, doc: dict) -> None:
        """Add the protection status of a file to the file document."""
        self.add_file_access(node, doc)
        doc["acl"] = node.acl

    def add_file_access(self, node: models.Node, doc: dict) -> None:
        """Summarize file ACL and Add it to doc["access"].

        Summarizes whether the ACL implies that the file is either ``open``
        or ``controlled``

        """
        if node.acl == ["open"]:
            doc["access"] = "open"
        else:
            doc["access"] = "controlled"

    def get_file_associated_entities(self, node: models.Node) -> Iterable[models.Node]:
        """Return a list of entities that are 'associated' with a file."""
        return self.neighbors_labeled(node, POSSIBLE_ASSOCIATED_ENTITIES)

    def add_file_associated_entities(self, node: models.Node, doc: dict) -> None:
        self._cache_entity_cases()

        docs = []
        entities = self.get_file_associated_entities(node)

        for e in entities:
            if e not in self.entity_cases:
                # Skip, the cases is likely missing because it is omitted
                continue

            case = self.entity_cases[e]
            subdoc = {
                "entity_type": e.label,
                "entity_id": e.node_id,
                "case_id": case.node_id,
            }

            entity_submitter_id = e._props.get("submitter_id")
            if entity_submitter_id:
                subdoc["entity_submitter_id"] = entity_submitter_id

            docs.append(subdoc)

        if docs:
            doc["associated_entities"] = docs

    def upsert_file_into_dict(self, files: dict[str, dict], file_doc: dict) -> None:
        did = file_doc["file_id"]
        if did not in files:
            files[did] = file_doc
        else:
            # If file in dict already, merge cases
            existing_ids = {c["case_id"] for c in files[did]["cases"]}
            for case in file_doc["cases"]:
                case_id = case["case_id"]
                if case_id not in existing_ids:
                    files[did]["cases"] += file_doc["cases"]

    ###################################################################
    #                       Project summaries
    ###################################################################

    def denormalize_project(self, p: models.Node) -> dict:
        """Summarize a project."""
        self._cache_all()
        doc = self._get_base_doc(p)

        # Get programs
        program = next(self.neighbors_labeled(p, "program"))
        log.info(f"Program: {program}")
        doc["program"] = self._get_base_doc(program)

        # project_id <- program.name-project.code
        self.patch_project(doc)

        log.info("Finding cases")
        cases = list(self.neighbors_labeled(p, "case"))
        log.info(f"Got {len(cases)} cases")

        # Get files
        log.info("Getting files")
        files: set[models.Node] = set()
        case_files = {}
        for case in cases:
            case_files[case] = self.remove_bam_index_files(
                self.walk_paths(case, self.case_to_file_paths)
            )
            files = files.union(case_files[case])

        log.info(f"Got {len(files)} total files from {len(case_files)} cases")

        # filter files
        files = {f for f in files if not validators.is_node_hidden(f)}

        log.info(f"Got {len(files)} files from {len(case_files)} cases")

        # Get experimental strategies
        exp_strat_summaries = []
        for exp_strat in self.experimental_strategies.keys():
            log.info(f"exp_strat: {exp_strat}")
            exp_files = self.experimental_strategies[exp_strat] & files

            if not len(exp_files):
                continue

            case_count = len(
                {p for p, p_files in case_files.items() if len(exp_files & p_files)}
            )

            exp_strat_summaries.append(
                {
                    "case_count": case_count,
                    "experimental_strategy": exp_strat,
                    "file_count": len(exp_files),
                }
            )

        # Get data types
        data_category_summaries = []

        for data_category in self.data_categories.keys():
            log.info(f"data_category: {data_category}")
            dt_files = self.data_categories[data_category] & files

            if not len(dt_files):
                continue

            case_count = len(
                {p for p, p_files in case_files.items() if len(dt_files & p_files)}
            )

            data_category_summaries.append(
                {
                    "case_count": case_count,
                    # data_type is renamed data_category, viz.
                    # https://jira.opensciencedatacloud.org/browse/PGDC-1472
                    "data_category": data_category,
                    "file_count": len(dt_files),
                }
            )

        # Summarize diesease_type and primary_site
        disease_types = set()
        primary_sites = set()

        for case in cases:
            if case["disease_type"]:
                disease_types.add(case["disease_type"])
            if case["primary_site"]:
                primary_sites.add(case["primary_site"])

        doc["disease_type"] = list(disease_types)
        doc["primary_site"] = list(primary_sites)

        # Compile summary
        doc["summary"] = cast(
            dict,
            {
                "case_count": len(cases),
                "file_count": len(files),
                "file_size": sum(f["file_size"] or 0 for f in files),
            },
        )

        if exp_strat_summaries:
            doc["summary"]["experimental_strategies"] = exp_strat_summaries

        if data_category_summaries:
            # data_type is renamed data_category, viz.
            # https://jira.opensciencedatacloud.org/browse/PGDC-1472
            doc["summary"]["data_categories"] = data_category_summaries

        return doc

    ###################################################################
    #                     Topmost denorm functions
    ###################################################################

    def denormalize_cases(
        self, cases: Collection[models.Node] = ()
    ) -> tuple[list[dict], list[dict], list[dict]]:
        """Denormalize specified cases or all cases in graph.

        If cases is not specified, denormalize all cases in
        the graph.  If cases is specified, denormalize only those
        given.

        :returns:
            tuple containing (case docs, file docs, annotation docs)

        """
        self._cache_all()
        case_docs, ann_docs = [], {}
        file_docs: dict[str, dict] = {}
        if not cases:
            cases = self.cases
        pbar = self.pbar("Denormalizing cases ", len(cases))
        for n in cases:
            pa, fi, an = self.denormalize_case(n)
            case_docs.append(pa)
            # TODO: [DEV-957] refactor the logic for `an` as denormalize_case returns []
            for a in an:
                if a["annotation_id"] not in ann_docs:
                    ann_docs[a["annotation_id"]] = a
            for f in fi:
                self.upsert_file_into_dict(file_docs, f)
            pbar.update(pbar.value + 1)
        pbar.finish()
        return case_docs, list(file_docs.values()), list(ann_docs.values())

    def denormalize_projects(
        self, projects: Collection[models.Node] = ()
    ) -> list[dict]:
        """Denormalize specified projects or all projects in graph.

        If projects is not specified, denormalize all projects in
        the graph.  If projects is specified, denormalize only those
        given.

        """
        self._cache_all()
        if not projects:
            projects = self.projects
        project_docs = []
        pbar = self.pbar("Denormalizing projects ", len(projects))
        for project in projects:
            project_docs.append(self.denormalize_project(project))
            pbar.update(pbar.value + 1)
        pbar.finish()
        return project_docs

    def denormalize_annotation(self, node: models.Node) -> dict:
        """Denormalize a specific annotation.

        .. note: The project of an annotation will be injected during
        case denormalization.

        """
        ann_doc = self._get_base_doc(node)
        entities = list(self.G.neighbors(node))
        if len(entities) == 0:
            self.error(
                "Annotation has no entities",
                f"{node.node_id} has zero entity associated.",
                tags=[f"annotation_id:{node.node_id}"],
            )
            # There are no entities! We cannot proceed.
            ann_doc.update(
                dict(
                    entity_type=None,
                    entity_id=None,
                    entity_submitter_id=None,
                )
            )
            return ann_doc

        if len(entities) > 1:
            self.warning(
                "Annotation has multiple entities",
                f"{node.node_id} has more than one entity associated.",
                tags=[f"annotation_id:{node.node_id}"],
            )
            # There are too many entities! proceed with only the first
            # entity

        entity = entities[0]
        ann_doc["entity_type"] = entity.label
        ann_doc["entity_id"] = entity.node_id
        esid = entity._props.get("submitter_id")
        if esid:
            ann_doc["entity_submitter_id"] = esid

        with self.g.session_scope() as sxn, sxn.no_autoflush:
            annotation = self.g.nodes().get(node.node_id)

            case = more_itertools.first(
                (
                    e
                    for e in annotation.edges_out  # type: ignore
                    if e.label == "relates_to"
                ),
                default=None,
            )

            if case:
                ann_doc["case_id"] = case.dst_id

        return ann_doc

    def denormalize_annotations(
        self,
        annotations: Iterable[models.Node],
        projects: Mapping[str, dict] = types.MappingProxyType({}),
    ) -> list[dict]:
        g = self.g
        annotation_ids = [node.node_id for node in annotations]

        if not annotation_ids:
            return []

        # NOTE: This santiy check is required as the linter thinks that Edges could be None.
        assert models.Edge

        with g.session_scope(can_inherit=False) as sxn, sxn.no_autoflush:
            edges_q = g.edges().filter(models.Edge.src_id.in_(annotation_ids))
            entities = dict()
            ann_to_entity = dict()
            ann_to_case = dict()

            assert edges_q

            for edge in edges_q:
                # Can't query on label since it's a hybrid property
                if edge.label != "annotates":
                    continue

                annotation = edge.src
                entity = edge.dst
                case = dfs_to_parent(annotation)

                ann_to_entity[annotation.node_id] = entity.node_id
                entities[entity.node_id] = entity
                if case:
                    ann_to_case[annotation.node_id] = case

        docs = []

        for annotation in annotations:
            try:
                doc = self._get_base_doc(annotation)
                doc.update(
                    dict(  # extend with more info
                        entity_type=None,
                        entity_id=None,
                        entity_submitter_id=None,
                        project=None,
                        case_id=None,
                        case_submitter_id=None,
                    )
                )

                # Handle entity info
                entity_id = ann_to_entity[annotation.node_id]
                entity = entities[entity_id]
                doc["entity_id"] = entity.node_id
                doc["entity_type"] = entity.label
                doc["entity_submitter_id"] = entity.submitter_id

                # Handle project info
                project = projects.get(annotation.project_id)
                if project:
                    doc["project"] = {
                        key: val
                        for key, val in project.items()
                        if key not in ["summary"]
                    }

                # Handle case info
                case = ann_to_case.get(annotation.node_id)
                if case:
                    doc["case_id"] = case.node_id
                    doc["case_submitter_id"] = case.submitter_id

                docs.append(doc)

            except Exception as e:
                exception = "".join(
                    traceback.format_exception(type(e), e, e.__traceback__, limit=1)
                )

                self.error(
                    "denormalize_annotations",
                    f"Annotation: {annotation.node_id} encountered an exception:\n{exception}",
                )
                continue

        return docs

    def denormalize_all(self) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
        """Return an entire index worth of case, file, annotation, and project documents."""
        cases, files, _ = self.denormalize_cases()
        projects = self.denormalize_projects()

        project_lookup = {}
        for project in projects:
            try:
                project_id = project["project_id"]
                project_lookup[project_id] = project
            except KeyError:
                self.error(
                    "denormalize_all",
                    "Encountered missing project_id in denormalize_all: {}".format(
                        project
                    ),
                )

        self.annotations = self.annotations or ()
        annotations = self.denormalize_annotations(
            self.annotations, projects=project_lookup
        )

        # NOTE: This is new logic from the active builder.
        projects_map = {
            p["project_id"]: {
                "primary_site": p["primary_site"],
                "disease_type": p["disease_type"],
            }
            for p in projects
        }

        for case in cases:
            project_id = case["project"]["project_id"]
            case["project"]["primary_site"] = projects_map[project_id]["primary_site"]
            case["project"]["disease_type"] = projects_map[project_id]["disease_type"]

        return cases, files, annotations, projects

    ###################################################################
    #                         Graph functions
    ###################################################################

    def nodes_labeled(self, labels: Union[Iterable, str]) -> Iterator[models.Node]:
        """Return an iterator over the edges in the graph with label `label`.

        Args:
            labels: node label or node labels

        Returns:
            networkx node generator
        """
        """Return an iterator over the edges in the graph with label `label`."""

        if isinstance(labels, Iterable) and not isinstance(labels, str):
            labels = tuple(labels)
        else:
            labels = (labels,)

        for n, p in self.G.nodes(data=True):
            if n.label in labels:
                yield n

    def neighbors_labeled(
        self,
        node: models.Node,
        labels: Union[str, Iterable[str]],
        expected: Optional[int] = None,
    ) -> Iterator[models.Node]:
        """Get neighbors of node, with desired labels.

        For a given node, return an iterator with generates neighbors to
        that node that are in a list of labels.  `label` can be either a
        string or list of strings.

        Args:
            node: node whose neighbors to get.
            labels: labels of neighbors wanted.
            expected: number of neighbors expected.

        Returns:
            A generator of neighbors.
        """
        if isinstance(labels, Iterable) and not isinstance(labels, str):
            labels = tuple(labels)
        else:
            labels = (labels,)

        if node in self.popular_nodes:
            if labels not in self.popular_nodes[node]:
                neighbors = self._cache_popular_neighbor(
                    node, self.G.neighbors(node), labels
                )
            else:
                neighbors = self.popular_nodes[node][labels]
        else:
            temp = list(self.G.neighbors(node))
            if len(temp) > 200:
                neighbors = self._cache_popular_neighbor(node, temp, labels)
            else:
                neighbors = {n for n in temp if n.label in labels}

        count = 0
        for n in neighbors:
            count += 1
            yield n

        if expected is not None and count != expected:
            self.warning(
                f"{node}: unexpected no. of '{labels}' neighbors",
                f"{node}: {count} != {expected} (expected)",
                tags=[f"{node.label}:{node.node_id}"],
            )

    ###################################################################
    #                       Validation functions
    ###################################################################

    def validate_against_mapping(
        self, doc: Union[dict, list], mapping: Mapping[str, Any]
    ) -> None:
        """Validate keys in the document are in the mapping.

        Recursively verify that all keys in the document are in the
        provided Elasticsearch mapping

        """
        if isinstance(doc, dict):
            # Recurse through all keys in dictionary
            for doc_key in list(doc.keys()):
                if doc_key not in mapping["properties"]:
                    self.error(
                        "Key not in mapping",
                        "Key '{}' was not found in mapping keys {}".format(
                            doc_key, list(mapping["properties"].keys())
                        ),
                        tags=[f"key:{doc_key}"],
                    )
                    # Remove so there is not an error when populating index
                    doc.pop(doc_key, None)
                else:
                    self.validate_against_mapping(
                        doc[doc_key], mapping["properties"][doc_key]
                    )

        elif isinstance(doc, list):
            # Loop over all items in the list. Note that ES
            # mappings do not distinguish between lists of subdocs and
            # single subdocs.
            for list_entry in doc:
                self.validate_against_mapping(list_entry, mapping)

    def validate_case(self, node: models.Node, case: dict) -> None:
        # Check that file count = summary.file_count
        if len(case["files"]) != case["summary"]["file_count"]:
            self.error(
                "Inconsistent case file count",
                "{}: {} != {}".format(
                    node.node_id, len(case["files"]), case["summary"]["file_count"]
                ),
                tags=[f"case_id:{node.node_id}"],
            )

        # Check for keys that are in the doc but not in the mapping
        self.validate_against_mapping(case, mappings.get_case_mapping())

    ###################################################################
    #                       Caching functions
    ###################################################################

    @staticmethod
    def is_harmonized_file(node: models.Node) -> bool:
        return node.label == "file" and node._sysan.get("source", "").endswith(
            "_alignment"
        )

    def is_old_supplement_file(self, node: models.Node) -> bool:
        if node.label == "file":
            node = self.add_file_metadata_from_indexd(node)
            return any(
                p.match(node._props.get("file_name", "")) for p in SUPPLEMENT_PATTERNS
            )
        return False

    def is_file_indexed(self, node: models.Node) -> bool:
        """Return false if node is a file that is not supposed to be indexed."""
        # This function should test only file nodes
        if node.label not in self.file_labels:
            return True

        if node.node_id in self.versioned_files:
            return True

        # Add file metadata to the node
        node = self.add_file_metadata_from_indexd(node)

        # remove file node with wrong gencode_version
        # TODO: [DEV-957] should we also remove 1) to_delete nodes and 2) nodes w/o indexd records ?
        if "ignore" in self.file_metadata[node.node_id]:
            log.info(
                f"File not indexed: {node.node_id} - {self.file_metadata[node.node_id]['ignore']}"
            )
            return False

        # Remove files with no acl entries
        if len(node.acl) == 0:
            log.info("File not indexed (empty acl): %s", node)
            return False

        # Skip old versions of supplement xmls
        if self.is_old_supplement_file(node):
            log.info("File not indexed (deprecated supplement): %s", node)
            return False

        # Skip old representation of harmonized files
        if self.is_harmonized_file(node):
            log.info("File not indexed (deprecated harmonized file): %s", node)
            return False

        # Is file to_delete
        if node.system_annotations.get("to_delete"):
            return False

        return True

    def is_omitted_project_or_neighbor_case(self, node: models.Node) -> bool:
        """Return false if the node is a project that is not supposed to be indexed."""
        if node.label == "project":
            projects = [node]
        elif node.label == "case":
            projects = list(self.neighbors_labeled(node, "project", 1))
        else:
            return False

        project_codes = [project.code for project in projects]
        program_names = [
            program.name
            for project in projects
            for program in self.neighbors_labeled(project, "program", 1)
        ]

        # Check if project is not released (for non-AWG build only)
        if not self.build_awg:
            for project in projects:
                if project.released is not True:
                    log.info("Omitting %s, project %s not released", node, project)
                    return True

        # Check project and program against omitted_projects
        for program_name in program_names:
            for project_code in project_codes:
                if (program_name, project_code) in OMITTED_PROJECTS:
                    return True
                elif self.build_projects:
                    if (program_name, project_code) in self.build_projects:
                        return False
                    else:
                        return True

        return False

    def is_unindexed_case(self, node):
        return node.label == "case" and not list(
            self.neighbors_labeled(node, "project", 1)
        )

    def is_node_unindexed_by_property(self, node: models.Node) -> bool:
        """Check if node properties specified in self.unindexed_by_property.

        Returns True if node should be removed because its properties are
        specified in self.unindexed_by_property as an indication to
        remove it from the index.

        """
        filters = self.unindexed_by_property.get(node.label, [])

        for filter_ in filters:
            is_subset = not set(filter_.items()) - set(node._props.items())

            if is_subset:
                return True

        return False

    def is_node_public(self, node: models.Node) -> bool:
        """Return whether a node is public.

        A node is public if:
        1. it's a project and it's released
        2. it's a node with a 'state' that is a 'released' state
        3. it's not a project or it doesn't have a state defined on it

        When self.build_awg is set, the rules are different:
        1. project must be in self.build_projects
        2. it's a node with a 'state' that is a AWG state
        """
        # AWG mode
        if self.build_awg:
            awg_states = {"live", "submitted", "processed", "released"}

            if node.label == "project":
                return True
            # NOTE: this one is questionable
            elif "state" not in node.__pg_properties__:
                return True  # True or False?

            elif node.state in awg_states:
                return True

        # Regular esbuild
        else:
            released_states = {"live", "released"}

            if node.label == "project":
                return node.released is True

            elif "state" not in node.__pg_properties__:
                return True

            elif node.state in released_states and node.label != "annotation":
                return True
            elif node.node_id in self.versioned_files:
                return True

            if (
                node.label == "annotation"
                and node.state == "released"
                and node.status == "Approved"
            ):
                return True

        return False

    def cache_skipped_node(
        self, node: Union[models.Node, tuple[models.Node, str]], reason: str
    ) -> None:
        """Cache skipped node in self.skipped_nodes['{reason-for-skipping}']."""
        self.skipped_nodes[reason].append(str(node))

    def is_node_indexed(self, node: models.Node) -> bool:
        """Return false if the node is not supposed to be indexed."""
        # Is the node allowed to be displayed publicly
        if not self.is_node_public(node):
            self.cache_skipped_node((node, node._props.get("state")), "not-public")
            return False

        if self.is_unindexed_case(node):
            self.cache_skipped_node(node, "unindexed-case")
            return False

        # Check for non-indexed files
        if not self.is_file_indexed(node):
            self.cache_skipped_node(node, "unindexed-file")
            return False

        # Check for non-indexed files
        if self.is_node_unindexed_by_property(node):
            self.cache_skipped_node(node, "unindexed-by-property")
            return False

        # Check for omitted_projects
        if self.is_omitted_project_or_neighbor_case(node):
            self.cache_skipped_node(node, "omitted-project")
            return False

        return True

    @staticmethod
    def truncate_path(path: Sequence[str], label: str) -> Sequence[str]:
        """Truncate a path, so it starts from next value of the given label.

        Given a path (a list of node labels), "truncate" it from the left
        such that it starts with the given label, or return [], e.g.:

        truncate_path(["a", "b", "c"], "a") -> ["b", "c"]
        truncate_path(["c", "d"], "b") -> []

        Args:
            path: path to truncate
            label: label to truncate from

        Returns:
            truncated path
        """
        for i, currlabel in enumerate(path):
            if currlabel == label:
                return path[i + 1 :]
        return ()

    def get_suppressed_children(self, redacted: models.Node) -> Iterator[models.Node]:
        """Get the children of a redacted node."""
        if redacted.label == "case":
            paths = self.case_to_file_paths
        else:
            paths = (
                self.truncate_path(p, redacted.label) for p in self.case_to_file_paths
            )
            # filter empty paths
            paths = tuple(filter(None, paths))
        log.info("suppressing %s, which is redacted directly.", redacted)
        yield redacted

        log.info("Walking down towards file with paths %s", paths)
        extra = self.walk_paths(redacted, paths, whole=True)

        log.info(
            "Found %s other things to suppress by walking from %s", extra, redacted
        )
        yield from extra

    def get_redaction_annotations(self) -> Iterator[models.Node]:
        """Return an iterator of annotations that should cause redactions."""
        return (
            annotation
            for annotation in self.nodes_labeled("annotation")
            if annotation.classification == "Redaction"
            and annotation.status != "Rescinded"
            # Suppress entities with redaction annotation if
            # entity.annotation.category not in this list
            and annotation.category not in ("Subject withdrew consent",)  #
        )

    def suppressed_nodes(self) -> Iterator[models.Node]:
        """Find all nodes that need to be suppressed due to redactions."""
        for redaction in self.get_redaction_annotations():
            redacted_list = list(self.G.neighbors(redaction))

            if len(redacted_list) == 0:
                # If there is no entity, then we have to move on to
                # the next annotation
                self.error(
                    "Redaction annotation no entities",
                    f"Redaction {redaction} has zero entities associated.",
                    tags=[f"annotation:{redaction}"],
                )
                continue

            if len(redacted_list) > 1:
                # an annotation should only ever annotate one thing,
                # however, proceed to redact them all
                self.warning(
                    "Redaction annotation has multiple entities",
                    (
                        "{} has more than one entity associated. "
                        "For security reasons, removing all from index!"
                    ).format(redaction),
                    tags=[f"annotation:{redaction}"],
                )

            for redacted in redacted_list:
                yield from self.get_suppressed_children(redacted)

    def remove_unindexed_nodes_from_graph(self) -> None:
        """Remove unindexed nodes and suppressed nodes from cached networkx graph.

        Removes nodes from cached graph in self.G according to:
        - is_node_indexed(node)
        - suppressed_nodes()
        """
        log.info("Selecting entities to be removed from cache...")
        removed_nodes = tuple(
            node for node in self.G.nodes() if not self.is_node_indexed(node)
        )
        log.info(f"Removing {len(removed_nodes)} nodes from cache")
        self.G.remove_nodes_from(removed_nodes)
        log.info("Finding and removing suppressed nodes")
        suppressed = tuple(self.suppressed_nodes())
        log.info("Removing %s suppressed nodes", len(suppressed))
        self.G.remove_nodes_from(suppressed)

    def iter_database_edges(self) -> Iterator[models.Edge]:  # type: ignore
        """Return an iterable of edges to load from the database.

        Eagerly (with join) loads the source and destination of the edge.
        NOTE: All nodes that are not Project and expected to be picked up
        must have project_id field corresponding to project they are part of
        As of Jan 2018, this is not true for Legacy and old Active nodes

        NOTE: [AWG build mode] If self.build_awg is set, will return only edges
        that are connected to nodes that are part of awg_review == True projects
        """
        if (self.build_awg or self.selective_caching) and self.build_projects:
            # Load only node ids with relevant project_id's
            project_ids = ["-".join(p) for p in self.build_projects]
            log.info(f"Getting {project_ids} from database")

            relevant_node_ids = {
                nd.node_id for nd in self.g.nodes().prop_in("project_id", project_ids)  # type: ignore
            }

            # Add relevant Project nodes to relevant nodes set:
            projects = [p[1] for p in self.build_projects]
            relevant_projects = self.g.nodes(models.Project).prop_in("code", projects)  # type: ignore

            relevant_node_ids.update(p.node_id for p in relevant_projects)

            # Query only relevant edges
            query = lambda node_type: self.g.edges(node_type).src(relevant_node_ids)  # type: ignore

        else:
            # Query all edges
            query = lambda node_type: self.g.edges(node_type)

        return itertools.chain.from_iterable(
            query(subclass)
            .options(orm.joinedload(subclass.src))
            .options(orm.joinedload(subclass.dst))  # type: ignore
            .yield_per(int(1e5))
            for subclass in models.Edge.get_subclasses()  # type: ignore
        )

    def cache_database(self) -> None:
        """Cache database psqlgraph into memory.

        Load the database into memory and remember only edge labels that we
        will need to distinguish later.

        """
        with self.g.session_scope() as sxn, sxn.no_autoflush:
            pbar = self.pbar("Caching Database: ", self.g.edges().count())
            # Cache graph to self.G
            # NOTE: if build_awg or selective_caching are set, will only iterate
            #   over relevant edges
            for e in self.iter_database_edges():
                pbar.update(pbar.value + 1)
                triple = (e.src.label, e.label, e.dst.label)
                needs_differentiation = triple in DIFFERENTIATED_EDGES
                if triple == ("file", "data_from", "file"):
                    # for files that are "data_from" other files, the
                    # centers and aliquots of the source files count
                    # as neighbors of the dst files
                    for center in e.src.centers:
                        self.G.add_edge(e.dst, center)
                    for aliquot in e.src.aliquots:
                        self.G.add_edge(e.dst, aliquot)
                if e.label == "relates_to" and e.__dst_class__ == "Case":
                    pass
                elif needs_differentiation and e._props:
                    self.G.add_edge(e.src, e.dst, label=e.label, props=e._props)
                elif needs_differentiation and not e._props:
                    self.G.add_edge(e.src, e.dst, label=e.label)
                elif e._props:
                    self.G.add_edge(e.src, e.dst, props=e._props)
                else:
                    self.G.add_edge(e.src, e.dst)
            pbar.finish()

        # Prune graph
        log.info(f"Cached {self.G.number_of_nodes()} nodes")
        self.remove_unindexed_nodes_from_graph()

        # Aggressively cache relationships, nodes by type, traversals, etc.
        self._cache_all()

    def _cache_all(self) -> None:
        """Create key value maps to cache nodes by label, by path, etc."""
        self._cache_experimental_strategies()
        self._cache_data_categories()
        self._cache_file_properties()
        self._cache_annotations()
        self._cache_relevant_nodes()
        self._cache_entity_cases()
        self._cache_cases()
        self._cache_projects()

    def _cache_projects(self) -> None:
        """Cache a list of all Project nodes."""
        if not self.projects:
            log.info("Caching projects...")
            self.projects = list(self.nodes_labeled("project"))

    def _cache_cases(self) -> None:
        """Cache a list of all Case nodes."""
        if not self.cases:
            log.info("Caching cases...")
            self.cases = tuple(self.nodes_labeled("case"))

    def _cache_entity_cases(self) -> None:
        """Cache the related Case nodes for each file."""
        if self.entity_cases:
            return

        entities = list(self.nodes_labeled(POSSIBLE_ASSOCIATED_ENTITIES))
        pbar = self.pbar("Caching entity cases: ", len(entities))
        self.entity_cases = {}

        for e in entities:
            if e.label == "case":
                # if the associated entity is a case, it's case is
                # just itself. this is kind of sketchy but w/e
                self.entity_cases[e] = e
                continue

            paths = set()
            for path in self.file_to_case_paths:
                truncated = self.truncate_path(path, e.label)
                if truncated:
                    paths.add(tuple(truncated))

            cases = self.walk_paths(e, paths)

            if len(cases) > 1:
                self.warning(
                    "Entity associated with > 1 case",
                    f"{e}: Found {len(cases)} cases",
                    tags=[f"entity:{e}"],
                )
                continue

            if len(cases) != 0:
                self.entity_cases[e] = more_itertools.first(cases)

            pbar.update(pbar.value + 1)
        pbar.finish()

    def get_cls_file_to_case_paths(self, cls: models.Node) -> Iterable[Sequence[str]]:
        """Given a node, return the paths the lead monotonically up to case.

        Args:
            cls: psqlgraph node

        Returns:
            generator of paths from node to case
        """
        parent_labels = frozenset(
            link["dst_type"].label for link in cls._pg_links.values()
        )
        return (
            path
            for path in self.file_to_case_paths
            if path and path[0] in parent_labels
        )

    def _cache_relevant_nodes(self) -> None:
        """Cache all nodes on path from current node to related cases.

        The file documents will need to be pruned to only the nodes that
        are relevant to the file. Here we cache all the nodes
        encountered when traversing to all related cases.

        Returns:
            None
        """
        if self.relevant_nodes:
            return

        self.relevant_nodes = {}

        files = list(self.nodes_labeled(self.file_labels))
        pbar = self.pbar("Caching file paths: ", len(files))

        for f in files:
            paths = self.get_cls_file_to_case_paths(f)
            self.relevant_nodes[f] = self.walk_paths(f, paths, whole=True)
            pbar.update(pbar.value + 1)

        pbar.finish()

    def _cache_annotations(self) -> None:
        if not self.annotations:
            # cache what nodes are annotations
            self.annotations = tuple(self.nodes_labeled("annotation"))
        if self.annotation_entities:
            # we've already cached the related entities
            return
        if not self.annotations:
            # there aren't any entities to relate
            self.annotation_entities = {}
            log.warning("No annotations found in the cached database!")
            return
        pbar = self.pbar("Caching annotations: ", len(self.annotations))
        self.annotation_entities = {}
        for a in self.annotations:
            for n in self.G.neighbors(a):
                if n not in self.annotation_entities:
                    self.annotation_entities[n] = {}
                a_doc = self.denormalize_annotation(a)
                self.annotation_entities[n][a.node_id] = a_doc
            pbar.update(pbar.value + 1)
        pbar.finish()

    def _cache_popular_neighbor(
        self,
        node: models.Node,
        neighbors: Iterable[models.Node],
        labels: tuple[str, ...],
    ) -> Set[models.Node]:
        self.popular_nodes[node][labels] = frozenset(
            n for n in neighbors if n.label in labels
        )
        return self.popular_nodes[node][labels]

    def _cache_experimental_strategies(self) -> None:
        """Cache files classified in each experimental strategy.

        Looking up the files that are classified in each
        experimental_strategy is a common computation.  Here we cache
        this information for easy retrieval.

        """
        if self.experimental_strategies:
            return

        log.info("Caching experimental strategies")

        for exp_strat in self.nodes_labeled("experimental_strategy"):
            strategy = exp_strat._props["name"]
            self.experimental_strategies[strategy] |= set(
                self.walk_path(exp_strat, ["file"])
            )

    def _cache_data_categories(self) -> None:
        log.info("Caching data categories/types")

        if self.data_categories:
            return

        for data_category in self.nodes_labeled("data_type"):
            category = data_category._props["name"]
            self.data_categories[category] |= self.remove_bam_index_files(
                set(self.walk_path(data_category, ["data_subtype", "file"]))
            )

    def _cache_file_properties(self) -> None:
        """Cache file nodes by some properties.

        Cache file nodes by the following properties: experimental_strategy,
        data_type and data_category

        Returns:
            None
        """
        for file_ in self.nodes_labeled(self.file_labels):
            strategy = file_._props.get("experimental_strategy")
            if strategy:
                self.experimental_strategies[strategy].add(file_)

            category = file_._props.get("data_category")
            if category:
                self.data_categories[category].add(file_)


def get_namespaced_uuid(ns: str, seed: str) -> str:
    """Create a consistent UUID5 string using the provided args.

    Args:
        ns: namespace
        seed: seed value

    Returns:
        str: uuid5 string
    """
    namespace = get_uuid_namespace(ns)
    return str(uuid.uuid5(namespace, seed))


UUID_NAMESPACES: dict[str, uuid.UUID] = {}


def get_uuid_namespace(label: str) -> uuid.UUID:
    """Return a consistent uuid4 string for a given label.

    Args:
        label (str): a label for a namespace, for eg aliquots

    Returns:
        UUID: uuid4 string
    """
    if label in UUID_NAMESPACES:
        return UUID_NAMESPACES[label]

    namespace = hashlib.sha1(bytes(label, "utf-8"), usedforsecurity=False).hexdigest()
    namespace = namespace[:32]
    namespace_uuid = uuid.UUID(hex=namespace, version=4)

    return UUID_NAMESPACES.setdefault(label, namespace_uuid)
