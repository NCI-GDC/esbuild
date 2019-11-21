# -*- coding: utf-8 -*-
"""
test_build_scripts.py
----------------------------------

Test the build scripts that wrap core functionality

"""

from subprocess import check_call
from tests.conftest import BIN_DIR

import pytest
import os


@pytest.mark.parametrize('path', [
    'build_download_stats_index.py',
])
def test_script_runs(environment, path, init_indexd):
    os.environ['INDEXD_HOST'] = init_indexd.url
    os.environ['INDEXD_USER'], os.environ['INDEXD_PASS'] = init_indexd.auth
    check_call(['python', os.path.join(BIN_DIR, path)])
