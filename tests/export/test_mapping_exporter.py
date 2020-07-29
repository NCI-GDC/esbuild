import pathlib
import tempfile
from typing import Dict

import yaml

from esbuild.export import mapping_exporter
from esbuild.graph.active import mappings


def load_yaml(path: pathlib.Path) -> Dict:
    with path.open() as in_file:
        return yaml.safe_load(in_file)


def verify_export(output_dir: mapping_exporter.PathName) -> None:
    """Verify the exported mappings/settings files in the given output directory."""
    output_path = pathlib.Path(output_dir)

    assert (
        load_yaml(output_path / "annotation.mapping.yaml")["properties"]
        == mappings.ActiveESMapper.get_annotation_es_mapping()["properties"]
    )
    assert (
        load_yaml(output_path / "case.mapping.yaml")["properties"]
        == mappings.ActiveESMapper.get_case_es_mapping()["properties"]
    )
    assert (
        load_yaml(output_path / "file.mapping.yaml")["properties"]
        == mappings.ActiveESMapper.get_file_es_mapping()["properties"]
    )
    assert (
        load_yaml(output_path / "project.mapping.yaml")["properties"]
        == mappings.ActiveESMapper.get_project_es_mapping()["properties"]
    )

    assert (
        load_yaml(output_path / "descriptions.yaml")["_meta"]["descriptions"]
        == mappings.ActiveESMapper.get_descriptions()
    )

    assert (
        load_yaml(output_path / "settings.yaml")
        == mappings.ActiveESMapper.index_settings()["settings"]
    )


def test_export():
    """Export the graph mappings and verify the written files match the actual mappings.

    This test is kind of tautological in that it basically just checks if we wrote
    some files, but there isn't much else we can test without digging into the mapper
    logic, which is better tested elsewhere.
    """
    exporter = mapping_exporter.MappingExporter()
    with tempfile.TemporaryDirectory() as tempdir:
        exporter.export(tempdir)
        verify_export(tempdir)


def test_export__creates_output_dir():
    """Verify the export creates the output directory if needed."""
    exporter = mapping_exporter.MappingExporter()
    with tempfile.TemporaryDirectory() as parentdir:
        tempdir = pathlib.Path(parentdir) / "subdir_to_create"
        exporter.export(output_dir=tempdir)
        verify_export(tempdir)
