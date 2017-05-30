from addict import Dict
import yaml
import os

from gdcdictionary import gdcdictionary
from gdcdatamodel import models
from psqlgraph import Node


# ======================================================================
# Parent-child relationships

ONE_TO_ONE = '__one_to_one__'
ONE_TO_MANY = '__one_to_many__'

# ======================================================================
# Types

STRING = {
    'type': 'keyword',
}

LONG = {
    'type': 'long',
}

INTEGER = {
    'type': 'integer',
}


class BaseESMapper(object):

    top_level_ids = [
        'sample',
        'portion',
        'analyte',
        'aliquot',
        'slide',
    ]

    @staticmethod
    def get_mapping(mapping_type):
        """
        Reads .yaml mapping from gdc-models into a dictionary

        :mapping_type in ['annotation', 'case', 'file', 'project', 'settings']
        :returns <dict>
        """
        assert mapping_type in ['annotation', 'case', 'file', 'project',
                                'settings']

        if mapping_type != 'settings':
            mapping_type = mapping_type + '.mapping'

        def step_up(path, n_times=1):
            if n_times == 1:
                return os.path.dirname(path)
            else:
                return step_up(os.path.dirname(path), n_times - 1)

        root_dir = step_up(os.path.abspath(__file__), n_times=2)
        root_dir = os.path.join(root_dir, 'common', 'gdc-models', 'es-models',
                                'gdc_from_graph')
        filename = '{}.yaml'.format(mapping_type)

        with open(os.path.join(root_dir, filename), 'r') as f:
            mapping = yaml.safe_load(f.read())

        return mapping

    @classmethod
    def get_annotation_es_mapping(cls):
        mapping = cls.get_mapping('annotation')
        mapping.update(cls._get_header().to_dict())
        return mapping

    @classmethod
    def get_case_es_mapping(cls):
        mapping = cls.get_mapping('case')
        mapping.update(cls._get_header().to_dict())
        return mapping

    @classmethod
    def get_file_es_mapping(cls):
        mapping = cls.get_mapping('file')
        mapping.update(cls._get_header().to_dict())
        return mapping

    @classmethod
    def get_project_es_mapping(cls):
        mapping = cls.get_mapping('project')
        mapping.update(cls._get_header().to_dict())
	return mapping

    @classmethod
    def index_settings(cls):
        settings = {
            "settings": {
	    	"mapping.nested_fields.limit": 150,
		"index.mapping.total_fields.limit": 2000,
		"index.max_result_window" : 100000000,
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
	
	loaded_settings = cls.get_mapping('settings')['analysis']
	
	for a in ['analyzer', 'filter']:
	    settings['settings']['analysis'][a].update(loaded_settings[a])

        return settings

    @classmethod
    def _get_header(cls):
        header = Dict()
        header.dynamic = 'strict'
        header._all.enabled = False
        header._source.excludes = ["__comment__"]
        header._meta.descriptions = cls._get_descriptions()
        return header

    @classmethod
    def _get_descriptions(cls):
        """
        Get a description for properties of all defined node types
        """
        descriptions = {}

        descriptions.update({
            'files.file.{}'.format(prop):
                cls._get_prop_description('file', prop)
            for prop in Node.get_subclass('file').__pg_properties__})
        descriptions.update({
            'cases.case.{}'.format(prop):
                cls._get_prop_description('case', prop)
            for prop in Node.get_subclass('case').__pg_properties__})
        descriptions.update({
            'projects.project.{}'.format(prop):
                cls._get_prop_description('project', prop)
            for prop in Node.get_subclass('project').__pg_properties__})
        descriptions.update({
            'annotations.annotation.{}'.format(prop):
                cls._get_prop_description('annotation', prop)
            for prop in Node.get_subclass('file').__pg_properties__})

        return descriptions

    @classmethod
    def _get_prop_description(cls, label, prop):
        """
        Look the description up from the ``term`` if it exists, else try
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

    #################### Handwritten mapping trees ####################

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
