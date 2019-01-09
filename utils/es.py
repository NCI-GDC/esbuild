import os
from elasticsearch import Elasticsearch


class ElasticsearchUtil(object):

    def __init__(self, **es_args):
        self.es = Elasticsearch(
            host=es_args.get('es_host', os.getenv('ES_HOST')),
            port=es_args.get('es_port', os.getenv('ES_PORT')),
            http_auth=(
                es_args.get('es_user', os.getenv('ES_USER')),
                es_args.get('es_pass', os.getenv('ES_PASS')),
            ),
            timeout=9999,
        )

    def alias(self, index, alias_name='gdc_from_graph'):
        """
        Aliases :index to :alias_name
        """
        self.es.indices.put_alias(index=index, name=alias_name)
