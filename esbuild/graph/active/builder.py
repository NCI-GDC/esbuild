"""esbuild.graph.active.builder.

Defines :class:`ActiveGraphIndexBuilder` for building the graph index
for Active projects.

Strategy to add analysis and file types:

- An attempt to balance abstraction by creating the traversals from a
known point to limit wandering through the graph.  Currently, the
subgraph that includes active data_file and analysis nodes is isolated
by removing read_group, so we create a readgroup subtree and append
all paths generated in the readgroup subtree to paths from aliquot to
case - jsm (2016-03-22)

- we don't need a special path for harmonized files because they get
tied to the relevant aliquots during cache_database

"""
from typing import List, Optional, Set

from cdislogging import get_logger
from gdcdatamodel.models import ReadGroup

from esbuild.graph.active.mappings import ActiveESMapper
from esbuild.graph.common.builder import GraphIndexBuilder

from ..common import validators

log = get_logger("graph_active_index", log_level="info")
FILTERED_FILE_STATUSES = frozenset(("ignore", "error"))


def reverse_and_skip_first_entry(path: List) -> List:
    """Return a path that.

    1. is reversed and
    2. has the first step (in reversed order) removed

    This was created to traverse paths in reverse order such that the
    first entry in the path is skipped because we are already visiting
    that node. Example: ``['a', 'b', 'c'] -> ['b', 'a']``

    """
    return path[-2::-1]


def list_product(roots: List, subtrees: List) -> List:
    """Append each subtree to each root.

    It's not quite a cartesian product, example::

        roots = [['a', 'b'], ['-', '#']]
        subtrees = [range(0, 2), range(2, 4), range(4, 8)]
        list(list_product(roots, subtrees))
        [['a', 'b', 0, 1],
         ['a', 'b', 2, 3],
         ['a', 'b', 4, 5, 6, 7],
         ['-', '#', 0, 1],
         ['-', '#', 2, 3],
         ['-', '#', 4, 5, 6, 7]]

    """
    return [root + subtree for root in roots for subtree in subtrees]


def subtree_paths_to_file(
    cls,
    paths: Optional[List[List[str]]] = None,
    visited: Optional[List[str]] = None,
    categories: Optional[Set[str]] = None,
    exclude_paths_through: Optional[set] = None,
) -> List[List[str]]:
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
    if categories is None:
        categories = {"data_file", "analysis"}

    if exclude_paths_through is None:
        exclude_paths_through = set()

    visited = visited if visited is not None else []
    paths = paths if paths is not None else []

    if cls._dictionary["category"] == "data_file":
        paths.append(visited)

    for backref in cls._pg_backrefs.values():
        child = backref["src_type"]

        should_recur = (
            child._dictionary["category"] in categories
            and child.label not in visited
            and child.label not in exclude_paths_through
        )

        if should_recur:
            subtree_paths_to_file(
                child,
                paths,
                visited=visited + [child.label],
                exclude_paths_through=exclude_paths_through,
            )

    return paths


class ActiveGraphIndexBuilder(GraphIndexBuilder):

    mapper = ActiveESMapper

    """
    Since the Active index has more complicated paths from case to
    file, this is an attempt not to hard code them.  See module doc.
    """

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
    #
    # See PGDC-2349 for details.
    exclude_paths_through = {
        "alignment_cocleaning_workflow",
    }

    # Filter nodes out if their properties are a superset of any of
    # the dictionaries listed here by label
    unindexed_by_property = {
        "annotation": [{"status": "Rescinded"}, {"classification": "Blocking Release"}],
    }

    case_to_aliquot = [
        ["sample", "aliquot"],
        ["sample", "analyte", "aliquot"],
        ["sample", "portion", "analyte", "aliquot"],
    ]

    # BREADCRUMB
    # Holy hell. Ok, the following lists are paths to where
    # the builder *will* walk (and ONLY will walk) to find
    # file nodes. If your path is not here, you will not
    # get picked up. Be sure to add any paths here to
    # get data_file nodes to show up. You'll need to create
    # a list below, then add it to the case_to_file_paths
    # - a very tired joe sislow (3/15/2018)

    readgroup_subtree = list_product(
        [[ReadGroup.label]],
        subtree_paths_to_file(ReadGroup, exclude_paths_through=exclude_paths_through),
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

    aliquot_to_copy_number_segment_paths = [
        [
            "submitted_tangent_copy_number",
            "copy_number_liftover_workflow",
            "copy_number_segment",
        ],
        [
            "submitted_genotyping_array",
            "somatic_copy_number_workflow",
            "copy_number_segment",
        ],
    ]

    aliquot_to_copy_number_estimate_paths = [
        [
            "submitted_tangent_copy_number",
            "copy_number_liftover_workflow",
            "copy_number_segment",
            "copy_number_variation_workflow",
            "copy_number_estimate",
        ],
        [
            "submitted_genotyping_array",
            "somatic_copy_number_workflow",
            "copy_number_estimate",
        ],
    ]

    aliquot_to_methylation_value_paths = [
        [
            "submitted_methylation_beta_value",
            "methylation_liftover_workflow",
            "methylation_beta_value",
        ],
        [
            "raw_methylation_array",
            "methylation_array_harmonization_workflow",
            "methylation_beta_value",
        ],
    ]

    # added for slide_image by joe, 3/18
    case_to_slide_image_path = [
        ["sample", "slide", "slide_image"],
        ["sample", "portion", "slide", "slide_image"],
    ]

    case_to_file_paths = [
        ["biospecimen_supplement"],
        ["clinical_supplement"],
        ["sample", "pathology_report"],
    ]

    case_to_copy_number_segment_paths = list_product(
        case_to_aliquot, aliquot_to_copy_number_segment_paths
    )

    case_to_copy_number_estimate_paths = list_product(
        case_to_aliquot, aliquot_to_copy_number_estimate_paths
    )

    case_to_protein_expression = [
        ["sample", "protein_expression"],
        ["sample", "portion", "protein_expression"],
    ]

    case_to_methylation_value_paths = list_product(
        case_to_aliquot, aliquot_to_methylation_value_paths
    )

    case_to_raw_methylation_array_paths = list_product(
        case_to_aliquot, [["raw_methylation_array"]]
    )

    case_to_masked_methylation_array_paths = list_product(
        case_to_aliquot,
        [
            [
                "raw_methylation_array",
                "methylation_array_harmonization_workflow",
                "masked_methylation_array",
            ]
        ],
    )

    case_to_genotyping_array_paths = list_product(
        case_to_aliquot, [["submitted_genotyping_array"]]
    )
    case_to_germline_variation_paths = list_product(
        case_to_genotyping_array_paths,
        [["germline_mutation_calling_workflow", "simple_germline_variation"]],
    )

    case_to_file_paths += list_product(case_to_aliquot, readgroup_subtree)
    case_to_file_paths += case_to_copy_number_segment_paths
    case_to_file_paths += case_to_copy_number_estimate_paths
    case_to_file_paths += case_to_methylation_value_paths
    case_to_file_paths += case_to_slide_image_path
    case_to_file_paths += case_to_protein_expression
    case_to_file_paths += case_to_raw_methylation_array_paths
    case_to_file_paths += case_to_masked_methylation_array_paths
    case_to_file_paths += case_to_genotyping_array_paths
    case_to_file_paths += case_to_germline_variation_paths

    file_labels = GraphIndexBuilder.node_labels_by_category(
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

    # Pre-calculate the paths to read_group from each type of file
    file_to_read_group_paths = {}
    for path in readgroup_subtree:
        file_to_read_group_paths.setdefault(path[-1], []).append(path[-2::-1])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

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
        metadata_doc = {}

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
        paths = self.file_to_read_group_paths.get(node.label, [])
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

    def get_file_associated_entities(self, node):
        """Return a list of entities that are 'associated' with a file."""
        entities = super().get_file_associated_entities(node)

        # Add entities via read_group
        entities += [
            entity
            for rg in self.get_file_read_groups(node)
            for entity in self.neighbors_labeled(rg, self.possible_associated_entites)
        ]

        # Add entities with one step through a data_file
        entities += [
            entity
            for parent in self.get_parent_with_category(node, "data_file")
            for entity in self.neighbors_labeled(
                parent, self.possible_associated_entites
            )
        ]

        # Copy number paths
        cnv_paths = [
            reverse_and_skip_first_entry(path)
            for path in list_product(
                [["aliquot"]], self.aliquot_to_copy_number_segment_paths
            )
        ]

        # GISTIC paths
        gistic_paths = [
            reverse_and_skip_first_entry(path)
            for path in list_product(
                [["aliquot"]], self.aliquot_to_copy_number_estimate_paths
            )
        ]

        # Methylation paths
        methylation_paths = [
            reverse_and_skip_first_entry(path)
            for path in list_product(
                [["aliquot"]], self.aliquot_to_methylation_value_paths
            )
        ]

        # Special case paths to be traversed to possible associated entities
        custom_paths = cnv_paths + gistic_paths + methylation_paths

        entities += [entity for entity in self.walk_paths(node, custom_paths)]

        return list(set(entities))
