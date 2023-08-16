from typing import Iterable, Iterator


def get_dict_paths(dictionary: dict, path: str = "root") -> Iterator[str]:
    """
    Flattens all entries in a dictionary and its nested dictionaries into a path.

    NOTE: items in any list value will generate a path for each value.

    Args:
        dictionary: The dict to be flattened.
        path: The current path to the given dictionary.

    Returns:
        An iterator of all the final paths.
    """
    for key, value in dictionary.items():
        subpath = f"{path}.{key}"

        if isinstance(value, dict):
            yield from get_dict_paths(value, subpath)
        elif isinstance(value, str):
            yield f"{subpath}.{value}"
        elif isinstance(value, Iterable):
            yield from (f"{subpath}.{e}" for e in value)
