import pathlib
import tempfile

from esbuild.export import mapping_exporter


def verify_export(output_dir: mapping_exporter.PathName) -> None:
    """Verify the exported mappings/settings files in a given output directory."""
    output_path = pathlib.Path(output_dir)

    # TODO Actually check file contents. Just do a smoke test right now.
    exported_filenames = set(p.name for p in output_path.iterdir())
    assert exported_filenames == {
        "annotation.mapping.yaml",
        "case.mapping.yaml",
        "descriptions.yaml",
        "file.mapping.yaml",
        "project.mapping.yaml",
        "settings.yaml",
    }


def test_export():
    """Export the graph mappings and verify the written files match the actual mappings.

    This test is kind of tautological in that it basically just checks if we wrote
    some files, but there isn't a lot else to test short of creating ES indices and
    seeing if the mappings match what go into ES.
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
