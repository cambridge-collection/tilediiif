from pathlib import Path

import toml

from tilediiif.tools import __version__ as module_version
from tilediiif.tools.version import __version__ as internal_version


def test_module_exports_internal_version():
    assert module_version == internal_version


def test_version_is_in_sync():
    with open(Path(__file__).parents[1] / "pyproject.toml") as f:
        pyproject = toml.load(f)
    assert type(module_version) == str
    assert len(module_version) > 0
    assert module_version == pyproject["tool"]["poetry"]["version"]
