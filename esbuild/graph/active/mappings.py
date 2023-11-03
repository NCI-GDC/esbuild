"""esbuild.graph.active.mappings.

Defines the Elasticsearch mappings for the main GDC graph index.

.. _hierarchy-format:

    The hierarchies defined below will contain a tuple (CORR, name),
    where CORR is the expected correlation and ``name`` is what key to
    nest the child documents under

"""

from copy import deepcopy
from typing import Any

from addict import Dict
from normalizer import load_blacklist, load_normalizer, normalize

from esbuild.graph.common.mappings import STRING, ESMapper

CLINICAL_NORMALIZER_KEYWORD = {"type": "keyword", "normalizer": "clinical_normalizer"}


class ActiveESMapper(ESMapper):
    @staticmethod
    def get_blacklist():
        blacklist = load_blacklist()
        blacklist.extend(["case_submitter_id", "entity_submitter_id"])

        return blacklist

    @staticmethod
    def apply_normalizer(mapping):
        blacklist = ActiveESMapper.get_blacklist()
        normalizer, _ = load_normalizer()

        return Dict(normalize(mapping, normalizer, blacklist))

    @staticmethod
    def multifield(name):
        doc = Dict()
        doc.type = "keyword"
        return Dict({name: doc})

    @staticmethod
    def index_settings():
        settings = super(ActiveESMapper, ActiveESMapper).index_settings()

        # Load default normalizer
        # FIXME: add support for different normalizers if needed in the future
        _, definition = load_normalizer()

        settings["settings"]["analysis"] = {
            "normalizer": definition,
            "filter": {
                "edge_ngram": {
                    "min_gram": "1",
                    "side": "front",
                    "type": "edge_ngram",
                    "max_gram": "20",
                }
            },
            "analyzer": {
                "autocomplete_prefix": {
                    "tokenizer": "keyword",
                    "filter": ["lowercase", "edge_ngram"],
                },
                "autocomplete_analyzed": {
                    "tokenizer": "standard",
                    "filter": ["lowercase", "edge_ngram"],
                },
                "lowercase_keyword": {
                    "tokenizer": "keyword",
                    "filter": ["lowercase"],
                },
            },
        }
        return settings

    @staticmethod
    def update_no_overwrite(original, new):
        for key, value in new.items():
            if key not in original:
                original[key] = value

    @classmethod
    def get_file_es_mapping(cls, include_case=True, is_root=True):
        files = Dict(
            super(ActiveESMapper, ActiveESMapper).get_file_es_mapping(
                include_case, is_root
            )
        )

        file_base_props = cls.multifield("file_id")
        file_base_props.update(cls.get_properties_by_category("index_file"))
        file_base_props.update(cls.get_properties_by_category("data_file"))
        file_base_props.access = STRING
        file_base_props.wgs_coverage = CLINICAL_NORMALIZER_KEYWORD

        # Update file properties to allow props from all file types
        cls.update_no_overwrite(files.properties, file_base_props)

        index_files = files.properties.index_files
        cls.update_no_overwrite(index_files.properties, file_base_props)

        # Input/output files
        input_files = Dict()
        input_files.type = "nested"
        cls.update_no_overwrite(input_files.properties, file_base_props)
        input_files.properties.access = STRING
        input_files.properties.wgs_coverage = CLINICAL_NORMALIZER_KEYWORD
        output_files = Dict(deepcopy(input_files.to_dict()))

        # Analysis
        analysis = Dict()
        analysis.properties = cls.get_properties_by_category("analysis")
        analysis.properties.analysis_id = STRING
        analysis.properties.analysis_type = STRING
        analysis.properties.input_files = input_files

        # Metadata
        metadata = Dict()
        read_groups = cls.nested("read_group")
        read_groups.properties.read_group_qcs = cls.nested("read_group_qc")
        metadata.properties.read_groups = read_groups
        analysis.properties.metadata = metadata

        # Downstream analysis
        ds_analysis = Dict(type="nested")
        ds_analysis.properties = cls.get_properties_by_category("analysis")
        ds_analysis.properties.analysis_id = STRING
        ds_analysis.properties.analysis_type = STRING
        ds_analysis.properties.output_files = output_files

        files.properties.analysis = analysis
        files.properties.downstream_analyses = ds_analysis

        # Add autocomplete and copy_to fields
        if is_root:
            files = cls.add_file_autocomplete(files)

        return ActiveESMapper.apply_normalizer(deepcopy(files.to_dict()))

    @classmethod
    def get_case_es_mapping(cls, include_file=True, is_root=True):
        case = Dict(
            super(ActiveESMapper, ActiveESMapper).get_case_es_mapping(
                include_file, is_root
            )
        )

        case.properties.samples.properties.specimen_type = CLINICAL_NORMALIZER_KEYWORD

        # Add autocomplete and copy_to fields
        if is_root:
            case = cls.add_case_autocomplete(case)

        return ActiveESMapper.apply_normalizer(deepcopy(case.to_dict()))

    @classmethod
    def get_annotation_es_mapping(cls, include_file=True):
        annotation = Dict(
            super(ActiveESMapper, ActiveESMapper).get_annotation_es_mapping(
                include_file
            )
        )

        # Add autocomplete and copy_to fields
        annotation = cls.add_annotation_autocomplete(annotation)

        return ActiveESMapper.apply_normalizer(deepcopy(annotation.to_dict()))

    @classmethod
    def get_project_es_mapping(cls):
        project = Dict(super(ActiveESMapper, ActiveESMapper).get_project_es_mapping())

        # Add autocomplete and copy_to fields
        project = cls.add_project_autocomplete(project)

        return ActiveESMapper.apply_normalizer(deepcopy(project.to_dict()))


get_file_es_mapping = ActiveESMapper.get_file_es_mapping
get_case_es_mapping = ActiveESMapper.get_case_es_mapping
get_project_es_mapping = ActiveESMapper.get_project_es_mapping
get_annotation_es_mapping = ActiveESMapper.get_annotation_es_mapping
index_settings = ActiveESMapper.index_settings
