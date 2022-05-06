"""
Elasticsearch test documents are defined here
"""
from esbuild.graph.active.mappings import ESMapper

dummy_docs = [{"id": "test-doc-1", "value": 1,}, {"id": "test-doc-2", "value": 2,}]

build_metadata = [
    {
        u"build_projects": [
            u"TCGA-DLBC",
            u"TCGA-PRAD",
            u"TARGET-OS",
            u"TARGET-RT",
            u"TCGA-STAD",
        ],
        u"commit_hash": u"a07731187614da9788fc453dcfd22aac8222592b",
        u"counts": {u"annotation": 10, u"case": 16, u"file": 9, u"project": 5},
    },
    {
        u"build_projects": [u"TARGET-NBL", u"FM-AD", u"TCGA-THYM"],
        u"commit_hash": u"a07731187614da9788fc453dcfd22aac8222592b",
        u"counts": {u"annotation": 4, u"case": 15, u"file": 5, u"project": 3},
    },
]

case_docs = [
    {"project": {"project_id": "TCGA-DLBC"}},
    {"project": {"project_id": "TCGA-DLBC"}},
    {"project": {"project_id": "TCGA-DLBC"}},
    {"project": {"project_id": "TCGA-DLBC"}},
    {"project": {"project_id": "TCGA-PRAD"}},
    {"project": {"project_id": "TCGA-PRAD"}},
    {"project": {"project_id": "TCGA-PRAD"}},
    {"project": {"project_id": "TCGA-PRAD"}},
    {"project": {"project_id": "TARGET-OS"}},
    {"project": {"project_id": "TARGET-OS"}},
    {"project": {"project_id": "TARGET-OS"}},
    {"project": {"project_id": "TARGET-RT"}},
    {"project": {"project_id": "TARGET-RT"}},
    {"project": {"project_id": "TCGA-STAD"}},
    {"project": {"project_id": "TCGA-STAD"}},
    {"project": {"project_id": "TCGA-STAD"}},
    {"project": {"project_id": "TARGET-NBL"}},
    {"project": {"project_id": "TARGET-NBL"}},
    {"project": {"project_id": "TARGET-NBL"}},
    {"project": {"project_id": "TARGET-NBL"}},
    {"project": {"project_id": "TARGET-NBL"}},
    {"project": {"project_id": "TCGA-THYM"}},
    {"project": {"project_id": "TCGA-THYM"}},
    {"project": {"project_id": "TCGA-THYM"}},
    {"project": {"project_id": "FM-AD"}},
    {"project": {"project_id": "FM-AD"}},
    {"project": {"project_id": "FM-AD"}},
    {"project": {"project_id": "FM-AD"}},
    {"project": {"project_id": "FM-AD"}},
    {"project": {"project_id": "FM-AD"}},
    {"project": {"project_id": "FM-AD"}},
]
file_docs = [
    {
        "cases": [
            {"project": {"project_id": "TCGA-DLBC"}},
            {"project": {"project_id": "TCGA-DLBC"}},
        ]
    },
    {
        "cases": [
            {"project": {"project_id": "TCGA-PRAD"}},
            {"project": {"project_id": "TCGA-PRAD"}},
        ]
    },
    {
        "cases": [
            {"project": {"project_id": "TARGET-OS"}},
            {"project": {"project_id": "TARGET-OS"}},
        ]
    },
    {
        "cases": [
            {"project": {"project_id": "TARGET-RT"}},
            {"project": {"project_id": "TARGET-RT"}},
        ]
    },
    {"cases": [{"project": {"project_id": "TCGA-STAD"}}]},
    {"cases": [{"project": {"project_id": "TARGET-NBL"}}]},
    {"cases": [{"project": {"project_id": "TCGA-THYM"}}]},
    {"cases": [{"project": {"project_id": "FM-AD"}}]},
    {
        "cases": [
            {"project": {"project_id": "FM-AD"}},
            {"project": {"project_id": "FM-AD"}},
        ]
    },
    {"cases": [{"project": {"project_id": "FM-AD"}}]},
]
project_docs = [
    {"project_id": "TCGA-DLBC"},
    {"project_id": "TCGA-PRAD"},
    {"project_id": "TARGET-OS"},
    {"project_id": "TARGET-RT"},
    {"project_id": "TCGA-STAD"},
    {"project_id": "TARGET-NBL"},
    {"project_id": "TCGA-THYM"},
    {"project_id": "FM-AD"},
]
annotation_docs = [
    {"project": {"project_id": "TCGA-DLBC"}},
    {"project": {"project_id": "TCGA-DLBC"}},
    {"project": {"project_id": "TCGA-DLBC"}},
    {"project": {"project_id": "TCGA-DLBC"}},
    {"project": {"project_id": "TCGA-PRAD"}},
    {"project": {"project_id": "TARGET-OS"}},
    {"project": {"project_id": "TARGET-RT"}},
    {"project": {"project_id": "TARGET-RT"}},
    {"project": {"project_id": "TCGA-STAD"}},
    {"project": {"project_id": "TCGA-STAD"}},
    {"project": {"project_id": "TARGET-NBL"}},
    {"project": {"project_id": "TCGA-THYM"}},
    {"project": {"project_id": "TCGA-THYM"}},
    {"project": {"project_id": "FM-AD"}},
]


def get_index_settings():
    return ESMapper.index_settings()


def get_mapping(index_type):
    mapping = getattr(ESMapper, "get_{}_es_mapping".format(index_type))()
    mapping.pop("_all", None)
    return mapping
