# -*- coding: utf-8 -*-
"""
test_scripts.py
----------------------------------

Test the build scripts that wrap core functionality

"""

from subprocess import check_call

import pytest


@pytest.mark.parametrize('path', [
    'build_download_stats_index.py',
])
def test_script_runs(path, init_indexd, pg_driver):
    check_call([path])


@pytest.mark.parametrize('posargs', [
    ['-h'],
    ['reindex', '-h'],
    ['pre-flight', '-h'],
])
def test_esbuild_cli(init_indexd, pg_driver, posargs):
    cmd = ['esbuild-cli'] + posargs
    check_call(cmd)
