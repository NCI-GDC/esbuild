import pathlib
from typing import Dict, IO, Union

import yaml

from esbuild.graph.active import mappings


PathName = Union[pathlib.Path, str]


class MappingExporter:
    """Utility to export Elasticsearch mappings based on the dictionary."""

    DESCRIPTIONS_FILENAME = "descriptions.yaml"
    MAPPING_FILENAME_FORMAT = "{mapping_name}.mapping.yaml"
    SETTINGS_FILENAME = "settings.yaml"

    # TODO These could be parsed from dir(self.mapper_cls), but see the comment below.
    MAPPING_NAMES = ["annotation", "case", "file", "project"]
    MAPPING_KEYS_TO_OMIT = ["_all", "_meta", "_source", "_size", "dynamic"]

    # TODO Refactor mapper class a little so we can pass the mapping name instead of
    # formatting the name of an accessor? Accessor hacks are expedient, but ugly.
    _MAPPING_GETTER_FORMAT = "get_{mapping_name}_es_mapping"

    def __init__(self):
        self.mapper_cls = mappings.ActiveESMapper

    def _write_yaml(self, contents: Dict, output: IO) -> None:
        """Write a dictionary as YAML to a stream, formatted how we want it."""

        # yaml.dump writes tuples as bizarre-looking tagged structures.
        # yaml.safe_dump formats them as normal lists.
        yaml.safe_dump(contents, output)

    def write_mapping(self, mapping_name: str, output: IO) -> None:
        """Write a specific mapping as YAML to a stream.

        Omit parts of the mapping that other GDC libraries would typically pull in
        from shared files (e.g., descriptions).

        Args:
            mapping_name: Which mapping to write (e.g., ``case``).
            output: Stream to which to write.
        """
        getter = self._MAPPING_GETTER_FORMAT.format(mapping_name=mapping_name)
        mapping = getattr(self.mapper_cls, getter)()

        for key in self.MAPPING_KEYS_TO_OMIT:
            mapping.pop(key)

        self._write_yaml(mapping.to_dict(), output)

    def write_descriptions(self, output: IO) -> None:
        """Write the combined mapping description ``_meta`` as YAML to a stream."""
        descriptions = self.mapper_cls.get_descriptions()
        contents = {"_meta": {"descriptions": descriptions}}
        self._write_yaml(contents, output)

    def write_settings(self, output: IO) -> None:
        """Write the common index settings as YAML to a stream."""
        settings = self.mapper_cls.index_settings()
        contents = settings["settings"]
        self._write_yaml(contents, output)

    def export(self, output_dir: PathName) -> None:
        """Export mappings and settings files to the given directory.

        Create the directory if it does not already exist.
        """
        output_path = pathlib.Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        for mapping in self.MAPPING_NAMES:
            mapping_filename = self.MAPPING_FILENAME_FORMAT.format(mapping_name=mapping)
            with (output_path / mapping_filename).open("w") as output:
                self.write_mapping(mapping, output)

        with (output_path / self.DESCRIPTIONS_FILENAME).open("w") as output:
            self.write_descriptions(output)

        with (output_path / self.SETTINGS_FILENAME).open("w") as output:
            self.write_settings(output)
