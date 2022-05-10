import os
from argparse import ArgumentParser

import yaml
from cdislogging import get_logger
from gdcdatamodel.models import Program, Project
from psqlgraph import PsqlGraphDriver


def parse_cmd_args():
    default_state_filename = "project-program-release.yaml"
    parser = ArgumentParser()
    parser.add_argument(
        "which_data",
        help="Which es instance we're setting states for",
        choices=["ACTIVE", "LEGACY"],
    )
    parser.add_argument(
        "--state_file",
        help=f"File to load states from (default {default_state_filename}",
        default=default_state_filename,
    )
    parser.add_argument(
        "--dry_run",
        help="just run code, don't make any permanent changes",
        action="store_true",
    )

    args = parser.parse_args()

    return args


if __name__ == "__main__":

    args = parse_cmd_args()
    log = get_logger("esbuild-set_project_released_states")
    # load yaml
    with open(args.state_file) as yaml_file:
        state_conf = yaml.safe_load(yaml_file)

    pg = PsqlGraphDriver(
        os.environ["PG_HOST"],
        os.environ["PG_USER"],
        os.environ["PG_PASS"],
        os.environ["PG_NAME"],
    )

    current_data = state_conf[args.which_data]

    updated_states = 0
    with pg.session_scope() as session:
        for program, data in current_data["PROGRAMS"].iteritems():
            log.info(f"Looking for {program}")
            prog = pg.nodes(Program).props(name=program).scalar()
            if prog:
                project_list = []
                project_names = []
                if data["PROJECTS"] != "*":
                    for entry in [
                        proj for proj in prog.projects if proj.code in data["PROJECTS"]
                    ]:
                        project_list.append(entry)
                        project_names.append(entry.code)
                    if len(data["PROJECTS"]) != len(project_list):
                        for entry in data["PROJECTS"]:
                            if entry not in project_names:
                                log.warning(f"{entry} not found")

                else:
                    project_list = prog.projects

                log.info(f"{len(project_list)} programs found")
                for proj in project_list:
                    if proj.props["released"] != data["RELEASED"]:
                        log.info(
                            "Changing released for {}-{} to {}".format(
                                program, proj.props["code"], data["RELEASED"]
                            )
                        )
                        proj.props["released"] = data["RELEASED"]
                        session.merge(proj)
                        updated_states += 1
                    else:
                        log.info(
                            "{}-{} released is ok as {}".format(
                                program, proj.props["code"], proj.props["released"]
                            )
                        )
            else:
                log.info(f"Unable to find {program}")

        if args.dry_run:
            session.rollback()

    log.info(f"Updated {updated_states} states")
