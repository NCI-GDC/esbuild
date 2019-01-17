import os
from psqlgraph import PsqlGraphDriver
from gdcdatamodel import models as md


class PostgresUtil(object):

    def __init__(self):
        self.g = PsqlGraphDriver(
            os.environ["PG_HOST"],
            os.environ["PG_USER"],
            os.environ["PG_PASS"],
            os.environ["PG_NAME"],
        )

    def get_release_candidate_info(self):
        """
        Lookup release candidate name and version in postgres
        """

        with self.g.session_scope():
            release_node = (self.g.nodes(md.DataRelease)
                                  .props(released=False).first())

        if release_node is None:
            raise ValueError('No unreleased DataRelease node found in postgres')

        release_name = release_node.name
        release_version = [release_node.major_version, release_node.minor_version]
        return release_name, release_version
