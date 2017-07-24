import requests
import yaml
import argparse
import os

root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, 'config.yml'), 'r').read())


def parse_args():
    """Parses arguments"""

    parser = argparse.ArgumentParser(description='Delegate Esbuild jobs')
    parser.add_argument('--host',
                        help='Depot server host',
                        required=True)
    parser.add_argument('--port',
                        type=int,
                        help='Depot server port',
                        required=True)
    parser.add_argument('--index',
                        help='Name of elasticsearch index to upsert data into',
                        required=True)
    parser.add_argument('--n-workers',
                        help='Number of workers to split esbuild between',
                        required=True, type=int)
    parser.add_argument('--queue-id', type=int,
                        help='Depot queue id to listen to',
                        required=True)

    # Optional
    parser.add_argument('--queue-status',
                        help='Checks esbuild queue status', action='store_true',
                        default=False)
    parser.add_argument('--queue-clear',
                        help='Clears esbuild queue', action='store_true',
                        default=False)
    parser.add_argument('--skip-legacy',
                        help='If set, will not build legacy', action='store_true',
                        default=False)

    return parser.parse_args()


def depot_call(action, host, port, queue_id, json=None):
    """Calls depot api"""

    url = 'http://{}:{}/v0/{}/{}'.format(host, port, action, queue_id)

    method = 'put'
    if action == 'status':
        method = 'get'

    return getattr(requests, method)(url, json=json)


def list_split(mylist, n):
    """ Splits list into n parts"""
    group_lengths = [1 for _ in range(n)]
    i = 0
    while sum(group_lengths) != len(mylist):
        group_lengths[i] += 1
        i += 1
        if i == len(group_lengths):
            i = 0

    result = []
    i = 0
    for length in group_lengths:
        result.append(mylist[i:i+length])
        i = i + length
    return result


if __name__ == "__main__":
    args = parse_args()

    projects = config['projects']

    # Get queue status:
    status = depot_call('status', args.host, args.port, args.queue_id)

    if args.queue_clear:
        print depot_call('clear', args.host, args.port, args.queue_id).text

    if args.queue_status:
        print status.text

    if not (args.queue_clear or args.queue_status):
        if 'not found' in status.text:
            print "Creating new queue:"
            print depot_call('new', args.host, args.port, args.queue_id).text

        # Delegate a job for each project group:
        for group in list_split(projects, args.n_workers):
            cmd = ('sudo /var/tungsten/services/esbuild/es_build_active_wrapper'
                   ' --upsert-to {} --no-roll'.format(args.index))
            if args.n_workers > 1:
                cmd = cmd + ' --projects {}'.format(' '.join(group))

            depot_call('delegate', args.host, args.port, args.queue_id,
                       json={'command': cmd})

        if not args.skip_legacy:
            cmd = 'sudo /var/tungsten/services/esbuild/es_build_legacy_wrapper'
            depot_call('delegate', args.host, args.port, args.queue_id,
                       json={'command': cmd})
