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


@pytest.mark.parametrize('path', [
    'build_legacy_graph_index.py',
    'build_active_graph_index.py',
    'build_download_stats_index.py',
])
def test_script_runs(environment, path):
    check_call(['python', os.path.join(BIN_DIR, path)])
