from base import BaseParser


class ESArgs(BaseParser):
    """
    Elasticsearch settings arguments
    """

    @property
    def group(self):
        return dict(
            title='Elasticsearch preferences',
            description='Arguments to tweak elasticsearch settings',
        )

    @property
    def arguments(self):
        return {
            'n-shards': dict(
                help='Number of primary shards per index',
                default=6,
                type=int,
            ),
            'n-replicas': dict(
                help='Number of replicas per shard',
                default=0,
                type=int,
            ),

        }
