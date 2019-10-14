import json
import subprocess
from pathlib import Path

import pytest

PROJECT_DIR = Path(__file__).parents[1]
DATA_DIR = PROJECT_DIR / 'test_tilediiif/data'
ID_URL = 'https://images.cudl.lib.cam.ac.uk/iiif/MS-ADD-00269-000-01075'


@pytest.fixture
def info_json(info_json_path):
    with open(info_json_path) as f:
        return json.load(f)


@pytest.mark.parametrize('dzi_path, info_json_path', [
    [DATA_DIR / 'MS-ADD-00269-000-01075.dzi',
     DATA_DIR / 'MS-ADD-00269-000-01075.info.json'],
    [DATA_DIR / 'MS-ADD-00269-000-01075_with-png-format.dzi',
     DATA_DIR / 'MS-ADD-00269-000-01075_with-png-format.info.json'],
])
def test_infojson_generates_expected_output(dzi_path, info_json):
    result = subprocess.run([
        'infojson', 'from-dzi', '--id', ID_URL, dzi_path],
        capture_output=True, encoding='utf-8')

    assert result.returncode == 0
    assert json.loads(result.stdout) == info_json
    assert result.stderr == ''


@pytest.mark.parametrize('indent', [1, 2, 4])
def test_indent(indent):
    result = subprocess.run([
        'infojson', 'from-dzi', '--indent', str(indent), '--id', ID_URL,
        DATA_DIR / 'MS-ADD-00269-000-01075.dzi'],
        capture_output=True, encoding='utf-8')

    expected = '{\n' + ' ' * indent + '"'
    assert result.stdout.startswith(expected)
    assert result.stdout.endswith('}\n')


def test_indent_0_disables_indentation():
    result = subprocess.run([
        'infojson', 'from-dzi', '--indent', '0', '--id', ID_URL,
        DATA_DIR / 'MS-ADD-00269-000-01075.dzi'],
        capture_output=True, encoding='utf-8')

    assert result.stdout.startswith('{"')
    assert result.stdout.endswith('}')
