import requests


def depot_call(action, args, json=None):
    """
    Calls depot api
    """

    url = 'http://{}:{}/v0/{}/{}'.format(
        args.depot_host, args.depot_port, action, args.queue_id
    )

    method = 'put'
    if action == 'status':
        method = 'get'

    return getattr(requests, method)(url, json=json)


def user_confirm(prompt_string, logger):
    """
    Prompt user confirmation to proceed
    """
    while True:
        logger.info(prompt_string)
        ans = raw_input().lower()
        if ans in ['y', 'yes']:
            return
        elif ans in ['n', 'no']:
            raise Exception('User refused to continue')
        else:
            logger.error('Invalid answer: {}'.format(ans))


def split_projects(project_list, n, split_by_program=False, split_by_project=False):
    """
    Splits project list into n parts
    """

    if n == 1:
        return [project_list]

    if split_by_project:
        return [[p] for p in project_list]

    # Check input
    if not isinstance(n, int) or n < 1:
        raise ValueError('Number of parts should be positive integer. Got: {}'.format(n))
    if n > len(project_list):
        raise ValueError('Can not split list to {} > len(list) parts'.format(n))

    def get_program(project_id):
        return project_id.split('-', 1)[0]

    # Split-by-program mode
    if split_by_program:
        programs = set([get_program(p) for p in project_list])
        project_groups = []
        for program in programs:
            project_groups.append([x for x in project_list if get_program(x) == program])
        return project_groups

    # Regular mode
    else:
        group_lengths = [1 for _ in range(n)]
        i = 0
        while sum(group_lengths) != len(project_list):
            group_lengths[i] += 1
            i += 1
            if i == len(group_lengths):
                i = 0

        project_groups = []
        i = 0
        for length in group_lengths:
            project_groups.append(project_list[i:i+length])
            i = i + length
        return project_groups
