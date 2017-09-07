import requests
import yaml
import argparse
import os

root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, 'config.yml'), 'r').read())


def parse_args():
    """Parses arguments"""

    parser = argparse.ArgumentParser(description='Delegate Esbuild jobs '
                                     'to workers using depot server')
    depot_args = parser.add_argument_group(title='Depot server arguments',
                                           description='Depot server address '
                                           'and queue_id to listen to')
    depot_args.add_argument('--host',
                            help='Depot server host',
                            required=True)
    depot_args.add_argument('--port',
                            type=int,
                            help='Depot server port',
                            required=True)
    depot_args.add_argument('--queue-id', type=int,
                            help='Depot queue id',
                            required=True)

    es_args = parser.add_argument_group(title='Esbuild arguments',
                                        description='Esbuild related settings')

    es_args.add_argument('--index',
                         help='Name of elasticsearch index to upsert data into')
    es_args.add_argument('--n-workers',
                         help='Number of workers to split esbuild between',
                         type=int)
    es_args.add_argument('--build-type', choices=['active', 'legacy'],
                         help='Choose "active" or "legacy"',
                         )
    es_args.add_argument('--split-by-program', action='store_true',
                         help='If set, splits all projects into groups by program',
                         default=False,
                         )

    # Optional
    misc_args = parser.add_argument_group(title='Other Depot arguments',
                                          description='Depot queue controls')
    misc_args.add_argument('--queue-status',
                           help='Checks esbuild queue status',
                           action='store_true',
                           default=False)
    misc_args.add_argument('--queue-clear',
                           help='Clears esbuild queue', action='store_true',
                           default=False)

    args = parser.parse_args()
    if not any([args.queue_status, args.queue_clear]):
        if not all([args.index, args.n_workers, args.build_type]):
            raise Exception('Provide esbuild arguments to delegate jobs.\n'
                            'Run `python master.py -h` for more info')
    return args


def depot_call(action, host, port, queue_id, json=None):
    """Calls depot api"""

    url = 'http://{}:{}/v0/{}/{}'.format(host, port, action, queue_id)

    method = 'put'
    if action == 'status':
        method = 'get'

    return getattr(requests, method)(url, json=json)


def split_projects(mylist, n, split_by_program=False):
    """Splits list of projects into n parts"""

    # Check input
    if not isinstance(n, int) or n < 1:
        raise ValueError('Number of parts should be positive integer. Got: {}'.format(n))
    if n > len(mylist):
        raise ValueError('Can not split list to {} > len(list) parts'.format(n))

    # Split-by-program mode
    if split_by_program:
        programs = set([p.split('-', 1)[0] for p in mylist])
        if n != len(programs):
            raise Exception("Number of workers should equal number of programs ({})"
                            .format(len(programs)))
        result = []
        for program in programs:
            result.append([x for x in mylist if x.split('-', 1)[0] == program])
        return result
    # Regular mode
    else:
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

    # Get queue status:
    status = depot_call('status', args.host, args.port, args.queue_id)

    if args.queue_clear:
        print depot_call('clear', args.host, args.port, args.queue_id).text

    elif args.queue_status:
        print status.text

    else:
        projects = config['{}_projects'.format(args.build_type)]
        print ("\n\n\tDelegating {} build with {} workers\n\tES index: {}"
               .format(args.build_type.upper(), args.n_workers, args.index))

        if 'not found' in status.text:
            print "Creating new queue:"
            print depot_call('new', args.host, args.port, args.queue_id).text

        # Delegate a job for each project group:
        for group in split_projects(projects, args.n_workers,
                                    split_by_program=args.split_by_program):
            cmd = ('sudo /var/tungsten/services/esbuild/es_build_{}_wrapper'
                   ' --upsert-to {} --no-roll'.format(args.build_type,
                                                      args.index))
            if args.n_workers > 1:
                cmd = cmd + ' --projects {}'.format(' '.join(group))

            depot_call('delegate', args.host, args.port, args.queue_id,
                       json={'command': cmd})
