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
        self.repository_name = os.environ["S3_REPOSITORY"]
        self.backuper = S3RepositoryUtil(
            self.es_client,
            os.environ["S3_HOST"],
            os.environ["S3_ACCESS_KEY"],
            os.environ["S3_SECRET_KEY"],
            self.repository_name,
        )

    def backup(self, snapshot_name, indices):
        if indices != '_all':
            if isinstance(indices, str):
                indices = [indices]

        logger.info("Saving {} to snapshot {}"
                    .format(indices, snapshot_name))
        self.backuper.store_snapshot(self.repository_name,
                                     snapshot_name, indices=indices,
                                     wait_for_completion=False)
        logger.info("Backup to s3 initialized. Will take time to complete")

    def restore(self, snapshot_name, indices):
        if indices != '_all':
            if isinstance(indices, str):
                indices = [indices]

            for index_name in indices:
                if index_name in self.es_client.indices.get_alias():
                    raise Exception('Index {} already exists.'.format(index_name))

        logger.info("Restoring {} from snapshot {}.\nWill take some time..."
                    .format(indices, snapshot_name))
        self.backuper.restore_from_snapshot(
            self.repository_name,
            snapshot_name, indices=indices,
            wait_for_completion=False,
        )
        logger.info("Indices restored")

    def list(self, repository_name, snapshot_name=None):
        """
        List all snapshots in repository
        If :snapshot_name is passed, show details about the snapshot
        """
        if snapshot_name is None:
            logger.info("Listing {} snapshots:".format(repository_name))
        else:
            logger.info("{}: snapshot {}:".format(repository_name, snapshot_name))
        res = self.backuper.list_repository(repository_name, snapshot_name)
        logger.info(pprint.pformat(res))


class S3RepositoryUtil(object):
    """
    Wraps backup-restore to s3 operations for elasticsearch indices.
    Elasticsearch cluster has to have 'repository-s3' plugin installed.
    Refer to https://www.elastic.co/guide/en/elasticsearch/reference/current/modules-snapshots.html
    """

    def __init__(self, es, s3_host, s3_access_key, s3_secret_key, s3_bucket):
        self.es = es
        self.es_snapshot = elasticsearch.client.SnapshotClient(es)
        self.s3_creds = {'host': s3_host, 'access_key': s3_access_key,
                         'secret_key': s3_secret_key, 'bucket': s3_bucket}

    def create_repository(self, repository_name):
        """
        Creates repository in es cluster associated with S3 bucket
        Cluster and bucket are chosen during __init__
        """
        repository_settings = {
            "type": "s3",
            "settings": {
                "bucket": self.s3_creds['bucket'],
                "endpoint": self.s3_creds['host'],
                "access_key": self.s3_creds['access_key'],
                "secret_key": self.s3_creds['secret_key']
            }
        }
        self.es_snapshot.create_repository(repository=repository_name,
                                           body=repository_settings)

    def delete_repository(self, repository_name, snapshot_name=None):
        """
        Deletes repository (default) or a particular snapshot
        """
        if not snapshot_name:
            self.es_snapshot.delete_repository(repository=repository_name)
        else:
            self.es_snapshot.delete(repository=repository_name,
                                    snapshot=snapshot_name)

    def store_snapshot(self, repository_name, snapshot_name, indices,
                       wait_for_completion=True):
        """
        Stores indices as a snapshot in s3 repository
        """
        # Create repository if not found
        if repository_name not in self.es_snapshot.get_repository():
            self.create_repository(repository_name)

        snapshot_settings = {
            "indices": ','.join(indices),
            "ignore_unavailable": False,
            "include_global_state": True
        }
        self.es_snapshot.create(body=snapshot_settings,
                                repository=repository_name,
                                snapshot=snapshot_name,
                                wait_for_completion=wait_for_completion)

    def restore_from_snapshot(self, repository_name, snapshot_name, indices='_all',
                              rename_pattern=None, wait_for_completion=True):
        # Create repository if not found
        if repository_name not in self.es_snapshot.get_repository():
            self.create_repository(repository_name)

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
                                 wait_for_completion=wait_for_completion)

    def list_repository(self, repository_name, snapshot_name=None):
        """
        List all snapshots in repository
        If :snapshot_name is passed, show details about the snapshot
        """
        if snapshot_name is None:
            snapshot_name = '_all'

        snapshots = self.es_snapshot.get('esbuild-snapshots', snapshot_name)['snapshots']

        # Return all snapshot names
        if snapshot_name == '_all':
            return sorted([s['snapshot'] for s in snapshots])

        # Return details about :snapshot_name
        return snapshots[0]
