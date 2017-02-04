import os
import sys
import yaml
from cdisutils.log import get_logger
from psqlgraph import PsqlGraphDriver
from gdcdatamodel.models import Project, Program
from argparse import ArgumentParser

def parse_cmd_args():
    default_state_filename = 'project-program-release.yaml'
    parser = ArgumentParser()
    parser.add_argument('which_data',
        help='Which data we\'re setting data for',
        choices=['ACTIVE', 'LEGACY']
    )
    parser.add_argument('--state_file', 
        help='File to load states from (default {}'.format(default_state_filename),
        default=default_state_filename
    )
    parser.add_argument('--dry_run',
        help='run code, don\'t make any permanent changes',
        action='store_true'
    )

    args = parser.parse_args()
    
    return args

args = parse_cmd_args()
log = get_logger('esbuild-set_project_released_states')
# load yaml
with open(args.state_file, 'r') as yaml_file:
    state_conf = yaml.load(yaml_file)

pg = PsqlGraphDriver(
    os.environ["PG_HOST"],
    os.environ["PG_USER"],
    os.environ["PG_PASS"],
    os.environ["PG_NAME"],
)

current_data = state_conf[args.which_data]

updated_states = 0
with pg.session_scope() as session:
    for program, data in current_data['PROGRAMS'].iteritems():
        log.info('Looking for {}'.format(program))
        prog = pg.nodes(Program).props(name=program).scalar()
        if prog:
            project_list = []
            if data['PROJECTS'] != '*':
                for entry in data['PROJECTS']:
                    proj = pg.nodes(Project).props(code=entry).scalar()
                    if proj:
                        project_list.append(proj)
                    else:
                        log.warn('Unable to find project {}'.filter(entry))
            else:
                project_list = prog.projects
            
            log.info('{} programs found'.format(len(project_list)))
            for proj in project_list:
                if proj.props['released'] != data['RELEASED']:
                    log.info('Changing released for {}-{} to {}'.format(
                        program,
                        proj.props['code'],
                        data['RELEASED']
                    ))
                    proj.props['released'] = data['RELEASED']
                    session.merge(proj)
                    updated_states += 1
                else:
                    log.info('{}-{} released is ok as {}'.format(
                        program,
                        proj.props['code'],
                        proj.props['released']
                    ))
        else:
            log.info('Unable to find {}'.filter(program))

log.info('Updated {} states'.format(updated_states))
