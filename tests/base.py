from unittest import TestCase

import os
import random
import string
import uuid

from cdisutils.log import get_logger
from gdcdictionary import gdcdictionary
from psqlgraph import PsqlGraphDriver, Node, Edge

TEST_DIR = os.path.dirname(os.path.realpath(__file__))
DATA_DIR = os.path.join(TEST_DIR, 'data')

PG_HOST = 'localhost'
PG_USER = 'test'
PG_PASSWORD = 'test'
PG_DATABASE = 'automated_test'


class TestBase(TestCase):

    logger = get_logger('tests')

    g = PsqlGraphDriver(
        PG_HOST,
        PG_USER,
        PG_PASSWORD,
        PG_DATABASE,
    )

    @classmethod
    def delete_all_nodes(cls):
        tables = [
            t for l in map(
                lambda x: x().get_subclass_table_names(), (Edge, Node)
            ) for t in l
            if t != Edge.__tablename__ and t != Node.__tablename__
        ] + [
            '_voided_nodes',
            '_voided_edges',
        ]

        with cls.g.engine.begin() as conn:
            conn.execute('TRUNCATE {}'.format(', '.join(tables)))

    @classmethod
    def random_string(cls, length=6):
        return ''.join([
            random.choice(
                string.ascii_lowercase + string.digits
            ) for _ in range(length)
        ])

    @classmethod
    def get_fuzzed_node(cls, node_class, node_id=None, **kwargs):
        if node_id is None:
            node_id = str(uuid.uuid4())
        for key, types in node_class.get_pg_properties().iteritems():
            schema = gdcdictionary.schema[node_class.label]
            prop_def = schema['properties'].get(key, {})

            if key in kwargs:
                continue

            # Enum
            elif 'enum' in prop_def:
                kwargs[key] = prop_def['enum'][0]

            # String
            elif not types or str in types:
                kwargs[key] = cls.random_string()

            # Integer
            elif int in types or long in types:
                kwargs[key] = random.randint(1e6, 1e7)

            # Float
            elif float in types:
                kwargs[key] = random.random()

            # Boolean
            elif bool in types:
                kwargs[key] = random.choice((True, False))

        return node_class(node_id, **kwargs)
