# -*- coding: utf-8 -*-
"""
esbuild.graph.common.mappings
----------------------------------

Common definitions for building GDC Elasticsearch mappings

"""

from addict import Dict
from gdcdictionary import gdcdictionary
from copy import deepcopy
from psqlgraph import Node

# These values specify the multiplicity of the relationship from
# parent to child.
ONE_TO_ONE = '__one_to_one__'
ONE_TO_MANY = '__one_to_many__'

DATA_FILE_CATEGORIES = [
    'data_file',
]

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


def get_es_type(_type):
    if long in _type or int in _type:
        return 'long'
    elif float in _type:
        return 'double'
    else:
        return 'string'


# ======================================================================
# Index settings

class ESMapper(object):

    # These are the types of data_file that will be treated as a file
    file_labels = ['file']

    top_level_ids = [
        'sample',
        'portion',
        'analyte',
        'aliquot',
        'slide',
    ]

    flatten = [
        'tag',
        'platform',
        'data_format',
        'experimental_strategy',
    ]

    multifields = {
        'project': [
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

    @staticmethod
    def get_file_tree():
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

        return file_tree

    @staticmethod
    def get_case_tree():
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
        case_tree.sample.aliquot.corr = (ONE_TO_MANY, 'aliquots')
        case_tree.sample.aliquot.annotation.corr = (ONE_TO_MANY, 'annotations')
        case_tree.sample.aliquot.analyte.annotation.corr = (ONE_TO_MANY, 'annotations')
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
        case_tree.demographic.corr = (ONE_TO_ONE, 'demographic')
        case_tree.exposure.corr = (ONE_TO_MANY, 'exposures')
        case_tree.diagnosis.corr = (ONE_TO_MANY, 'diagnoses')
        case_tree.diagnosis.treatment.corr = (ONE_TO_MANY, 'treatments')
        case_tree.family_history.corr = (ONE_TO_MANY, 'family_histories')

        return case_tree

    @staticmethod
    def get_annotation_tree():
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

        return annotation_tree

    @staticmethod
    def get_project_tree():
        project_tree = Dict()
        project_tree.corr = (ONE_TO_ONE, 'project')
        project_tree.program.corr = (ONE_TO_ONE, 'program')

        return project_tree

    # ======================================================================
    # Denormalization configuration options

    @staticmethod
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

    @classmethod
    def get_prop_description(cls, label, prop):
        """Look the description up from the ``term`` if it exists, else try
        the jsonschema property description, else return None

        """

        definition = gdcdictionary.schema[label]['properties'].get(prop)
        if not definition:
            return None

        term = definition.get('term', None)

        if not term or not isinstance(term, dict):
            return definition.get('description', None)
        else:
            return term.get('description', None)

    @classmethod
    def get_descriptions_from_tree(cls, tree, root_name, path=''):
        """Given a tree (file, case, etc) recurively aggregate the
        descriptions

        :returns:
            Flattened dict of descriptions with keys like
            ``diagnoses.submitter_id``

        """
        descriptions = {}

        for label in [key for key in tree if key != 'corr']:
            _, name = tree[label]['corr']

            # recur
            descriptions.update(cls.get_descriptions_from_tree(
                tree[label], root_name, path + '.' + name))

            # add current level
            descriptions.update({
                '{}{}.{}.{}'.format(root_name, path, name, prop):
                cls.get_prop_description(label, prop)
                for prop in Node.get_subclass(label).__pg_properties__
            })

        return descriptions

    @classmethod
    def get_descriptions(cls):
        """Get a description for properties of all defined node types

        """
        descriptions = {}
        descriptions.update(cls.get_descriptions_from_tree(
            cls.get_annotation_tree(), 'annotations'))
        descriptions.update(cls.get_descriptions_from_tree(
            cls.get_case_tree(), 'cases'))
        descriptions.update(cls.get_descriptions_from_tree(
            cls.get_file_tree(), 'files'))
        descriptions.update(cls.get_descriptions_from_tree(
            cls.get_project_tree(), 'projects'))

        descriptions.update({
            'files.file.{}'.format(prop):
            cls.get_prop_description('file', prop)
            for prop in Node.get_subclass('file').__pg_properties__})
        descriptions.update({
            'cases.case.{}'.format(prop):
            cls.get_prop_description('case', prop)
            for prop in Node.get_subclass('case').__pg_properties__})
        descriptions.update({
            'projects.project.{}'.format(prop):
            cls.get_prop_description('project', prop)
            for prop in Node.get_subclass('project').__pg_properties__})
        descriptions.update({
            'annotations.annotation.{}'.format(prop):
            cls.get_prop_description('annotation', prop)
            for prop in Node.get_subclass('file').__pg_properties__})

        return descriptions

    @classmethod
    def _get_header(cls, source):
        header = Dict()
        header.dynamic = 'strict'
        header._all.enabled = False
        header._source.compress = True
        header._source.excludes = ["__comment__"]
        header._id = {'path': '{}_id'.format(source)}
        header._meta.descriptions = cls.get_descriptions()
        return header

    @staticmethod
    def get_base_properties(source, include_id=True):
        # Get properties from schema
        cls = Node.get_subclass(source)
        assert cls, 'No model for {}'.format(source)
        properties = cls.get_pg_properties()
        fields = properties.keys()

        doc = Dict()

        if include_id:
            # Add id to document
            id_name = '{}_id'.format(source)
            doc[id_name] = STRING

        # Add all properties to document
        for field in fields:
            _type = get_es_type(properties[field] or [])
            # assign the type
            doc[field] = {'type': _type}
            if str(_type) == 'string':
                doc[field]['index'] = 'not_analyzed'

        if source != 'project':
            doc.pop('project_id', None)

        return doc

    @staticmethod
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

    @staticmethod
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

    @classmethod
    def nested(cls, source):
        return Dict(type='nested', properties=cls.get_base_properties(source))

    @classmethod
    def add_multifields(cls, doc, source):
        for key in cls.multifields[source]:
            doc.properties.update(cls.multifield(key))

    @staticmethod
    def patch_project(doc):
        doc.pop('code')

    @classmethod
    def _walk_tree(cls, tree, mapping):
        for k, v in [(k, v) for k, v in tree.items() if k != 'corr']:
            corr, name = v['corr']
            if name not in mapping:
                mapping[name] = {'properties': {}}
            if k in cls.flatten:
                mapping[name] = STRING
            elif k == 'annotation':
                mapping.annotations = cls.annotation_body()
                mapping.annotations.type = 'nested'
            else:
                nested = (corr == ONE_TO_MANY)
                mapping[name].properties.update(cls.get_base_properties(k))
                cls._walk_tree(tree[k], mapping[name]['properties'])
                if nested:
                    mapping[name]['type'] = 'nested'
        return mapping

    @classmethod
    def get_properties_by_category(cls, category):
        doc = Dict()
        classes = (
            c for c in Node.get_subclasses()
            if c._dictionary['category'] == category
        )

        for c in classes:
            doc.update(cls.get_base_properties(c.label, include_id=False))

        return doc

    # ======================================================================
    # Mappings

    @classmethod
    def get_file_es_mapping(cls, include_case=True):
        files = cls._get_header('file')

        # Let top level properties be a union over properties from all
        # node types that this mapper considers a file
        files.properties = Dict({
            key: value
            for node in Node.get_subclasses()
            if node.label in cls.file_labels
            for key, value in
            cls.get_base_properties(node.label, include_id=False).iteritems()
        })

        files.properties = cls._walk_tree(
            cls.get_file_tree(),
            files.properties
        )

        cls.flatten_data_type(files.properties)

        # Specify the type of file
        files.properties.type = STRING

        # Specify the entity the file was derived from
        files.properties.associated_entities.type = 'nested'
        files.properties.associated_entities.properties.entity_type = STRING
        files.properties.associated_entities.properties.entity_id = STRING
        files.properties.associated_entities.properties.case_id = STRING
        files.properties.associated_entities.properties.entity_submitter_id = STRING

        # Patch file mutlifields
        cls.add_multifields(files, 'files')

        # Related files
        metadata_files = cls.nested('file')
        metadata_files.properties.type = STRING
        #   data_type is renamed data_category, viz.
        #   https://jira.opensciencedatacloud.org/browse/PGDC-1472
        metadata_files.properties.data_category = STRING
        #   data_subtype is renamed data_type, viz.
        #   https://jira.opensciencedatacloud.org/browse/PGDC-1472
        metadata_files.properties.data_type = STRING
        metadata_files.properties.data_format = STRING
        metadata_files.properties.access = STRING
        files.properties.metadata_files = metadata_files

        # Index files
        index_files = cls.nested('file')
        index_files.properties.data_format = STRING
        files.properties.index_files = index_files

        # File access
        files.properties.access = STRING
        files.properties.acl = STRING

        # Other file properties
        files.properties.origin = STRING

        # Case
        files.properties.pop('case', None)
        if include_case:
            files.properties.cases = cls.get_case_es_mapping(False)
            files.properties.cases.type = 'nested'

        return deepcopy(files.to_dict())

    @classmethod
    def get_case_es_mapping(cls, include_file=True):
        # case body
        case = cls._get_header('case')
        case.properties = cls._walk_tree(
            cls.get_case_tree(),
            cls.get_base_properties('case')
        )
        case.properties.days_to_index = LONG

        # Remove case.samples.aliquots from mapping
        case.properties.samples.properties.pop('aliquots')

        # Patch project
        cls.patch_project(case.properties.project.properties)

        # Patch case mutlifields
        cls.add_multifields(case, 'case')

        # Add top level id aggregation
        for label in cls.top_level_ids:
            case.properties['{}_ids'.format(label)] = STRING
            case.properties['submitter_{}_ids'.format(label)] = STRING

        # Add pop whatever file is present and add correct files
        case.properties.pop('file', None)
        if include_file:
            case.properties.files = cls.get_file_es_mapping(True)
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

        return deepcopy(case.to_dict())

    @classmethod
    def annotation_body(cls, nested=True):
        annotation = Dict()
        annotation.properties = cls.get_base_properties('annotation')
        annotation.properties.case_id = STRING
        annotation.properties.case_submitter_id = STRING
        annotation.properties.entity_type = STRING
        annotation.properties.entity_id = STRING
        annotation.properties.entity_submitter_id = STRING
        annotation.properties.pop('item_id', None)
        return annotation

    @classmethod
    def get_annotation_es_mapping(cls, include_file=True):
        annotation = cls._get_header('annotation')
        annotation.update(cls.annotation_body(nested=False))

        # Patch annotation mutlifields
        cls.add_multifields(annotation, 'annotation')

        # Remove annotation.creator viz. PGDC-2114
        annotation.properties.pop('creator', None)

        # Add the project and program
        annotation.properties.update(Dict({
            'project': {'properties': cls.get_base_properties('project')}}))
        annotation.properties.project.properties.program = {
            'properties': cls.get_base_properties('program')}

        return deepcopy(annotation.to_dict())

    @classmethod
    def get_project_es_mapping(cls):
        project = cls._get_header('project')
        project.properties = cls._walk_tree(
            cls.get_project_tree(),
            cls.get_base_properties('project'))

        # Patch annotation mutlifields
        cls.add_multifields(project, 'project')

        # Patch project
        cls.patch_project(project.properties)
        project.properties.update(cls.multifield('project_id'))

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

        return deepcopy(project.to_dict())
