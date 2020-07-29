import pathlib
from typing import IO, Union

import yaml

from esbuild.graph.active import mappings


PathName = Union[pathlib.Path, str]


class MappingExporter:
    """Utility to export Elasticsearch mappings based on the dictionary."""

    DESCRIPTIONS_FILENAME = "descriptions.yaml"
    MAPPING_FILENAME_FORMAT = "{index_name}.mapping.yaml"
    SETTINGS_FILENAME = "settings.yaml"

    MAPPING_KEYS_TO_OMIT = ["_meta", "_source", "_size", "dynamic"]

    def __init__(self):
        self.mapper_cls = mappings.ActiveESMapper

    def write_mapping(self, index: str, output: IO) -> None:
        """Write a specific mapping as YAML to a stream.

        Omit parts of the mapping that other GDC libraries would typically pull in
        from shared files (e.g., descriptions).

        Args:
            index: For which index to write the mapping (e.g., ``case``).
            output: Stream to which to write.
        """
        mapping = self.mapper_cls.get_es_mapping(index)
        for key in self.MAPPING_KEYS_TO_OMIT:
            mapping.pop(key)

        yaml.safe_dump(mapping.to_dict(), output)

    def write_descriptions(self, output: IO) -> None:
        """Write the combined mapping description ``_meta`` as YAML to a stream."""
        descriptions = self.mapper_cls.get_descriptions()
        contents = {"_meta": {"descriptions": descriptions}}
        yaml.safe_dump(contents, output)

    def write_settings(self, output: IO) -> None:
        """Write the common index settings as YAML to a stream."""
        settings = self.mapper_cls.index_settings()
        contents = settings["settings"]
        yaml.safe_dump(contents, output)

    def export(self, output_dir: PathName) -> None:
        """Export mappings and settings files to the given directory.

        Create the directory if it does not already exist.
        """
        output_path = pathlib.Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        for index in self.mapper_cls.index_names:
            mapping_filename = self.MAPPING_FILENAME_FORMAT.format(index_name=index)
            with (output_path / mapping_filename).open("w") as output:
                self.write_mapping(index, output)

        with (output_path / self.DESCRIPTIONS_FILENAME).open("w") as output:
            self.write_descriptions(output)

        with (output_path / self.SETTINGS_FILENAME).open("w") as output:
            self.write_settings(output)
