import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from tilediiif.tools.infojson import DEFAULT_ID_BASE_URL

PROJECT_DIR = Path(__file__).parents[1]
DATA_DIR = PROJECT_DIR / "tests/data"
ID_BASE_URL = "https://images.cudl.lib.cam.ac.uk/iiif/"
ID_URL = "https://images.cudl.lib.cam.ac.uk/iiif/MS-ADD-00269-000-01075"


@pytest.fixture
def tmp_data_path(tmp_path):
    with TemporaryDirectory(dir=tmp_path) as path:
        yield Path(path)


@pytest.fixture
def info_json(info_json_path):
    with open(info_json_path) as f:
        return json.load(f)


@pytest.mark.parametrize(
    "argv, message",
    [
        [[], "Usage:\n    infojson from-dzi "],
        [
            ["from-dzi", "-"],
            "Error: no --id is specified so --id is derived from <dzi-file>, but DZI "
            "is read from stdin; nothing to generate @id attribute from",
        ],
        [
            ["from-dzi", "/tmp/img?a=1.dzi"],
            "Error: identifier is not a relative URL path: 'img?a=1'",
        ],
        [
            ["from-dzi", "--id", "img?a=1", "/tmp/img.dzi"],
            "Error: identifier is not a relative URL path: 'img?a=1'",
        ],
        [
            ["from-dzi", "--id", "", "/tmp/img.dzi"],
            "Error: identifier is not a relative URL path: ''",
        ],
        [
            ["from-dzi", "--id-base-url", "foo.com/", "/tmp/img.dzi"],
            "Error: invalid --id-base-url 'foo.com/': url is not absolute",
        ],
    ],
)
def test_infojson_fails_with_invalid_arguments(argv, message):
    result = subprocess.run(["infojson"] + argv, capture_output=True, encoding="utf-8")
    assert result.returncode == 1
    assert result.stdout == ""
    assert message in result.stderr


@pytest.mark.parametrize(
    "dzi_path, info_json_path",
    [
        [
            DATA_DIR / "MS-ADD-00269-000-01075.dzi",
            DATA_DIR / "MS-ADD-00269-000-01075.info.json",
        ],
        [
            DATA_DIR / "MS-ADD-00269-000-01075_with-png-format.dzi",
            DATA_DIR / "MS-ADD-00269-000-01075_with-png-format.info.json",
        ],
    ],
)
def test_infojson_generates_expected_output_on_stdout(dzi_path, info_json):
    result = subprocess.run(
        [
            "infojson",
            "from-dzi",
            "--stdout",
            "--id-base-url",
            ID_BASE_URL,
            "--id",
            "MS-ADD-00269-000-01075",
            dzi_path,
        ],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )

    assert result.returncode == 0
    assert json.loads(result.stdout) == info_json
    assert result.stderr == ""


@pytest.mark.parametrize("chdir", [True, False])
@pytest.mark.parametrize(
    "options, dzi_path, expected_content, expected_path, expected_id_attr",
    [
        [
            ["--id-base-url", ID_BASE_URL],
            DATA_DIR / "MS-ADD-00269-000-01075.dzi",
            DATA_DIR / "MS-ADD-00269-000-01075.info.json",
            "MS-ADD-00269-000-01075/info.json",
            f"{ID_BASE_URL}MS-ADD-00269-000-01075",
        ],
        [
            ["--id-base-url", ID_BASE_URL],
            DATA_DIR / "MS-ADD-00269-000-01075.dzi",
            DATA_DIR / "MS-ADD-00269-000-01075.info.json",
            "MS-ADD-00269-000-01075/info.json",
            f"{ID_BASE_URL}MS-ADD-00269-000-01075",
        ],
        [
            [],
            DATA_DIR / "MS-ADD-00269-000-01075_with-png-format.dzi",
            DATA_DIR / "MS-ADD-00269-000-01075_with-png-format.info.json",
            "MS-ADD-00269-000-01075_with-png-format/info.json",
            f"{DEFAULT_ID_BASE_URL}MS-ADD-00269-000-01075_with-png-format",
        ],
        [
            [
                "--id",
                "foo",
                "--path-template",
                "some-dir/{identifier-shard}/{identifier}_info.json",
            ],
            DATA_DIR / "MS-ADD-00269-000-01075.dzi",
            DATA_DIR / "MS-ADD-00269-000-01075.info.json",
            "some-dir/b1/71/foo_info.json",
            f"{DEFAULT_ID_BASE_URL}foo",
        ],
        [
            [
                "--id",
                "foo",
                "--path-template",
                "some-dir/{identifier-shard}/{identifier}_info.json",
                "--id-base-url",
                "https://example/",
            ],
            DATA_DIR / "MS-ADD-00269-000-01075.dzi",
            DATA_DIR / "MS-ADD-00269-000-01075.info.json",
            "some-dir/b1/71/foo_info.json",
            f"https://example/foo",
        ],
    ],
)
def test_infojson_writes_expected_output_file(
    chdir,
    dzi_path,
    options,
    expected_content,
    expected_path,
    expected_id_attr,
    tmp_data_path,
    monkeypatch,
):
    if chdir:
        monkeypatch.chdir(tmp_data_path)
    else:
        options += ["--data-path", tmp_data_path]

    result = subprocess.run(
        ["infojson", "from-dzi"] + options + [dzi_path],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )

    assert result.stdout == ""
    assert result.stderr == ""

    info_json_path: Path = tmp_data_path / expected_path
    expected_meta = json.loads(expected_content.read_text())
    if expected_id_attr is not None:
        expected_meta["@id"] = expected_id_attr

    assert json.loads(info_json_path.read_text()) == expected_meta


@pytest.mark.parametrize("indent", [1, 2, 4])
def test_indent(indent):
    result = subprocess.run(
        [
            "infojson",
            "from-dzi",
            "--stdout",
            "--indent",
            str(indent),
            DATA_DIR / "MS-ADD-00269-000-01075.dzi",
        ],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )

    expected = "{\n" + " " * indent + '"'
    assert result.stdout.startswith(expected)
    assert result.stdout.endswith("}\n")


def test_indent_0_disables_indentation():
    result = subprocess.run(
        [
            "infojson",
            "from-dzi",
            "--stdout",
            "--indent",
            "0",
            DATA_DIR / "MS-ADD-00269-000-01075.dzi",
        ],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )

    assert result.stdout.startswith('{"')
    assert result.stdout.endswith("}")
