import json
import subprocess
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).parents[1]
DATA_DIR = PROJECT_DIR / 'test_tilediiif/data'


@pytest.fixture
def expected_info_json():
    with open(DATA_DIR / 'MS-ADD-00269-000-01075.info.json') as f:
        return json.load(f)


def test_infojson_generates_expected_output(expected_info_json):
    result = subprocess.run([
        'infojson', 'from-dzi',
        DATA_DIR / 'MS-ADD-00269-000-01075.dzi'],
        capture_output=True, encoding='utf-8')

    assert result.returncode == 0
    assert json.loads(result.stdout) == expected_info_json
    assert result.stderr == ''


@pytest.mark.parametrize('indent', [1, 2, 4])
def test_indent(indent):
    result = subprocess.run([
        'infojson', 'from-dzi', '--indent', str(indent),
        DATA_DIR / 'MS-ADD-00269-000-01075.dzi'],
        capture_output=True, encoding='utf-8')

    expected = '{\n' + ' ' * indent + '"'
    assert result.stdout.startswith(expected)
    assert result.stdout.endswith('}\n')


def test_indent_0_disables_indentation():
    result = subprocess.run([
        'infojson', 'from-dzi', '--indent', '0',
        DATA_DIR / 'MS-ADD-00269-000-01075.dzi'],
        capture_output=True, encoding='utf-8')

    assert result.stdout.startswith('{"')
    assert result.stdout.endswith('}')
