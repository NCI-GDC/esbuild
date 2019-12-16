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
    file_mapping = mapper.get_file_es_mapping()

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
        # Archives are manually included regardless of path to
        # case. see self.denormalize_archive_files()
        'archive',
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

    def is_node_indexed(self, node):
        """Augments parent's method"""
        if not super(LegacyGraphIndexBuilder, self).is_node_indexed(node):
            return False
        else:
            if node.label == 'project':
                return node.state == 'legacy'
            elif node.label == 'case':
                projects = list(self.neighbors_labeled(node, 'project', 1))
                return any([p.state == 'legacy' for p in projects])
            else:
                return True

    def get_archive_as_file_doc(self, archive):
        """Returns a an archive doc in format consistent with file index"""

        archive_doc = self.denormalize_file(archive, {})
        self.validate_against_mapping(archive_doc, self.file_mapping)

        return archive_doc

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
            # Add file metadata properties to archive:
            archive = self.add_file_metadata_from_indexd(archive)

            # Add only archives related to self.build_projects in case of split build
            project_id = None
            for project in self.neighbors_labeled(archive, 'project'):
                project_id = '-'.join([next(self.neighbors_labeled(project, 'program')).name,
                                       project.code])

            n_projects = len(list(self.neighbors_labeled(archive, 'project')))
            if n_projects != 1:
                self.warning('Number of archive projects is not 1',
                             '{} has {} projects, this is unexpected.'
                             .format(archive, n_projects),
                             tags=['archive_id:{}'.format(archive.node_id)])

            if not self.build_projects or n_projects == 0 or project_id in self.build_projects:
                file_docs.append(self.get_archive_as_file_doc(archive))
                for file_ in self.neighbors_labeled(archive, self.file_labels):
                    # skip any files visited in or before this function
                    if file_.node_id in visited_file_ids:
                        continue

                    # Add file metadata properties to neighbor file:
                    file_ = self.add_file_metadata_from_indexd(file_)

                    # Denormalize the file
                    file_docs.append(self.denormalize_file(file_, {}))
                    visited_file_ids.add(file_.node_id)

        return file_docs
