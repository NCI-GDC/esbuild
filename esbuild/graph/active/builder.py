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

import logging
from collections.abc import Iterable, Sequence
from typing import Any

import psqlgraph
from gdcdatamodel2 import models
from indexclient import client

from esbuild.graph.common import builder, path_tools, validators

log = logging.getLogger(__name__)
FILTERED_FILE_STATUSES = frozenset(("ignore", "error"))
FILE_NODES = frozenset(
    {
        models.AggregatedSomaticMutation,
        models.AlignedReads,
        models.AnnotatedSomaticMutation,
        models.BiospecimenSupplement,
        models.ClinicalSupplement,
        models.CopyNumberAuxiliaryFile,
        models.CopyNumberEstimate,
        models.CopyNumberSegment,
        models.GeneExpression,
        models.MaskedMethylationArray,
        models.MaskedSomaticMutation,
        models.MethylationBetaValue,
        models.MirnaExpression,
        models.PathologyReport,
        models.ProteinExpression,
        models.RawMethylationArray,
        models.SecondaryExpressionAnalysis,
        models.SimpleGermlineVariation,
        models.SimpleSomaticMutation,
        models.SlideImage,
        models.StructuralVariation,
        models.SubmittedAlignedReads,
        models.SubmittedExpressionArray,
        models.SubmittedGenomicProfile,
        models.SubmittedGenotypingArray,
        models.SubmittedUnalignedReads,
    }
)
EXCLUDED_FILE_PATHS = frozenset(
    {
        models.AlignmentCocleaningWorkflow,
        models.Archive,
        models.Diagnosis,
        models.File,
    }
)


class ActiveGraphIndexBuilder(builder.GraphIndexBuilder):
    """The builder for the current graph indices.

    Since the Active index has more complicated paths from case to
    file, this is an attempt not to hard code them.  See module doc.
    """

    # Filter nodes out if their properties are a superset of any of
    # the dictionaries listed here by label
    unindexed_by_property = {
        "annotation": [{"status": "Rescinded"}, {"classification": "Blocking Release"}],
    }

    file_labels = builder.GraphIndexBuilder.node_labels_by_category(
        [
            "data_file",
            "index_file",
        ]
    )

    # Do not create file docs for archives
    file_labels.remove("archive")

    # Do not include files that are of the general legacy File type
    file_labels.remove("file")

    # Specify which analysis nodes get which types of
    # `analysis.metadata` {'metadata type': set({'labels'})}
    analysis_metadata = {
        "read_groups": {
            "alignment_workflow",
            "alignment_cocleaning_workflow",
        },
    }

    def __init__(
        self,
        psqlgraph_driver: psqlgraph.PsqlGraphDriver,
        indexd_client: client.IndexClient,
        index_prefix: str = "",
        **kwargs: Any,
    ) -> None:
        case_to_file_paths = tuple(
            path_tools.find_paths(
                models.Case,
                destinations=FILE_NODES,
                excluded_paths=EXCLUDED_FILE_PATHS,
            )
        )

        super().__init__(
            psqlgraph_driver, indexd_client, index_prefix, case_to_file_paths, **kwargs
        )

        # Omit entities from these projects
        self.omitted_projects.add(("CCLE", "CCLE_V2"))
        self.omitted_projects.add(("CCLE", "ALL-P1"))
        self.omitted_projects.add(("CCLE", "ACC"))
        self.omitted_projects.add(("CCLE", "DLBC"))
        self.omitted_projects.add(("CCLE", "READ"))
        self.omitted_projects.add(("CCLE", "GBM"))
        self.omitted_projects.add(("CCLE", "THCA"))
        self.omitted_projects.add(("CCLE", "BLCA"))
        self.omitted_projects.add(("CCLE", "UCEC"))
        self.omitted_projects.add(("CCLE", "PCPG"))
        self.omitted_projects.add(("CCLE", "LCML"))
        self.omitted_projects.add(("CCLE", "CESC"))
        self.omitted_projects.add(("CCLE", "UCS"))
        self.omitted_projects.add(("CCLE", "THYM"))
        self.omitted_projects.add(("CCLE", "LIHC"))
        self.omitted_projects.add(("CCLE", "CHOL"))
        self.omitted_projects.add(("CCLE", "HNSC"))
        self.omitted_projects.add(("CCLE", "STAD"))
        self.omitted_projects.add(("CCLE", "SKCM"))
        self.omitted_projects.add(("CCLE", "COAD"))
        self.omitted_projects.add(("CCLE", "UVM"))
        self.omitted_projects.add(("CCLE", "PAAD"))
        self.omitted_projects.add(("CCLE", "TGCT"))
        self.omitted_projects.add(("CCLE", "LUSC"))
        self.omitted_projects.add(("CCLE", "CNTL"))
        self.omitted_projects.add(("CCLE", "MISC"))
        self.omitted_projects.add(("CCLE", "MESO"))
        self.omitted_projects.add(("CCLE", "FPPP"))
        self.omitted_projects.add(("CCLE", "OV"))
        self.omitted_projects.add(("CCLE", "ESCA"))
        self.omitted_projects.add(("CCLE", "LCLL"))
        self.omitted_projects.add(("CCLE", "MM"))
        self.omitted_projects.add(("CCLE", "SARC"))
        self.omitted_projects.add(("CCLE", "KIRP"))
        self.omitted_projects.add(("CCLE", "LGG"))
        self.omitted_projects.add(("CCLE", "LAML"))
        self.omitted_projects.add(("CCLE", "PRAD"))
        self.omitted_projects.add(("CCLE", "LUAD"))
        self.omitted_projects.add(("CCLE", "BRCA"))
        self.omitted_projects.add(("CCLE", "KIRC"))
        self.omitted_projects.add(("CCLE", "KICH"))

        self._file_to_read_group_paths = path_tools.get_entity_paths(
            (models.ReadGroup.label,), self.case_to_file_paths
        )
        """A mapping of file labels and the paths to their associated read group."""

    def denormalize_all(self):
        cases, files, annotations, projects = super().denormalize_all()

        # Copy `primary_site` and `disease_type` from projects to cases.project:
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

    def get_case_files(self, node):
        def file_filter(file) -> bool:
            metadata = self.file_metadata.get(file.node_id, {})

            return not FILTERED_FILE_STATUSES.intersection(metadata)

        unfiltered_files = super().get_case_files(node)
        return set(filter(file_filter, unfiltered_files))

    def denormalize_file(self, node, ptree):
        doc = super().denormalize_file(node, ptree)

        self.add_file_analysis(node, doc)
        self.add_file_downstream_analyses(node, doc)
        return doc

    def get_file_index_files(self, node):
        """Given a file, return any neighboring index files."""
        return [
            n
            for n in list(self.get_child_with_category(node, "index_file"))
            if self.is_index_file(n)
        ]

    def get_parent_with_category(self, node, category):
        """Return iterable of neighbors from outbound edges with category."""
        labels = [
            l["dst_type"].label
            for l in node._pg_links.values()
            if l["dst_type"]._dictionary["category"] == category
        ]

        return self.neighbors_labeled(node, labels)

    def get_child_with_category(self, node, category):
        """Return iterable of neighbors from inbound edges with category."""
        labels = [
            l["src_type"].label
            for l in node._pg_backrefs.values()
            if l["src_type"]._dictionary["category"] == category
        ]

        return self.neighbors_labeled(node, labels)

    def add_file_analysis(self, node, doc):
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

    def add_file_downstream_analyses(self, node, doc):
        """Add the 'analysis' that produced the current file."""
        analyses = list(self.get_child_with_category(node, "analysis"))

        for analysis in analyses:
            analysis_doc = self._get_base_doc(analysis)
            self.add_analysis_output_files(analysis, analysis_doc)
            doc.setdefault("downstream_analyses", []).append(analysis_doc)

    def add_analysis_input_files(self, node, doc):
        """For a given analysis node, add the input_files to the doc."""
        input_files = [
            f
            for f in self.get_parent_with_category(node, "data_file")
            if not validators.is_node_hidden(f)
        ]
        input_file_docs = [self.get_simple_file_doc(f) for f in input_files]

        if input_file_docs:
            doc.setdefault("input_files", []).extend(input_file_docs)

    def add_analysis_output_files(self, node, doc):
        """For a given analysis node, add the output_files to the doc."""
        output_files = [
            f
            for f in self.get_child_with_category(node, "data_file")
            if not validators.is_node_hidden(f)
        ]
        output_file_docs = [self.get_simple_file_doc(f) for f in output_files]

        if output_file_docs:
            doc.setdefault("output_files", []).extend(output_file_docs)

    def add_analysis_metadata(self, analysis, read_groups, doc):
        """For a given analysis node, add the metadata to the doc."""
        metadata_doc: dict = {}

        if analysis.label in self.analysis_metadata["read_groups"]:
            self.add_analysis_metadata_read_groups(read_groups, metadata_doc)

        if metadata_doc:
            doc["metadata"] = metadata_doc

    def add_analysis_metadata_read_groups(self, read_groups, doc):
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

    def get_read_group_qc_docs(self, read_group):
        """Return a list of documents for Read Group QCs."""
        read_group_qc_docs = []
        rg_qcs = self.neighbors_labeled(read_group, "read_group_qc")
        for read_group_qc in rg_qcs:
            read_group_qc_docs.append(self._get_base_doc(read_group_qc))

        return read_group_qc_docs

    def get_file_read_groups(self, node):
        """Given a data_file node, traverse up the tree to read_groups.

        :returns: set of read_groups

        """
        paths: Iterable[Sequence[str]] = self._file_to_read_group_paths.get(
            node.label, ()
        )
        return set(self.walk_paths(node, paths))

    def get_analysis_read_groups(self, node):
        """Given a analysis node, traverse up the tree to read_groups.

        :returns: set of read_groups

        """
        return {
            path
            for file_ in self.get_parent_with_category(node, "data_file")
            for path in self.get_file_read_groups(file_)
        }

    def get_simple_file_doc(self, node):
        """Create a simple file doc for {input,output}_files."""
        doc = self._get_base_doc(node)

        self.add_data_category(node, doc)
        self.add_file_access(node, doc)

        doc["data_format"] = self.get_data_format(node)

        for dst in self.neighbors_labeled(node, "data_subtype"):
            doc["data_type"] = dst["name"]

        return doc
