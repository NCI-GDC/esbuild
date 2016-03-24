from unittest import TestCase

import os
import random
import string
import uuid

from cdisutils.log import get_logger
from gdcdatamodel import models as md
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

    def delete_non_prelude_nodes(self):
        self.logger.info('Deleting all non-prelude nodes')

        with self.g.session_scope():
            for scls in Node.get_subclasses():
                self.g.nodes(scls).not_sysan(is_prelude=True)\
                                  .delete(synchronize_session='fetch')

        with self.g.engine.begin() as conn:
            conn.execute('TRUNCATE _voided_nodes, _voided_edges')

    def add_file_nodes(self):
        self.live_file = md.File(
            node_id='file1',
            project_id='TCGA-BRCA',
            file_name='TCGA-WR-A838-01A-12R-A406-31_rnaseq_fastq.tar',
            file_size=12916551680,
            md5sum='d7e6cbd40ef2f5b6607cb4af982280a9',
            state='live',
            file_state='submitted',
            state_comment=None,
            submitter_id='5cb6bc65-9cd5-45ac-9078-551bc7408906',
            error_type=None,
        )

        self.index_file = self.get_fuzzed_node(
            md.File,
            state='live',
            file_name='test_file.bam.bai',
        )

        self.non_index_file = self.get_fuzzed_node(
            md.File,
            state="live",
            file_state='submitted',
            file_name="a_related_file.txt"
        )

        with self.g.session_scope():
            self.live_file.related_files = [
                self.index_file,
                self.non_index_file,
            ]
            self.live_file.data_subtypes = [
                self.g.nodes(md.DataSubtype)
                .props(name='Unaligned reads')
                .one()
            ]

        self.non_live_file = self.get_fuzzed_node(
            md.File, state='uploaded'
        )

        self.to_delete_file = md.File(
            node_id='file2',
            project_id='TCGA-BRCA',
            file_name='a_file_to_be_deleted.txt',
            file_size=5,
            md5sum='foobar',
            state='live',
            file_state='submitted',
            state_comment=None,
            submitter_id='5cb6bc65-9cd5-45ac-9078-551bc7408906',
            error_type=None,
        )
        self.to_delete_file.system_annotations["to_delete"] = True

        with self.g.session_scope():
            aliquot_id = '84df0f82-69c4-4cd3-a4bd-f40d2d6ef916'
            aliquot = self.g.nodes(md.Aliquot).ids(aliquot_id).one()
            aliquot.files.append(self.to_delete_file)
            aliquot.files.append(self.live_file)
            aliquot.files.append(self.non_live_file)

        self.file_ids = [
            self.to_delete_file.node_id,
            self.non_live_file.node_id,
            self.live_file.node_id,
            self.non_index_file.node_id,
            self.index_file.node_id,
        ]

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
