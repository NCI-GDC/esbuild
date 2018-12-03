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


@pytest.mark.parametrize('path,args', [
    ('es_build.py', ['--index-type', 'active', '--index-name', 'test_active']),
    ('es_build.py', ['--index-type', 'legacy', '--index-name', 'test_legacy']),
    ('build_download_stats_index.py', []),
])
def test_script_runs(environment, path, args, init_indexd):
    os.environ['INDEXD_HOST'] = init_indexd.url
    os.environ['INDEXD_USER'], os.environ['INDEXD_PASS'] = init_indexd.auth

    cmd_list = ['python', os.path.join(BIN_DIR, path)]
    cmd_list.extend(args)
    check_call(cmd_list)
