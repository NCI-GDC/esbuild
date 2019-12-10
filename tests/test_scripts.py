# -*- coding: utf-8 -*-
"""
test_scripts.py
----------------------------------

Test the build scripts that wrap core functionality

"""

from subprocess import getstatusoutput

import pytest


@pytest.mark.parametrize('path', [
    'build_download_stats_index.py',
])
def test_script_runs(path, init_indexd, pg_driver):
    status, out = getstatusoutput(path)
    assert status == 0, out


@pytest.mark.parametrize('posargs', [
    ['-h'],
    ['reindex', '-h'],
    ['pre-flight', '-h'],
])
def test_esbuild_cli(init_indexd, pg_driver, posargs):
    cmd = ' '.join(['esbuild-cli'] + posargs)
    status, out = getstatusoutput(cmd)
    assert status == 0, out
