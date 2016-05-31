# -*- coding: utf-8 -*-
"""
esbuild.export.elasticdump
----------------------------------

Export elasticsearch indices to file using elasticdump.

The nodejs ``elasticdump`` util must be install for this to work and
can be installed via

.. code-block:: bash
   :linenos:

    sudo apt-get install npm
    sudo ln -s `which nodejs` /usr/bin/node
    npm install -g elasticdump

"""

from subprocess import PIPE, Popen
import gzip

CHUNK_SIZE = 1026


class ExportTypes(object):
    DATA = 'data'
    MAPPING = 'mapping'
    ANALYZER = 'analyzer'

    ALL = [DATA, MAPPING, ANALYZER]


def construct_auth_string(user, password):
    """Create basic auth url string"""

    if user is not None or password is not None:
        return '{user}:{password}@'.format(user=user, password=password)
    else:
        return ''


def construct_es_target(index, host, port=9200, protocol='http', auth=''):
    """Construct url for ES input or output"""

    return '{protocol}://{auth}{host}:{port}/{index}'.format(
        auth=auth,
        protocol=protocol,
        host=host,
        port=port,
        index=index,
    )


def export_to_stdout(type_, index, host, **kwargs):
    """Starts an export with stdout, stderr piped"""

    user = kwargs.pop('user', None)
    password = kwargs.pop('password', None)
    auth = construct_auth_string(user, password)

    return Popen([
        'elasticdump',
        '--input', construct_es_target(index, host, auth=auth, **kwargs),
        '--output', '$',
        '--type', type_,
    ], stdout=PIPE, stderr=PIPE)


def raise_for_error(proc):
    """Raises a RuntimeError if :param:`proc` did not exit successfully"""

    proc.poll()
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.read())


def export_to_gzip(path, type_, index, host, **kwargs):
    """Export ES index to local file"""

    export = export_to_stdout(type_, index, host, **kwargs)
    output = gzip.open(path, 'wb')
    output.writelines(export.stdout)
    export.wait()
    output.close()
    raise_for_error(export)
