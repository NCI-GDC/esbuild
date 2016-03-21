# -*- coding: utf-8 -*-
"""esbuild.graph.mappings
----------------------------------

Defines the Elasticsearch mappings for the main GDC graph index.

.. _hierarchy-format:

    The hierarchies defined below will contain a tuple (CORR, name),
    where CORR is the expected correlation and ``name`` is what key to
    nest the child documents under

TODO: Update the traversals to be generative from datamodel links?
  - jsm (2016-03-17)

"""

from addict import Dict
from gdcdatamodel import models  # noqa
from psqlgraph import Node

# ======================================================================
# Correspondence values

# These values specify the multiplicity of the relationship from
# parent to child.
ONE_TO_ONE = '__one_to_one__'
ONE_TO_MANY = '__one_to_many__'

# ======================================================================
# File hierarchy see :ref:`hierarchy-format` above

file_tree = Dict()
file_tree.corr = (ONE_TO_MANY, 'files')
file_tree.annotation.corr = (ONE_TO_MANY, 'annotations')
file_tree.archive.corr = (ONE_TO_ONE, 'archive')
file_tree.center.corr = (ONE_TO_ONE, 'center')
file_tree.data_format.corr = (ONE_TO_ONE, 'data_format')
file_tree.data_subtype.corr = (ONE_TO_ONE, 'data_type')
file_tree.data_subtype.data_type.corr = (ONE_TO_ONE, 'data_category')
file_tree.experimental_strategy.corr = (ONE_TO_ONE, 'experimental_strategy')
file_tree.case.corr = (ONE_TO_MANY, 'cases')
file_tree.platform.corr = (ONE_TO_ONE, 'platform')
file_tree.tag.corr = (ONE_TO_MANY, 'tags')
file_tree.file.corr = (ONE_TO_MANY, 'metadata_files')

# ======================================================================
# File traversals

file_traversal = Dict()
file_traversal.center = [
    ('center'),
    ('aliquot', 'center')
]
file_traversal.case = [
    ('sample', 'case'),
    ('file', 'sample', 'case'),
    ('aliquot', 'sample', 'case'),
    ('file', 'aliquot', 'sample', 'case'),
    ('analyte', 'portion', 'sample', 'case'),
    ('file', 'analyte', 'portion', 'sample', 'case'),
    ('aliquot', 'analyte', 'portion', 'sample', 'case'),
    ('file', 'aliquot', 'analyte', 'portion', 'sample', 'case'),
]

# ======================================================================
# Case hierarchy see :ref:`hierarchy-format` above

case_tree = Dict()
case_tree.corr = (ONE_TO_MANY, 'cases')
case_tree.annotation.corr = (ONE_TO_MANY, 'annotations')
case_tree.project.corr = (ONE_TO_ONE, 'project')
case_tree.project.program.corr = (ONE_TO_ONE, 'program')
case_tree.file.corr = (ONE_TO_MANY, 'files')
case_tree.tissue_source_site.corr = (ONE_TO_ONE, 'tissue_source_site')

# Biospecimen subtree
case_tree.sample.corr = (ONE_TO_MANY, 'samples')
case_tree.sample.annotation.corr = (ONE_TO_MANY, 'annotations')
case_tree.sample.portion.corr = (ONE_TO_MANY, 'portions')
case_tree.sample.portion.analyte.corr = (ONE_TO_MANY, 'analytes')
case_tree.sample.portion.analyte.annotation.corr = (ONE_TO_MANY, 'annotations')
case_tree.sample.portion.analyte.aliquot.corr = (ONE_TO_MANY, 'aliquots')
case_tree.sample.portion.analyte.aliquot.annotation.corr = (ONE_TO_MANY, 'annotations')
case_tree.sample.portion.analyte.aliquot.center.corr = (ONE_TO_ONE, 'center')
case_tree.sample.portion.annotation.corr = (ONE_TO_MANY, 'annotations')
case_tree.sample.portion.center.corr = (ONE_TO_ONE, 'center')
case_tree.sample.portion.slide.corr = (ONE_TO_MANY, 'slides')
case_tree.sample.portion.slide.annotation.corr = (ONE_TO_MANY, 'annotations')

# Clinical subtree
case_tree.clinical.corr = (ONE_TO_ONE, 'clinical')
case_tree.demographic.corr = (ONE_TO_ONE, 'demographic')
case_tree.exposure.corr = (ONE_TO_MANY, 'exposures')
case_tree.diagnosis.corr = (ONE_TO_MANY, 'diagnoses')
case_tree.diagnosis.treatment.corr = (ONE_TO_MANY, 'treatments')
case_tree.family_history.corr = (ONE_TO_MANY, 'family_histories')

# For TARGET
case_tree.aliquot = case_tree.sample.portion.analyte.aliquot
case_tree.sample.aliquot = case_tree.sample.portion.analyte.aliquot

# ======================================================================
# Case traversal

case_traversal = Dict()
case_traversal.file = [
    ('sample', 'file'),
    ('sample', 'aliquot', 'file'),
    ('sample', 'portion', 'analyte', 'file'),
    ('sample', 'portion', 'analyte', 'aliquot', 'file'),
]

# ======================================================================
# Annotation hierarchy see :ref:`hierarchy-format` above

annotation_tree = Dict()
annotation_tree.corr = (ONE_TO_MANY, 'cases')
annotation_tree.project.corr = (ONE_TO_ONE, 'project')
annotation_tree.project.program.corr = (ONE_TO_ONE, 'program')
annotation_tree.case.corr = (ONE_TO_ONE, 'case')
annotation_tree.sample.corr = (ONE_TO_ONE, 'sample')
annotation_tree.portion.corr = (ONE_TO_ONE, 'portion')
annotation_tree.analyte.corr = (ONE_TO_ONE, 'analyte')
annotation_tree.aliquot.corr = (ONE_TO_ONE, 'aliquot')
annotation_tree.slide.corr = (ONE_TO_ONE, 'slide')
annotation_tree.file.corr = (ONE_TO_ONE, 'file')

# ======================================================================
# Annotation traversals see :ref:`hierarchy-format` above

annotation_traversal = Dict()
annotation_traversal.file = [
    ('sample', 'file'),
    ('sample', 'file', 'file'),
    ('analyte', 'file'),
    ('analyte', 'file', 'file'),
    ('case', 'file'),
    ('case', 'file', 'file'),
    ('sample', 'aliquot', 'file'),
    ('sample', 'aliquot', 'file', 'file'),
    ('sample', 'portion', 'analyte', 'file'),
    ('sample', 'portion', 'analyte', 'file', 'file'),
    ('sample', 'portion', 'analyte', 'aliquot', 'file'),
    ('sample', 'portion', 'analyte', 'aliquot', 'file', 'file'),
]

# ======================================================================
# Project hierarchy

project_tree = Dict()
project_tree.corr = (ONE_TO_ONE, 'project')
project_tree.program.corr = (ONE_TO_ONE, 'program')

# ======================================================================
# Types

STRING = {
    'index': 'not_analyzed',
    'type': 'string',
}

LONG = {
    'type': 'long',
}

INTEGER = {
    'type': 'integer',
}

# ======================================================================
# Denormalization configuration options

FLATTEN = [
    'tag',
    'platform',
    'data_format',
    'experimental_strategy',
]

TOP_LEVEL_IDS = [
    'sample',
    'portion',
    'analyte',
    'aliquot',
    'slide',
]

# ======================================================================
# Index settings

MULTIFIELDS = {
    'project': [
        'code',
        'disease_type',
        'name',
        'primary_site',
    ],
    'annotation': [
        'annotation_id',
        'entity_id',
    ],
    'files': [
        'file_id',
        'file_name',
    ],
    'case': [
        'case_id',
        'submitter_id',
    ],
}


def index_settings():
    return {
        "settings": {
            "analysis": {
                "analyzer": {
                    "id_search": {
                        "tokenizer": "whitespace",
                        "filter": ["lowercase"],
                        "type": "custom"
                    },
                    "id_index": {
                        "tokenizer": "whitespace",
                        "filter": [
                            "lowercase",
                            "edge_ngram"
                        ],
                        "type": "custom"
                    }
                },
                "filter": {
                    "edge_ngram": {
                        "side": "front",
                        "max_gram": 20,
                        "min_gram": 2,
                        "type": "edge_ngram"
                    }
                }
            }
        }
    }


# ======================================================================
# Utility functions

def _get_header(source):
    header = Dict()
    header.dynamic = 'strict'
    header._all.enabled = False
    header._source.compress = True
    header._source.excludes = ["__comment__"]
    header._id = {'path': '{}_id'.format(source)}
    return header


def _get_es_type(_type):
    if long in _type or int in _type:
        return 'long'
    elif float in _type:
        return 'double'
    else:
        return 'string'


def _munge_properties(source, nested=True):

    # Get properties from schema
    cls = Node.get_subclass(source)
    assert cls, 'No model for {}'.format(source)
    properties = cls.get_pg_properties()
    fields = properties.keys()

    # Add id to document
    id_name = '{}_id'.format(source)
    doc = Dict({id_name: STRING})

    # Add all properties to document
    for field in fields:
        _type = _get_es_type(properties[field] or [])
        # assign the type
        doc[field] = {'type': _type}
        if str(_type) == 'string':
            doc[field]['index'] = 'not_analyzed'
    return doc


def multifield(name):
    doc = Dict()
    doc.type = 'string'

    # Raw
    doc.fields.raw.index = 'not_analyzed'
    doc.fields.raw.store = 'yes'
    doc.fields.raw.type = 'string'

    # Analyzed
    doc.fields.analyzed.index = "analyzed"
    doc.fields.analyzed.index_analyzer = "id_index"
    doc.fields.analyzed.search_analyzer = "id_search"
    doc.fields.analyzed.type = "string"

    # Search
    doc.fields.search.index = 'analyzed'
    doc.fields.search.analyzer = 'id_search'
    doc.fields.search.type = 'string'
    return Dict({name: doc})


def _walk_tree(tree, mapping):
    for k, v in [(k, v) for k, v in tree.items() if k != 'corr']:
        corr, name = v['corr']
        if name not in mapping:
            mapping[name] = {'properties': {}}
        if k in FLATTEN:
            mapping[name] = STRING
        elif k == 'annotation':
            mapping.annotations = annotation_body()
            mapping.annotations.type = 'nested'
        else:
            nested = (corr == ONE_TO_MANY)
            mapping[name].properties.update(
                _munge_properties(k, nested))
            _walk_tree(tree[k], mapping[name]['properties'])
            if nested:
                mapping[name]['type'] = 'nested'
    return mapping


def flatten_data_type(root):
    """Compress nested data_type and sub_type into flat key/value

    ..note::
        data_type is renamed data_category, viz.
        https://jira.opensciencedatacloud.org/browse/PGDC-1472

    ..note::
        data_subtype is renamed data_type, viz.
        https://jira.opensciencedatacloud.org/browse/PGDC-1472

    """
    root.data_type = STRING

    # data_type is renamed data_category, viz.
    # https://jira.opensciencedatacloud.org/browse/PGDC-1472
    root.data_category = STRING


def patch_file_timestamps(doc):
    doc.properties.uploaded_datetime = LONG
    doc.properties.published_datetime = LONG
    return doc


def nested(source):
    return Dict(type='nested', properties=_munge_properties(source))


def add_multifields(doc, source):
    for key in MULTIFIELDS[source]:
        doc.properties.update(multifield(key))


def patch_project(doc):
    doc.pop('code')


# ======================================================================
# Mappings

def get_file_es_mapping(include_case=True):
    files = _get_header('file')
    files.properties = _walk_tree(file_tree, _munge_properties('file'))
    flatten_data_type(files.properties)

    # Specify the entity the file was derived from
    files.properties.associated_entities.type = 'nested'
    files.properties.associated_entities.properties.entity_type = STRING
    files.properties.associated_entities.properties.entity_id = STRING
    files.properties.associated_entities.properties.case_id = STRING
    files.properties.associated_entities.properties.entity_submitter_id = STRING

    # Patch file mutlifields
    add_multifields(files, 'files')

    # Related files
    metadata_files = patch_file_timestamps(nested('file'))
    metadata_files.properties.type = STRING
    #   data_type is renamed data_category, viz.
    #   https://jira.opensciencedatacloud.org/browse/PGDC-1472
    metadata_files.properties.data_category = STRING
    #   data_subtype is renamed data_type, viz.
    #   https://jira.opensciencedatacloud.org/browse/PGDC-1472
    metadata_files.properties.data_type = STRING
    metadata_files.properties.access = STRING
    files.properties.metadata_files = metadata_files

    # Index files
    index_files = patch_file_timestamps(nested('file'))
    index_files.properties.file_format = STRING
    files.properties.index_files = index_files

    # Temporary until datetimes are backported
    patch_file_timestamps(files)

    # File access
    files.properties.access = STRING
    files.properties.acl = STRING

    # Other file properties
    files.properties.origin = STRING

    # Case
    files.properties.pop('case', None)
    if include_case:
        files.properties.cases = get_case_es_mapping(False)
        files.properties.cases.type = 'nested'
    return files.to_dict()


def get_case_es_mapping(include_file=True):
    # case body
    case = _get_header('case')
    case.properties = _walk_tree(
        case_tree, _munge_properties('case'))
    case.properties.days_to_index = LONG

    # Patch project
    patch_project(case.properties.project.properties)

    # Patch case mutlifields
    add_multifields(case, 'case')

    # Metadata files
    case.properties.metadata_files = nested('file')
    #   data_type is renamed data_category, viz.
    #   https://jira.opensciencedatacloud.org/browse/PGDC-1472
    case.properties.metadata_files.properties.data_category = STRING
    #   data_subtype is renamed data_type, viz.
    #   https://jira.opensciencedatacloud.org/browse/PGDC-1472
    case.properties.metadata_files.properties.data_type = STRING
    case.properties.metadata_files.properties.acl = STRING

    # Add top level id aggregation
    for label in TOP_LEVEL_IDS:
        case.properties['{}_ids'.format(label)] = STRING
        case.properties['submitter_{}_ids'.format(label)] = STRING

    # Add pop whatever file is present and add correct files
    case.properties.pop('file', None)
    if include_file:
        case.properties.files = get_file_es_mapping(True)
        case.properties.files.type = 'nested'

    # Adjust file properties
    case.properties.files.properties.pop('associated_entities', None)
    case.properties.files.properties.pop('annotations', None)

    # Summary
    summary = case.properties.summary.properties
    summary.file_count = LONG
    summary.file_size = LONG

    # Summary experimental strategies
    summary.experimental_strategies.type = 'nested'
    summary.experimental_strategies.properties.experimental_strategy = STRING
    summary.experimental_strategies.properties.file_count = LONG

    # Summary data types.  data_type is renamed data_category, viz.
    # https://jira.opensciencedatacloud.org/browse/PGDC-1472
    summary.data_categories.type = 'nested'
    summary.data_categories.properties.data_category = STRING
    summary.data_categories.properties.file_count = LONG

    # Clinical
    clinical = case.properties.clinical.properties
    clinical.age_at_diagnosis = INTEGER
    clinical.days_to_death = INTEGER

    return case.to_dict()


def annotation_body(nested=True):
    annotation = Dict()
    annotation.properties = _munge_properties('annotation', nested)
    annotation.properties.case_id = STRING
    annotation.properties.case_submitter_id = STRING
    annotation.properties.entity_type = STRING
    annotation.properties.entity_id = STRING
    annotation.properties.entity_submitter_id = STRING
    annotation.properties.pop('item_id', None)
    return annotation


def get_annotation_es_mapping(include_file=True):
    annotation = _get_header('annotation')
    annotation.update(annotation_body(nested=False))

    # Patch annotation mutlifields
    add_multifields(annotation, 'annotation')

    # Add the project and program
    annotation.properties.update(Dict({
        'project': {'properties': _munge_properties('project')}}))
    annotation.properties.project.properties.program = {
        'properties': _munge_properties('program')}

    return annotation.to_dict()


def get_project_es_mapping():
    project = _get_header('project')
    project.properties = _walk_tree(project_tree, _munge_properties('project'))

    # Patch annotation mutlifields
    add_multifields(project, 'project')

    # Patch project
    patch_project(project.properties)
    project.properties.update(multifield('project_id'))

    # Summary
    summary = project.properties.summary.properties
    summary.file_count = LONG
    summary.file_size = LONG
    summary.case_count = LONG

    # Summary experimental strategies
    summary.experimental_strategies.type = 'nested'
    summary.experimental_strategies.properties.case_count = LONG
    summary.experimental_strategies.properties.experimental_strategy = STRING
    summary.experimental_strategies.properties.file_count = LONG

    # Summary data types.  data_type is renamed data_category, viz.
    # https://jira.opensciencedatacloud.org/browse/PGDC-1472
    summary.data_categories.type = 'nested'
    summary.data_categories.properties.case_count = LONG
    summary.data_categories.properties.data_category = STRING
    summary.data_categories.properties.file_count = LONG

    return project.to_dict()
