from functools import lru_cache
from pathlib import Path


# assumption: dirs we create are not removed during our runtime, hence
# memoisation is safe.
@lru_cache()
def ensure_dir_exists(path: Path):
    path.mkdir(exist_ok=True)


def ensure_sub_directories_exist(base_dir: Path, sub_path: Path):
    """
    Given a base directory and a relative path, ensure that all directory path
    components in the sub path exist as directories under the base directory,
    creating absent directories as required.

    :param base_dir: Path to an existing directory
    :param sub_path: Relative path to a file
    :return: The full {base_dir}/{sub_path} path.
    """
    for dir in reversed(list(sub_path.parents)[:-1]):
        ensure_dir_exists(base_dir / dir)

    return base_dir / sub_path


def validate_relative_path(path: Path, prefix='path', exc_cls=ValueError):
    if not path.parts:
        raise exc_cls(f'{prefix} is empty')
    if '..' in path.parts:
        raise exc_cls(f'{prefix} contains a ".." (parent) segment: {path}')
    if path.is_absolute():
        raise exc_cls(f'{prefix} is not relative: {path}')
    return True
