import os.path
import pathlib
from typing import IO, Union

import deepdiff
import yaml
from gdcmodels import mapping_utils

from esbuild.graph.active import mappings

PathName = Union[pathlib.Path, str]


class MappingExporter:
    """Utility to export Elasticsearch mappings based on the dictionary."""

    DESCRIPTIONS_FILENAME = "descriptions.yaml"
    MAPPING_FILENAME_FORMAT = "{index_name}.mapping.yaml"
    OBSOLETE_MAPPING_FILENAME_FORMAT = "{index_name}.obsolete.mapping.yaml"
    SETTINGS_FILENAME = "settings.yaml"

    MAPPING_KEYS_TO_OMIT = ["_meta", "_source", "_size", "dynamic"]

    def __init__(self):
        self.mapper_cls = mappings.ActiveESMapper

    def write_mapping(self, index: str, output_path: pathlib.Path) -> None:
        """Write a specific mapping as YAML to a stream.

        Omit parts of the mapping that other GDC libraries would typically pull in
        from shared files (e.g., descriptions).

        Args:
            index: For which index to write the mapping (e.g., ``case``).
        """
        # New mapping
        new_mapping = self.mapper_cls.get_es_mapping(index)
        for key in self.MAPPING_KEYS_TO_OMIT:
            new_mapping.pop(key)

        # Convert it from addict to python dict. deepdiff will detect this as a
        # type change and say there's a diff.
        new_mapping = new_mapping.to_dict()

        # Current mapping
        mapping_filename = self.MAPPING_FILENAME_FORMAT.format(index_name=index)
        with open(output_path / mapping_filename) as f:
            current_mapping = yaml.safe_load(f)

        diff = deepdiff.DeepDiff(
            new_mapping,
            current_mapping,
            ignore_order=True,
            report_repetition=True,
        )
        if diff:
            mapping_diff = {} + deepdiff.Delta(diff, force=True)
            obsolete_mapping_filename = self.OBSOLETE_MAPPING_FILENAME_FORMAT.format(
                index_name=index
            )
            obsolete_exists = os.path.exists(output_path / obsolete_mapping_filename)
            with open(output_path / obsolete_mapping_filename, "w+") as f:
                obsolete_mappings = mapping_diff
                if obsolete_exists:
                    obsolete_mappings = yaml.safe_load(f)
                    obsolete_mappings = mapping_utils.deep_merge_mapping_files(
                        obsolete_mappings, mapping_diff
                    )
                yaml.safe_dump(obsolete_mappings, f)

        with open(output_path / mapping_filename, "w") as f:
            yaml.safe_dump(new_mapping, f)

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
            self.write_mapping(index, output_path)

        with (output_path / self.DESCRIPTIONS_FILENAME).open("w") as output:
            self.write_descriptions(output)

        with (output_path / self.SETTINGS_FILENAME).open("w") as output:
            self.write_settings(output)
