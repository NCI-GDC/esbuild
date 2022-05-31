def get_dict_paths(d, path_list=None, path="root"):
    """
    Returns list of all paths in a dict and a last path found
    """
    if path_list is None:
        path_list = []

    for k, v in d.items():
        subpath = path + "." + k
        if isinstance(v, dict):
            sublist, subpath = get_dict_paths(v, path_list, subpath)
        else:
            if isinstance(v, list):
                sublist = [path + "." + k + "." + str(e) for e in v]
            else:
                sublist = [path + "." + k + "." + str(v)]
        path_list.extend(sublist)
    return list(set(path_list)), path
