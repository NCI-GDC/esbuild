from ..common.mappings import BaseESMapper
import json
import os


class LegacyESMapper(BaseESMapper):

    @staticmethod
    def load_mapping(mapping_type):
        filename = '{}_legacy_mapping.json'.format(mapping_type)
        dirname = os.path.join(os.path.dirname(__file__), 'mappings')
        with open(os.path.join(dirname, filename), 'r') as f:
            mapping = json.loads(f.read())
        return mapping

    @classmethod
    def get_annotation_es_mapping(cls):
        return cls.load_mapping('annotation')

    @classmethod
    def get_case_es_mapping(cls):
        return cls.load_mapping('case')

    @classmethod
    def get_file_es_mapping(cls):
        return cls.load_mapping('file')

    @classmethod
    def get_project_es_mapping(cls):
        return cls.load_mapping('project')


get_file_es_mapping = LegacyESMapper.get_file_es_mapping
get_case_es_mapping = LegacyESMapper.get_case_es_mapping
get_project_es_mapping = LegacyESMapper.get_project_es_mapping
get_annotation_es_mapping = LegacyESMapper.get_annotation_es_mapping
index_settings = LegacyESMapper.index_settings
