from pathlib import Path
from unittest.mock import call, MagicMock, patch

import pytest

from tilediiif.filesystem import (
    ensure_dir_exists, ensure_sub_directories_exist, validate_relative_path)


def test_ensure_dir_exists_creates_same_dir_once_with_multiple_calls():
    mock_path = MagicMock()
    ensure_dir_exists(mock_path)
    ensure_dir_exists(mock_path)
    mock_path.mkdir.assert_called_once_with(exist_ok=True)


@pytest.yield_fixture()
def mock_ensure_dir_exists():
    with patch('tilediiif.filesystem.ensure_dir_exists') as mock:
        yield mock


@pytest.fixture
def expected_ensure_dir_paths(base_path, expected_sub_dirs):
    return [base_path / sub for sub in expected_sub_dirs]


@pytest.mark.parametrize('base_path', [
    Path('/'), Path('relative/base'), Path('/abs/base')
])
@pytest.mark.parametrize('sub_path, expected_sub_dirs', [
    [Path(''), []],
    [Path('foo'), []],
    [Path('foo/bar'), ['foo']],
    [Path('foo/bar/baz'), ['foo', 'foo/bar']],
])
def test_ensure_sub_directories_exist(
        base_path, sub_path, expected_ensure_dir_paths,
        mock_ensure_dir_exists):

    result = ensure_sub_directories_exist(base_path, sub_path)
    assert result == base_path / sub_path

    assert mock_ensure_dir_exists.mock_calls == [
        call(sub) for sub in expected_ensure_dir_paths]


@pytest.mark.parametrize('invalid_path, exc_cls, prefix, msg', [
    ['abc/../foo', None, None,
     'path contains a ".." (parent) segment: abc/../foo'],
    ['abc/../foo', AssertionError, 'get_foo() returned a path which',
     'get_foo() returned a path which contains a ".." (parent) segment: '
     'abc/../foo'],
    ['/abc', None, None, 'path is not relative: /abc'],
    ['/abc', AssertionError, 'get_foo() returned a path which',
     'get_foo() returned a path which is not relative: /abc'],
    ['', None, None, 'path is empty'],
    ['', AssertionError, 'get_foo() returned a path which',
     'get_foo() returned a path which is empty'],
])
def test_validate_relative_path_rejects_invalid_paths(
        invalid_path, exc_cls, prefix, msg):
    kwargs = {k: v for k, v in dict(prefix=prefix, exc_cls=exc_cls).items()
              if v is not None}
    with pytest.raises(exc_cls or ValueError) as exc_info:
        validate_relative_path(Path(invalid_path), **kwargs)

    assert str(exc_info.value) == msg


@pytest.mark.parametrize('valid_path', ['foo', 'foo/bar'])
def test_validate_relative_path_accepts_valid_paths(valid_path):
    assert validate_relative_path(Path(valid_path)) is True
