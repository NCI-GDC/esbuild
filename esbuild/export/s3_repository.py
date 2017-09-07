import elasticsearch


class BackupHelper:
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
        Creates reposirory in es cluster associated with S3 bucket
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
            self.es_snapshot.delete(repository=repository_name, snapshot=snapshot_name)

    def store_snapshot(self, repository_name, snapshot_name, indices):
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
                                snapshot=snapshot_name)

    def restore_from_snapshot(self, repository_name, snapshot_name,
                              indices='all', wait_for_completion=True):
        # Create repository if not found
        if repository_name not in self.es_snapshot.get_repository():
            self.create_repository(repository_name)

        restore_settings = {
            "ignore_unavailable": False,
            "include_global_state": True,
            # "rename_pattern": "index_(.+)",
            # "rename_replacement": "restored_index_$1"
        }
        if indices != 'all':
            restore_settings['indices'] = ','.join(indices)

        self.es_snapshot.restore(repository=repository_name,
                                 snapshot=snapshot_name,
                                 body=restore_settings,
                                 wait_for_completion=wait_for_completion)
