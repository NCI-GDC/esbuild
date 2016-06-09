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

import argparse
import gzip
import os
import time


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


def add_es_args(parser):
    parser.add_argument('--es-host',
                        required=True,
                        help='Elasticsearch source host')
    parser.add_argument('--es-index',
                        required=True,
                        help='Elasticsearch source host')
    parser.add_argument('--es-port',
                        default=9200,
                        help='Elasticsearch source port')
    parser.add_argument('--es-user',
                        help='Basic Auth user for ES (if applicable)')
    parser.add_argument('--es-pass',
                        help='Basic Auth password for ES (if applicable)')

    return parser



def export_to_file(arg_list=None):
    """takes argument list or reads from command line. export index file.

    """

    parser = add_es_args(argparse.ArgumentParser())

    parser.add_argument('--working-directory',
                        required=True,
                        help='Where to store local export files while working')
    parser.add_argument('--leave-files',
                        action='store_false',
                        help='Leave local export files when finished')

    args = parser.parse_args(arg_list)
    base_dir = os.path.expanduser(args.working_directory)

    timestamp = int(time.time())

    for type_ in ExportTypes.ALL:

        name = '{}.{}_{}.gz'.format(args.es_index, type_, timestamp)
        path = os.path.join(base_dir, name)

        export_to_gzip(
            path,
            type_,
            args.es_index,
            args.es_host,
            port=args.es_port,
            user=args.es_user,
            password=args.es_pass)
