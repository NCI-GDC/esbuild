"""
Elasticsearch test documents are defined here
"""
from esbuild.graph.active.mappings import ESMapper

dummy_docs = [
    {
        "id": "test-doc-1",
        "value": 1,
    },
    {
        "id": "test-doc-2",
        "value": 2,
    },
]

build_metadata = [
    {
        "build_projects": [
            "TCGA-DLBC",
            "TCGA-PRAD",
            "TARGET-OS",
            "TARGET-RT",
            "TCGA-STAD",
        ],
        "commit_hash": "a07731187614da9788fc453dcfd22aac8222592b",
        "counts": {"annotation": 10, "case": 16, "file": 9, "project": 5},
    },
    {
        "build_projects": ["TARGET-NBL", "FM-AD", "TCGA-THYM"],
        "commit_hash": "a07731187614da9788fc453dcfd22aac8222592b",
        "counts": {"annotation": 4, "case": 15, "file": 5, "project": 3},
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
    mapping = getattr(ESMapper, f"get_{index_type}_es_mapping")()
    mapping.pop("_all", None)
    return mapping
