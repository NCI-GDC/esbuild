# -*- coding: utf-8 -*-
"""
test_scripts.py
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
def test_script_runs(path, init_indexd, pg_driver):
    check_call(['python', os.path.join(BIN_DIR, path)])


@pytest.mark.parametrize('posargs', [
    ('-h',),
    ('reindex', '-h'),
    ('pre-flight', '-h'),
])
def test_esbuild_cli(init_indexd, pg_driver, posargs):
    call_args = ['esbuild-cli']
    call_args.extend(posargs)
    check_call(call_args)
