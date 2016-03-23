# -*- coding: utf-8 -*-
"""esbuild.graph.legacy.mappings
----------------------------------

Defines the Elasticsearch mappings for the main GDC graph index.

.. _hierarchy-format:

    The hierarchies defined below will contain a tuple (CORR, name),
    where CORR is the expected correlation and ``name`` is what key to
    nest the child documents under

"""

from addict import Dict
from gdcdatamodel import models  # noqa

from ..common.mappings import (
    get_common_annotation_es_mapping,
    get_common_annotation_tree,
    get_common_case_es_mapping,
    get_common_case_tree,
    get_common_file_es_mapping,
    get_common_file_tree,
    get_common_project_es_mapping,
    get_common_project_tree,
)

annotation_tree = get_common_annotation_tree()
case_tree = get_common_case_tree()
file_tree = get_common_file_tree()
project_tree = get_common_project_tree()


def get_annotation_es_mapping():
    """Creates the annotation mapping for legacy annotations from the common
    annotation mapping

    :returns: Elasticsearch mapping ``dict``

    """
    annotation = Dict(get_common_annotation_es_mapping())

    return annotation.to_dict()


def get_case_es_mapping(include_file=True):
    """Creates the case mapping for legacy cases from the common
    case mapping

    :returns: Elasticsearch mapping ``dict``

    """
    case = Dict(get_common_case_es_mapping())

    # Add pop whatever file is present and add correct files
    case.properties.pop('file', None)
    if include_file:
        case.properties.files = get_file_es_mapping(True)
        case.properties.files.type = 'nested'

    return case.to_dict()


def get_file_es_mapping(include_case=True):
    """Creates the file mapping for legacy files from the common
    file mapping

    :returns: Elasticsearch mapping ``dict``

    """
    files = Dict(get_common_file_es_mapping())

    # Since file.cases was created with the common definition, replace
    # it with the legacy definition
    if include_case:
        files.properties.cases = get_case_es_mapping(False)
        files.properties.cases.type = 'nested'

    return files.to_dict()


def get_project_es_mapping():
    """Creates the project mapping for legacy projects from the common
    project mapping

    :returns: Elasticsearch mapping ``dict``

    """
    project = Dict(get_common_project_es_mapping())

    return project.to_dict()
