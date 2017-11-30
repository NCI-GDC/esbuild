import requests
import argparse
import time
import yaml
import os

root_dir = os.path.dirname(os.path.abspath(__file__))
config = yaml.safe_load(open(os.path.join(root_dir, 'config.yml'), 'r').read())

TIMEDELTA = config['timedelta']


def parse_args():
    """Parses arguments"""

    parser = argparse.ArgumentParser(description='Queries depot for esbuild jobs')
    parser.add_argument('--host',
                        help='Depot server host',
                        required=True)
    parser.add_argument('--port',
                        type=int,
                        help='Depot server port',
                        required=True)
    parser.add_argument('--queue-id', type=str,
                        help='Depot queue id to listen to. Has to be UUID string',
                        required=True)

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    while True:
        work = requests.get('http://{}:{}/v0/work/{}'
                            .format(args.host, args.port, args.queue_id))
        try:
            work = work.json()
        except:
            work = {'error': work.text}

        if 'command' in work:
            print '-> Running {}'.format(work['command'])
            os.system(work['command'])
        else:
            print work

        time.sleep(TIMEDELTA)
