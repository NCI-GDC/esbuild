# -*- coding: utf-8 -*-
"""
esbuild.esutils
----------------------------------

elasticsearchutility functions that were used in more than one place

"""


def raise_for_error(proc):
    """Raises a RuntimeError if :param:`proc` did not exit successfully"""

    proc.poll()
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.read())



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


def add_es_args(parser):
    """Add Elasticsearch arguments to argparse.ArgumentParser"""

    parser.add_argument('--es-host',
                        required=True,
                        help='Elasticsearch source host')
    parser.add_argument('--es-index',
                        required=True,
                        help='Elasticsearch source index')
    parser.add_argument('--es-port',
                        default=9200,
                        help='Elasticsearch source port')
    parser.add_argument('--es-user',
                        default='',
                        help='Basic Auth user for ES (if applicable)')
    parser.add_argument('--es-pass',
                        default='',
                        help='Basic Auth password for ES (if applicable)')

    return parser
