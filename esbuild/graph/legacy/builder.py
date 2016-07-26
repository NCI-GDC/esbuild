# -*- coding: utf-8 -*-
"""
esbuild.graph.legacy.builder
----------------------------------

Defines :class:`LegacyGraphIndexBuilder` for building the graph index
for Legacy projects.

"""

from ..common.builder import (
    GraphIndexBuilder,
)

from .mappings import (
    LegacyESMapper,
)


class LegacyGraphIndexBuilder(GraphIndexBuilder):

    mapper = LegacyESMapper

    case_to_file_paths = [
        ['file'],
        ['sample', 'aliquot', 'file'],
        ['sample', 'portion', 'file'],
        ['sample', 'portion', 'analyte', 'aliquot', 'file'],
        ['sample', 'portion', 'slide', 'file'],
        ['biospecimen_supplement'],
        ['clinical_supplement'],
    ]

    # Types of nodes to be treated as files
    file_labels = [
        'file',
        'biospecimen_supplement',
        'clinical_supplement',
    ]

    def denormalize_all(self):
        """Return an entire index worth of case, file, annotation, and
        project documents

        Overrides the Common Builder `denormalize_all()` method in
        order to include files from archives that are not attached to
        biospecimen nodes.

        """

        cases, files, annotations = self.denormalize_cases()

        # Add in files that weren't visited by denormalizing files
        # only attached to archives
        visited_file_ids = {
            file_['file_id']
            for file_ in files
        }
        files += self.denormalize_archive_files(visited_file_ids)

        projects = self.denormalize_projects()
        return cases, files, annotations, projects

    def denormalize_archive_files(self, visited_file_ids=None):
        """Starting at each archive in the graph, denormalize its files.

        This is intended to be used in addition to
        `self.denormalize_case()` wherein the set of resulting file
        ids is provided as :param:`visited_file_ids`.  This allows the
        legacy index to include files that are not connected to cases
        along canonical paths.

        """

        archives = self.nodes_labeled('archive')
        file_docs = []

        if visited_file_ids is None:
            visited_file_ids = set()

        for archive in archives:
            for file_ in self.neighbors_labeled(archive, self.file_labels):
                # skip any files visited in or before this function
                if file_.node_id in visited_file_ids:
                    continue

                file_docs.append(self.denormalize_file(file_, {}))
                visited_file_ids.add(file_.node_id)

        return file_docs
