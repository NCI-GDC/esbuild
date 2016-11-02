# -*- coding: utf-8 -*-
"""
test_build_scripts.py
----------------------------------

Test the build scripts that wrap core functionality

"""

from subprocess import check_call
from conftest import BIN_DIR

import pytest
import os


@pytest.mark.parametrize('path,test,graph_type', [
    ('gdc_datarelease.py', '--test', ''),
    ('gdc_datarelease.py', '--test', '--legacy'),
    ('build_download_stats_index.py', '', ''),
])
def test_script_runs(environment, path, test, graph_type):
    # build_download_stats_index doesn't take any args, but it also doesn't import argparse
    # argparse complains if you give it unnecessary args
    if graph_type:
        check_call(['python', os.path.join(BIN_DIR, path), test, graph_type])
    else:
        check_call(['python', os.path.join(BIN_DIR, path), test])
