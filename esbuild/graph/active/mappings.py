# -*- coding: utf-8 -*-
"""esbuild.graph.active.mappings
----------------------------------

Defines the Elasticsearch mappings for the main GDC graph index.

.. _hierarchy-format:

    The hierarchies defined below will contain a tuple (CORR, name),
    where CORR is the expected correlation and ``name`` is what key to
    nest the child documents under

"""

from addict import Dict
from copy import deepcopy
from gdcdatamodel import models  # noqa
from psqlgraph import Node

from ..common.mappings import (
    ESMapper,
    LONG,
    STRING,
)


class ActiveESMapper(ESMapper):

    file_labels = [
        c.label for c in Node.get_subclasses()
        if c._dictionary['category'] in {'data_file', 'index_file'}
    ]

    @classmethod
    def get_file_es_mapping(cls, *args, **kwargs):
        files = Dict(super(ActiveESMapper, ActiveESMapper)
                     .get_file_es_mapping(*args, **kwargs))

        files.properties.update(cls.get_properties_by_category('data_file'))
        files.properties.update(cls.get_properties_by_category('index_file'))

        index_files = files.properties.index_files
        index_files.properties.update(cls.get_properties_by_category('data_file'))
        index_files.properties.update(cls.get_properties_by_category('index_file'))

        input_files = Dict()
        input_files.type = 'nested'
        input_files.properties.data_type = STRING
        input_files.properties.data_category = STRING
        input_files.properties.data_format = STRING
        input_files.properties.file_id = STRING
        input_files.properties.file_name = STRING
        input_files.properties.file_size = LONG

        output_files = Dict(deepcopy(input_files.to_dict()))

        # Analysis
        analysis = Dict()
        analysis.properties = cls.get_properties_by_category('analysis')
        analysis.properties.input_files = input_files

        # Metadata
        metadata = Dict()
        metadata.properties.read_groups = cls.nested('read_group')
        analysis.properties.metadata = metadata

        # Downstream analysis
        ds_analysis = Dict()
        ds_analysis.properties = cls.get_properties_by_category('analysis')
        ds_analysis.properties.output_files = output_files

        files.properties.analysis = analysis
        files.properties.downstream_analysis = ds_analysis

        return files.to_dict()

    @classmethod
    def get_case_es_mapping(cls, *args, **kwargs):
        case = Dict(super(ActiveESMapper, ActiveESMapper)
                    .get_case_es_mapping(*args, **kwargs))

        files = case.properties.files

        # This is unecessary for searching cases
        files.properties.analysis.properties.pop('metadata', None)

        return case.to_dict()


get_file_es_mapping = ActiveESMapper.get_file_es_mapping
get_case_es_mapping = ActiveESMapper.get_case_es_mapping
get_project_es_mapping = ActiveESMapper.get_project_es_mapping
get_annotation_es_mapping = ActiveESMapper.get_annotation_es_mapping
index_settings = ActiveESMapper.index_settings
