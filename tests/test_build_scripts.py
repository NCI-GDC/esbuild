# -*- coding: utf-8 -*-
"""
test_build_scripts.py
----------------------------------

Test the build scripts that wrap core functionality

"""

from subprocess import check_call
from unittest import TestCase

import os

from base import (
    PG_HOST,
    PG_USER,
    PG_PASSWORD,
    PG_DATABASE,
    TEST_DIR,
)

BIN_DIR = os.path.join(os.path.dirname(TEST_DIR), 'bin')

os.environ['ELASTICSEARCH_HOST'] = 'localhost'
os.environ['ES_USER'] = ''
os.environ['ES_PASSWORD'] = ''

os.environ['PG_HOST'] = PG_HOST
os.environ['PG_USER'] = PG_USER
os.environ['PG_PASS'] = PG_PASSWORD
os.environ['PG_NAME'] = PG_DATABASE


class TestLegacyBuildScript(TestCase):

    def test_script_runs(self):
        check_call([
            'python',
            os.path.join(BIN_DIR, 'build_legacy_graph_index.py')
        ])


class TestActiveBuildScript(TestCase):

    def test_script_runs(self):
        check_call([
            'python',
            os.path.join(BIN_DIR, 'build_active_graph_index.py')
        ])


class TestDownloadReportBuildScript(TestCase):

    def test_script_runs(self):
        check_call([
            'python',
            os.path.join(BIN_DIR, 'build_download_stats_index.py')
        ])
