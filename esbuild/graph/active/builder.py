"""esbuild.graph.active.builder.

Defines :class:`ActiveGraphIndexBuilder` for building the graph index
for Active projects.

Strategy to add analysis and file types:

- An attempt to balance abstraction by creating the traversals from a
known point to limit wandering through the graph.  Currently, the
subgraph that includes active data_file and analysis nodes is isolated
by removing read_group, so we create a read group subtree and append
all paths generated in the read group subtree to paths from aliquot to
case - jsm (2016-03-22)

- we don't need a special path for harmonized files because they get
tied to the relevant aliquots during cache_database

"""

import itertools
import logging
from collections.abc import (
    Collection,
    Container,
    Iterable,
    Iterator,
    Mapping,
    Sequence,
    Set,
)
from typing import Any, Optional

import more_itertools
import psqlgraph
from gdcdatamodel2 import models
from indexclient import client

from esbuild.graph.common import builder, validators

log = logging.getLogger(__name__)
FILTERED_FILE_STATUSES = frozenset(("ignore", "error"))


def _path_product(
    roots: Iterable[Iterable[str]], subtrees: Iterable[Iterable[str]]
) -> Iterable[Sequence[str]]:
    """Append each subtree to each root.

    It's not quite a cartesian product, example::

        roots = [['a', 'b'], ['-', '#']]
        subtrees = [range(0, 2), range(2, 4), range(4, 8)]
        _path_product(roots, subtrees) ->
        (
            ('a', 'b', 0, 1),
            ('a', 'b', 2, 3),
            ('a', 'b', 4, 5, 6, 7),
            ('-', '#', 0, 1),
            ('-', '#', 2, 3),
            ('-', '#', 4, 5, 6, 7)
        )

    """
    return tuple((*p0, *p1) for p0 in roots for p1 in subtrees)


def _subtree_paths_to_file(
    cls: type[models.Node],
    visited: tuple[str, ...] = (),
    categories: Container[str] = frozenset(("data_file", "analysis")),
    exclude_paths_through: Container[str] = frozenset(),
) -> Iterator[Sequence[str]]:
    """Find paths to file nodes in subtree.

    Recurse through all child nodes in categories :param:`categories`
    and return all paths from :param:`cls` to destination child file
    nodes.

    Args:
        cls: The originating node class
        paths: Paths to file nodes
        visited: visited child labels
        categories: The set of categories through which recursion is allowed
        exclude_paths_through: child labels to skip

    Returns:
        paths to file nodes
    """
    if cls._dictionary["category"] == "data_file":
        yield visited

    for backref in cls._pg_backrefs.values():
        child = backref["src_type"]

        should_recur = (
            child._dictionary["category"] in categories
            and child.label not in visited
            and child.label not in exclude_paths_through
        )

        if should_recur:
            yield from _subtree_paths_to_file(
                child,
                visited=(*visited, child.label),
                exclude_paths_through=exclude_paths_through,
            )


def _get_case_to_file_paths() -> Iterable[Sequence[str]]:
    """Build all paths from case to files.

    Since the Active index has more complicated paths from case to file, this is an
    attempt not to hard code them. This process, with the exception of files related to
    read groups, builds the paths manually.

    TODO: DEV-2768: Currently this is done completely manually. However, we can and prob
        should build these paths using the same logic we currently use for read groups
        but start at the case node and walk all possible paths to our set of desired
        file types. We should create a whitelist of files which should be included in
        the build (preferably configurable) which will insure only the intended files
        are release. This will help us from accidentally forgetting a path or missing a
        path that is later introduced to the graph, but still be able to control which
        files types are released.

    Returns:
        A collection of string sequences which each represent a path (label to label;
        node to node) starting with the expected child of a case node and traversing to
        the file node label.
    """
    case_to_aliquot = (
        ("sample", "aliquot"),
        ("sample", "analyte", "aliquot"),
        ("sample", "portion", "analyte", "aliquot"),
    )

    # BREADCRUMB
    # Holy hell. Ok, the following lists are paths to where
    # the builder *will* walk (and ONLY will walk) to find
    # file nodes. If your path is not here, you will not
    # get picked up. Be sure to add any paths here to
    # get data_file nodes to show up. You'll need to create
    # a list below, then add it to the case_to_file_paths
    # - a very tired joe sislow (3/15/2018)

    readgroup_subtree = _path_product(
        ((models.ReadGroup.label,),),
        _subtree_paths_to_file(
            models.ReadGroup,
            # Skip any paths that traverse through nodes in
            # ``exclude_paths_through``.
            #
            # In the index, AlignedReads were associated with two aliquots
            # because they go through the Alignment Cocleaning
            # Workflow. However, they should have edges directly back to a
            # single SubmittedAlignedReads that goes back to a single
            # aliquot. They should only be associated with this aliquot.
            #
            # The impact is that the user can not filter properly on the
            # sample types, e.g. tumor versus normal as it returns all of the
            # AlignedReads.
            #
            # The solution applied here is to simply remove paths through
            # specific nodes and rely on the shortcut edges when traversing to
            # Read Groups.
            exclude_paths_through=("alignment_cocleaning_workflow",),
        ),
    )

    # Even more fun
    # It seems that the walk will walk differently
    # somehow. In some cases, it will walk to the
    # end of a path, but in others, it will stop or
    # ignore parents. The reason the following two are
    # overlapping is because it looks like extending
    # the path caused it to skip copy_number_segment
    # when walking to copy_number_estimate. We still
    # need to get to the bottom of how this logic
    # should be used.
    # - joe sislow (11/27/2018)

    aliquot_to_copy_number_segment_paths = (
        (
            "submitted_tangent_copy_number",
            "copy_number_liftover_workflow",
            "copy_number_segment",
        ),
        (
            "submitted_genotyping_array",
            "somatic_copy_number_workflow",
            "copy_number_segment",
        ),
    )

    aliquot_to_copy_number_estimate_paths = (
        (
            "submitted_tangent_copy_number",
            "copy_number_liftover_workflow",
            "copy_number_segment",
            "copy_number_variation_workflow",
            "copy_number_estimate",
        ),
        (
            "submitted_genotyping_array",
            "somatic_copy_number_workflow",
            "copy_number_estimate",
        ),
    )

    aliquot_to_methylation_value_paths = (
        (
            "submitted_methylation_beta_value",
            "methylation_liftover_workflow",
            "methylation_beta_value",
        ),
        (
            "raw_methylation_array",
            "methylation_array_harmonization_workflow",
            "methylation_beta_value",
        ),
    )

    # added for slide_image by joe, 3/18
    case_to_slide_image_path = (
        ("sample", "slide", "slide_image"),
        ("sample", "portion", "slide", "slide_image"),
    )

    case_to_copy_number_segment_paths = _path_product(
        case_to_aliquot, aliquot_to_copy_number_segment_paths
    )

    case_to_copy_number_estimate_paths = _path_product(
        case_to_aliquot, aliquot_to_copy_number_estimate_paths
    )

    case_to_protein_expression = (
        ("sample", "protein_expression"),
        ("sample", "portion", "protein_expression"),
    )

    case_to_methylation_value_paths = _path_product(
        case_to_aliquot, aliquot_to_methylation_value_paths
    )

    case_to_raw_methylation_array_paths = _path_product(
        case_to_aliquot, (("raw_methylation_array",),)
    )

    case_to_masked_methylation_array_paths = _path_product(
        case_to_aliquot,
        (
            (
                "raw_methylation_array",
                "methylation_array_harmonization_workflow",
                "masked_methylation_array",
            ),
        ),
    )

    case_to_genotyping_array_paths = _path_product(
        case_to_aliquot, (("submitted_genotyping_array",),)
    )
    case_to_germline_variation_paths = _path_product(
        case_to_genotyping_array_paths,
        (("germline_mutation_calling_workflow", "simple_germline_variation"),),
    )

    return tuple(
        itertools.chain(
            (
                ("biospecimen_supplement",),
                ("clinical_supplement",),
                ("sample", "pathology_report"),
            ),
            _path_product(case_to_aliquot, readgroup_subtree),
            case_to_copy_number_segment_paths,
            case_to_copy_number_estimate_paths,
            case_to_methylation_value_paths,
            case_to_slide_image_path,
            case_to_protein_expression,
            case_to_raw_methylation_array_paths,
            case_to_masked_methylation_array_paths,
            case_to_genotyping_array_paths,
            case_to_germline_variation_paths,
        )
    )


def _get_file_labels() -> Collection[str]:
    """Get the file labels for the build.

    This will return all nodes with a category of `data_file` & `index_file` except for
    the Archive and File node.

    Returns:
        The node labels associated with the file types to include in the build.
    """
    file_categories = frozenset(("data_file", "index_file"))
    excluded_labels = frozenset(("archive", "file"))

    return frozenset(
        n.label
        for n in models.Node.get_subclasses()
        if n._dictionary["category"] in file_categories
        and n.label not in excluded_labels
    )


def _get_paths_from_files(
    paths_to_files: Iterable[Sequence[str]],
    destination: str,
    included_files: Optional[Container[str]] = None,
) -> Mapping[str, Iterable[Sequence[str]]]:
    def restructure_path(path: Sequence[str]) -> Sequence[str]:
        restructured_path: Iterable[str] = reversed(path[:-1])
        restructured_path = more_itertools.takewhile_inclusive(
            lambda e: e != destination, restructured_path
        )

        return tuple(restructured_path)

    def is_path_included(path: Sequence[str]) -> bool:
        if included_files and path[-1] not in included_files:
            return False

        return destination in path

    paths_to_files = filter(is_path_included, paths_to_files)

    return more_itertools.map_reduce(
        paths_to_files, keyfunc=lambda p: p[-1], valuefunc=restructure_path
    )


class ActiveGraphIndexBuilder(builder.GraphIndexBuilder):
    """The builder for the current graph indices.

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
    ) -> None:
        super().__init__(
            psqlgraph_driver,
            indexd_client,
            index_prefix,
            build_projects,
            build_awg,
            selective_caching,
            versioned_files,
            allowed_gencode_versions,
            case_to_file_paths=_get_case_to_file_paths(),
            file_labels=_get_file_labels(),
            unindexed_by_property={
                "annotation": (
                    {"status": "Rescinded"},
                    {"classification": "Blocking Release"},
                ),
            },
        )

        self._file_to_aliquot_paths = _get_paths_from_files(
            self.case_to_file_paths, destination=models.Aliquot.label
        )
        self._file_to_read_group_paths = _get_paths_from_files(
            self.case_to_file_paths, destination=models.ReadGroup.label
        )

    def get_case_files(self, node: models.Node) -> Collection[models.Node]:
        def file_filter(file) -> bool:
            metadata = self.file_metadata.get(file.node_id, {})

            return not FILTERED_FILE_STATUSES.intersection(metadata)

        unfiltered_files = super().get_case_files(node)
        return set(filter(file_filter, unfiltered_files))

    def denormalize_file(self, node: models.Node, ptree: builder.PTree) -> dict:
        doc = super().denormalize_file(node, ptree)

        self.add_file_analysis(node, doc)
        self.add_file_downstream_analyses(node, doc)
        return doc

    def get_file_index_files(self, node: models.Node) -> Iterator[models.Node]:
        """Given a file, return any neighboring index files."""
        return (
            n
            for n in self.get_child_with_category(node, "index_file")
            if self.is_index_file(n)
        )

    def get_parent_with_category(
        self, node: models.Node, category: str
    ) -> Iterator[models.Node]:
        """Return iterable of neighbors from outbound edges with category."""
        labels = (
            l["dst_type"].label
            for l in node._pg_links.values()
            if l["dst_type"]._dictionary["category"] == category
        )

        return self.neighbors_labeled(node, labels)

    def get_child_with_category(
        self, node: models.Node, category: str
    ) -> Iterator[models.Node]:
        """Return iterable of neighbors from inbound edges with category."""
        labels = (
            l["src_type"].label
            for l in node._pg_backrefs.values()
            if l["src_type"]._dictionary["category"] == category
        )

        return self.neighbors_labeled(node, labels)

    def add_file_analysis(self, node: models.Node, doc: dict) -> None:
        """Add the 'analysis' that produced the current file."""
        analyses = list(self.get_parent_with_category(node, "analysis"))

        if analyses:
            # Add the first analysis
            analysis = analyses.pop()
            analysis_doc = self._get_base_doc(analysis)
            read_groups = self.get_file_read_groups(node)
            self.add_analysis_input_files(analysis, analysis_doc)
            self.add_analysis_metadata(analysis, read_groups, analysis_doc)
            doc["analysis"] = analysis_doc

        # If there are remaining analysis, record a warning and skip
        if analyses:
            self.warning(
                f"Multiple analysis on {node}",
                "{} has multiple analyses {}, this is unexpected.".format(
                    node, analyses
                ),
                tags=[f"file_id:{node.node_id}"],
            )

    def add_file_downstream_analyses(self, node: models.Node, doc: dict) -> None:
        """Add the 'analysis' that produced the current file."""
        analyses = self.get_child_with_category(node, "analysis")

        for analysis in analyses:
            analysis_doc = self._get_base_doc(analysis)
            self.add_analysis_output_files(analysis, analysis_doc)
            doc.setdefault("downstream_analyses", []).append(analysis_doc)

    def add_analysis_input_files(self, node: models.Node, doc: dict) -> None:
        """For a given analysis node, add the input_files to the doc."""
        input_files = [
            f
            for f in self.get_parent_with_category(node, "data_file")
            if not validators.is_node_hidden(f)
        ]
        input_file_docs = [self.get_simple_file_doc(f) for f in input_files]

        if input_file_docs:
            doc.setdefault("input_files", []).extend(input_file_docs)

    def add_analysis_output_files(self, node: models.Node, doc: dict) -> None:
        """For a given analysis node, add the output_files to the doc."""
        output_files = [
            f
            for f in self.get_child_with_category(node, "data_file")
            if not validators.is_node_hidden(f)
        ]
        output_file_docs = [self.get_simple_file_doc(f) for f in output_files]

        if output_file_docs:
            doc.setdefault("output_files", []).extend(output_file_docs)

    def add_analysis_metadata(
        self, analysis: models.Node, read_groups: Iterable[models.Node], doc: dict
    ) -> None:
        """For a given analysis node, add the metadata to the doc."""
        metadata_doc: dict = {}

        # Specify which analysis nodes get which types of
        # `analysis.metadata` {'metadata type': set({'labels'})}
        if analysis.label in ("alignment_workflow", "alignment_cocleaning_workflow"):
            self.add_analysis_metadata_read_groups(read_groups, metadata_doc)

        if metadata_doc:
            doc["metadata"] = metadata_doc

    def add_analysis_metadata_read_groups(
        self, read_groups: Iterable[models.Node], doc: dict
    ) -> None:
        """For a given analysis node, add read_groups to the metadata subdoc."""
        read_group_docs = []

        for read_group in read_groups:
            read_group_doc = self._get_base_doc(read_group)

            read_group_qc_docs = self.get_read_group_qc_docs(read_group)
            if read_group_qc_docs:
                read_group_doc["read_group_qcs"] = read_group_qc_docs

            read_group_docs.append(read_group_doc)

        if read_group_docs:
            doc["read_groups"] = read_group_docs

    def get_read_group_qc_docs(self, read_group: models.Node) -> list[dict]:
        """Return a list of documents for Read Group QCs."""
        read_group_qc_docs = []
        rg_qcs = self.neighbors_labeled(read_group, "read_group_qc")
        for read_group_qc in rg_qcs:
            read_group_qc_docs.append(self._get_base_doc(read_group_qc))

        return read_group_qc_docs

    def get_file_read_groups(self, node: models.Node) -> Set[models.Node]:
        """Given a data_file node, traverse up the tree to read_groups.

        :returns: set of read_groups

        """
        paths = self._file_to_read_group_paths.get(node.label, ())
        return self.walk_paths(node, paths)

    def get_simple_file_doc(self, node: models.Node) -> dict:
        """Create a simple file doc for {input,output}_files."""
        doc = self._get_base_doc(node)

        self.add_data_category(node, doc)
        self.add_file_access(node, doc)

        doc["data_format"] = self.get_data_format(node)

        for dst in self.neighbors_labeled(node, "data_subtype"):
            doc["data_type"] = dst["name"]

        return doc

    def _get_associated_entities_via_read_group(
        self, node: models.Node
    ) -> Iterable[models.Node]:
        return itertools.chain.from_iterable(
            self.neighbors_labeled(rg, builder.POSSIBLE_ASSOCIATED_ENTITIES)
            for rg in self.get_file_read_groups(node)
        )

    def _get_associated_entities_via_data_files(
        self, node: models.Node
    ) -> Iterable[models.Node]:
        return itertools.chain.from_iterable(
            self.neighbors_labeled(parent, builder.POSSIBLE_ASSOCIATED_ENTITIES)
            for parent in self.get_parent_with_category(node, "data_file")
        )

    def get_file_associated_entities(self, node: models.Node) -> Iterable[models.Node]:
        """Return all entities that are 'associated' with a file."""
        custom_paths = self._file_to_aliquot_paths.get(node.label, ())
        entities = super().get_file_associated_entities(node)
        entities = itertools.chain(
            entities, self._get_associated_entities_via_read_group(node)
        )
        entities = itertools.chain(
            entities, self._get_associated_entities_via_data_files(node)
        )
        entities = itertools.chain(entities, self.walk_paths(node, custom_paths))

        return frozenset(entities)
