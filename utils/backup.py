import elasticsearch
import logging
import pprint
import os
from es import ElasticsearchUtil
from elasticsearch import Elasticsearch

logger = logging.getLogger(__name__)


class BackupUtil(object):
    """
    Helps to store and restore snapshots
    from dedicated s3 bucket, repository
    """

    def __init__(self):
        self.es_client = ElasticsearchUtil().es
        self.es_snapshot = elasticsearch.client.SnapshotClient(self.es_client)

        self.s3_host = os.environ["S3_HOST"]
        self.s3_access_key = os.environ["S3_ACCESS_KEY"]
        self.s3_secret_key = os.environ["S3_SECRET_KEY"]
        self.s3_bucket = os.environ["S3_REPOSITORY_BUCKET"]
        self.s3_repository_name = self.s3_bucket  # for simplicity

    def backup(self, snapshot_name, indices):
        """
        Stores indices as a snapshot in s3 repository
        """

        if indices != '_all':
            if isinstance(indices, str):
                indices = [indices]

        logger.info("Saving {} to snapshot {}".format(indices, snapshot_name))

        # Create repository if not found
        if self.s3_repository_name not in self.es_snapshot.get_repository():
            self._create_repository(self.s3_repository_name)

        snapshot_settings = {
            "indices": ','.join(indices),
            "ignore_unavailable": False,
            "include_global_state": True
        }
        self.es_snapshot.create(body=snapshot_settings,
                                repository=self.s3_repository_name,
                                snapshot=snapshot_name,
                                wait_for_completion=False)
        logger.info("Backup to s3 initialized. Will take time to complete")

    def restore(self, snapshot_name, indices, rename_pattern=None):
        """
        Restore indices from snapshot
        If indices == '_all', will restore all
        """
        if indices != '_all':
            if isinstance(indices, str):
                indices = [indices]

            existing_indices = self.es_client.indices.get_alias()
            for index_name in indices:
                if index_name in existing_indices:
                    raise Exception('Index {} already exists.'.format(index_name))

        logger.info("Restoring {} from snapshot {}.\nWill take some time..."
                    .format(indices, snapshot_name))
        repository_name = self.s3_repository_name
        # Create repository if not found
        if repository_name not in self.es_snapshot.get_repository():
            self._create_repository(repository_name)

        restore_settings = {
            "ignore_unavailable": False,
            "include_global_state": True,
        }

        if rename_pattern:
            restore_settings["rename_pattern"] = '(.+)'
            restore_settings["rename_replacement"] = rename_pattern

        if indices != '_all':
            restore_settings['indices'] = ','.join(indices)

        self.es_snapshot.restore(repository=repository_name,
                                 snapshot=snapshot_name,
                                 body=restore_settings,
                                 wait_for_completion=False)
        logger.info("Started restoring indices.")

    def list(self, snapshot_name=None):
        """
        List all snapshots in repository
        If :snapshot_name is passed, show details about the snapshot
        """
        if snapshot_name is None:
            logger.info("Listing {} snapshots:".format(self.s3_repository_name))
        else:
            logger.info("{}: snapshot {}:".format(self.s3_repository_name, snapshot_name))
        return self._list_repository(self.s3_repository_name, snapshot_name)

    def _create_repository(self, repository_name):
        """
        Creates repository in es cluster associated with S3 bucket
        Cluster and bucket are chosen during __init__
        """
        repository_settings = {
            "type": "s3",
            "settings": {
                "bucket": self.s3_bucket,
                "endpoint": self.s3_host,
                "access_key": self.s3_access_key,
                "secret_key": self.s3_secret_key,
            }
        }
        self.es_snapshot.create_repository(repository=repository_name,
                                           body=repository_settings)

    def _delete_repository(self, repository_name, snapshot_name=None):
        """
        Deletes repository (default) or a particular snapshot
        """
        if not snapshot_name:
            self.es_snapshot.delete_repository(repository=repository_name)
        else:
            self.es_snapshot.delete(repository=repository_name,
                                    snapshot=snapshot_name)

    def _list_repository(self, repository_name, snapshot_name=None):
        """
        List all snapshots in repository
        If :snapshot_name is passed, show details about the snapshot
        """
        if snapshot_name is None:
            snapshot_name = '_all'

        snapshots = self.es_snapshot.get(repository_name, snapshot_name)['snapshots']

        # Return all snapshot names
        if snapshot_name == '_all':
            return sorted([s['snapshot'] for s in snapshots])

        # Return details about :snapshot_name
        return snapshots[0]
