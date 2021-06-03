import contextlib
import json
import math
import shutil
import tempfile
from collections import Counter, abc
from functools import partial
from pathlib import Path, PurePath
from typing import Callable, ContextManager
from unittest.mock import Mock, call, patch

import pytest
from hypothesis import assume, given, settings
from hypothesis.strategies import composite, integers, lists, sampled_from, text
from tests import test_dzi
from tests.test_dzi import dzi_metadata
from tests.test_infojson import image_dimensions

from tilediiif.tools.dzi import get_dzi_tile_path
from tilediiif.tools.infojson import power2_image_pyramid_scale_factors
from tilediiif.tools.tilelayout import (
    DEFAULT_FILE_METHOD,
    DEFAULT_FILE_PATH_TEMPLATE,
    InvalidPath,
    create_dzi_tile_layout,
    create_file_methods,
    create_tile_layout,
    get_layer_tiles,
    get_template_bindings,
    get_templated_dest_path,
    parse_template,
    run,
)

DATA_DIR = Path(__file__).parent / "data"

dzi_ms_add_path = test_dzi.dzi_ms_add_path
dzi_ms_add_meta = test_dzi.dzi_ms_add_meta


ints_over_zero = integers(min_value=1)


@given(
    width=integers(), height=integers(), tile_size=integers(), scale_factor=integers()
)
def test_get_layer_tiles_argument_validation(width, height, tile_size, scale_factor):
    assume(any(n < 1 for n in [width, height, tile_size, scale_factor]))

    with pytest.raises(ValueError):
        next(
            get_layer_tiles(
                width=width,
                height=height,
                tile_size=tile_size,
                scale_factor=scale_factor,
            )
        )


@given(
    width=image_dimensions,
    height=image_dimensions,
    tile_size=ints_over_zero,
    scale_factor=integers(min_value=1, max_value=2 ** 18),
)
def test_get_layer_tiles(width, height, tile_size, scale_factor):
    src_tile_size = tile_size * scale_factor
    has_trailing_x = bool(width % src_tile_size)
    has_trailing_y = bool(height % src_tile_size)
    tiles_x = width // src_tile_size + has_trailing_x
    tiles_y = height // src_tile_size + has_trailing_y

    # Don't bother testing ridiculously huge tile counts
    assume(tiles_x * tiles_y < 10_000)

    tiles = list(
        get_layer_tiles(
            width=width, height=height, tile_size=tile_size, scale_factor=scale_factor
        )
    )

    assert len(tiles) > 0
    assert len(tiles) == tiles_x * tiles_y

    assert set(tile["index"]["x"] for tile in tiles) == set(range(tiles_x))
    assert set(tile["index"]["y"] for tile in tiles) == set(range(tiles_y))

    for tile in tiles:
        assert set(tile.keys()) == {"scale_factor", "index", "src", "dst"}

        assert tile["scale_factor"] == scale_factor

        is_last_x = tile["index"]["x"] == tiles_x - 1
        is_last_y = tile["index"]["y"] == tiles_y - 1

        assert tile["src"]["x"] == tile["index"]["x"] * src_tile_size
        assert tile["src"]["y"] == tile["index"]["y"] * src_tile_size

        assert tile["dst"]["x"] == tile["index"]["x"] * tile_size
        assert tile["dst"]["y"] == tile["index"]["y"] * tile_size

        assert tile["src"]["width"] == (
            (width % src_tile_size) if is_last_x and has_trailing_x else src_tile_size
        )
        assert tile["src"]["height"] == (
            (height % src_tile_size) if is_last_y and has_trailing_y else src_tile_size
        )

        assert tile["dst"]["width"] == (
            math.ceil((width % src_tile_size) / scale_factor)
            if is_last_x and has_trailing_x
            else tile_size
        )
        assert tile["dst"]["height"] == (
            math.ceil((height % src_tile_size) / scale_factor)
            if is_last_y and has_trailing_y
            else tile_size
        )


@composite
def tiles(
    draw,
    xs=integers(min_value=0),
    ys=integers(min_value=0),
    scale_factors=integers(min_value=1),
    tile_widths=integers(min_value=1),
    tile_heights=integers(min_value=1),
):
    x = draw(xs)
    y = draw(ys)
    tile_width = draw(tile_widths)
    tile_height = draw(tile_heights)
    scale_factor = draw(scale_factors)

    return {
        "scale_factor": scale_factor,
        "index": {"x": x, "y": y},
        "src": {
            "x": x * tile_width * scale_factor,
            "y": y * tile_height * scale_factor,
            "width": tile_width * scale_factor,
            "height": tile_height * scale_factor,
        },
        "dst": {
            "x": x * tile_width,
            "y": y * tile_height,
            "width": tile_width,
            "height": tile_height,
        },
    }


@given(tiles())
def test_test_get_template_bindings_defaults(tile):
    bindings = get_template_bindings(tile)

    assert bindings["format"] == "jpg"
    assert bindings["rotation"] == "0"
    assert bindings["quality"] == "default"


@given(
    tile=tiles(),
    format=text(),
    quality=text(),
    rotation=integers(min_value=0, max_value=359),
)
def test_get_template_bindings(tile, format, quality, rotation):
    bindings = get_template_bindings(
        tile, format=format, quality=quality, rotation=rotation
    )

    assert all(isinstance(v, str) for v in bindings.keys())
    assert all(isinstance(v, str) for v in bindings.values())

    assert bindings["region.x"] == str(tile["src"]["x"])
    assert bindings["region.y"] == str(tile["src"]["y"])
    assert bindings["region.w"] == str(tile["src"]["width"])
    assert bindings["region.h"] == str(tile["src"]["height"])
    assert bindings["region"] == ",".join(
        str(tile["src"][p]) for p in ["x", "y", "width", "height"]
    )
    assert bindings["size.w"] == str(tile["dst"]["width"])
    assert bindings["size.h"] == str(tile["dst"]["height"])
    assert bindings["size"] == f"{tile['dst']['width']},{tile['dst']['height']}"
    assert bindings["format"] == format
    assert bindings["quality"] == quality
    assert bindings["rotation"] == str(rotation)


@pytest.mark.parametrize(
    "template, msg",
    [
        ["/foo", "generated path is not relative: /foo"],
        ["foo/../bar", 'generated path contains a ".." segment: foo/../bar'],
        ["../foo/bar", 'generated path contains a ".." segment: ../foo/bar'],
        ["", "generated path is empty"],
    ],
)
@settings(max_examples=1)
@given(tile=tiles())
def test_get_templated_dest_path_rejects_invalid_paths(template, msg, tile):
    with pytest.raises(InvalidPath) as excinfo:
        assert get_templated_dest_path(parse_template(template), tile)

    assert str(excinfo.value) == msg


def test_get_templated_dest_path():
    tile = dict(
        dst=dict(x=100, y=100, width=50, height=50),
        src=dict(x=200, y=200, width=100, height=100),
    )
    path = get_templated_dest_path(
        parse_template("foo/{size}-{region}.{format}"),
        tile,
        bindings_for_tile=partial(get_template_bindings, format="png"),
    )

    assert isinstance(path, Path)
    assert str(path) == "foo/50,50-200,200,100,100.png"


def test_create_file_methods():
    methods = {"copy", "hardlink", "symlink"}
    assert create_file_methods.keys() == methods
    for method in methods:
        assert isinstance(create_file_methods[method], abc.Callable)


@pytest.fixture()
def src_content():
    return "content"


@pytest.fixture()
def src_path(tmp_path, src_content):
    src = tmp_path / "foo/example"
    src.parent.mkdir()
    src.write_text(src_content)
    return src


@pytest.fixture()
def dst_path(tmp_path):
    dst = tmp_path / "bar/example"
    dst.parent.mkdir()
    return dst


@pytest.mark.parametrize(
    "method, is_symlink, src_affected_by_dst",
    [["copy", False, False], ["symlink", True, True], ["hardlink", False, True]],
)
def test_create_file_copy(
    src_path: Path,
    src_content: str,
    dst_path: Path,
    method: str,
    is_symlink: bool,
    src_affected_by_dst: bool,
):
    create_file = create_file_methods[method]
    create_file(src_path, dst_path)

    assert dst_path.read_text() == "content"
    assert dst_path.is_file()
    assert dst_path.is_symlink() == is_symlink

    # Check if src is affected by changes to dst
    dst_path.write_text(src_content + " changed")
    src_has_changed = src_path.read_text() != src_content
    assert src_has_changed == src_affected_by_dst


@pytest.fixture()
def mock_ensure_sub_directories_exist() -> Callable[[], ContextManager[Mock]]:
    @contextlib.contextmanager
    def patch_ensure_sub_directories_exist():
        with patch("tilediiif.tools.tilelayout.ensure_sub_directories_exist") as mock:
            mock.side_effect = lambda base, sub: base / sub
            yield mock

    return patch_ensure_sub_directories_exist


@given(tiles=lists(tiles(), max_size=50))
def test_create_tile_layout(tiles, mock_ensure_sub_directories_exist):
    with mock_ensure_sub_directories_exist() as mocked_ensure_sub_directories_exist:

        def get_tile_path(tile):
            return PurePath(f"/src/tile-{tiles.index(tile)}/foo/file.jpeg")

        def get_dest_path(tile):
            return PurePath(f"dest/tile-{tiles.index(tile)}/bar/file.jpg")

        create_file = Mock(spec=[])
        target_directory = PurePath("target/dir")

        create_tile_layout(
            tiles=iter(tiles),
            get_tile_path=get_tile_path,
            get_dest_path=get_dest_path,
            create_file=create_file,
            target_directory=target_directory,
        )

        assert mocked_ensure_sub_directories_exist.mock_calls == [
            call(target_directory, get_dest_path(tile)) for tile in tiles
        ]

        assert create_file.mock_calls == [
            call(get_tile_path(tile), target_directory / get_dest_path(tile))
            for tile in tiles
        ]


@pytest.mark.parametrize(
    "invalid_dest, msg",
    [
        [
            "abc/../foo",
            'get_dest_path returned a path which contains a ".." (parent) segment: '
            "abc/../foo",
        ],
        ["/abc", "get_dest_path returned a path which is not relative: /abc"],
        ["", "get_dest_path returned a path which is empty"],
    ],
)
def test_create_tile_layout_rejects_invalid_dest_paths(invalid_dest, msg):
    with pytest.raises(ValueError) as exc_info:
        create_tile_layout(
            tiles=[{}],
            get_tile_path=lambda t: PurePath("src"),
            get_dest_path=lambda t: PurePath(invalid_dest),
            create_file=lambda s, d: None,
            target_directory=PurePath("target"),
        )

    assert str(exc_info.value) == msg


@given(
    dzi_meta=dzi_metadata(
        widths=sampled_from([42, 800, 7920]),
        heights=sampled_from([38, 600, 9800]),
        tile_sizes=sampled_from([100, 256]),
    )
)
@settings(max_examples=10, deadline=2000)
def test_create_dzi_tile_layout(dzi_meta, mock_ensure_sub_directories_exist):
    def get_dest_path(tile):
        return PurePath(f"dest/tile-{tile_key(tile)}/bar/file.jpg")

    create_file_calls = Counter()

    def create_file(src, dst):
        create_file_calls[(src, dst)] += 1

    width, height, tile_size = [dzi_meta[p] for p in ["width", "height", "tile_size"]]
    dzi_path = PurePath("/some/where/foo.dzi")
    target_directory = PurePath("target/dir")

    scale_factors = power2_image_pyramid_scale_factors(
        width=width, height=height, tile_size=tile_size
    )

    expected_tiles = (
        tile
        for scale_factor in scale_factors
        for tile in get_layer_tiles(
            width=width, height=height, tile_size=tile_size, scale_factor=scale_factor
        )
    )

    with patch(
        "tilediiif.tools.tilelayout.create_tile_layout",
        new=Mock(wraps=create_tile_layout),
    ) as mock_create_tile_layout:
        with mock_ensure_sub_directories_exist():
            create_dzi_tile_layout(
                dzi_path=dzi_path,
                dzi_meta=dzi_meta,
                get_dest_path=get_dest_path,
                create_file=create_file,
                target_directory=target_directory,
            )
    mock_create_tile_layout.assert_called_once()

    tile_count = 0
    for i, tile in enumerate(expected_tiles):
        tile_count = i + 1
        tile_path = get_dzi_tile_path(
            tile, dzi_meta=dzi_meta, dzi_files_path=PurePath("/some/where/foo_files")
        )

        assert (
            create_file_calls[
                (PurePath(tile_path), target_directory / get_dest_path(tile))
            ]
            == 1
        )
    assert len(create_file_calls) == tile_count


def tile_key(tile):
    return json.dumps(tile, sort_keys=True, indent=None, separators=(",", ":"))


@pytest.fixture
def mock_create_dzi_tile_layout():
    with patch("tilediiif.tools.tilelayout.create_dzi_tile_layout") as mock:
        yield mock


@pytest.fixture
def dummy_run(mock_create_dzi_tile_layout: Mock):
    def dummy_run(args):
        mock_create_dzi_tile_layout.reset_mock()
        run(args)
        mock_create_dzi_tile_layout.assert_called_once()
        _, kwargs = mock_create_dzi_tile_layout.call_args
        return kwargs

    return dummy_run


TmpPathManager = Callable[[], ContextManager[Path]]


@pytest.fixture()
def tidied_tmp_path(tmp_path) -> TmpPathManager:
    """
    A context manager which:

    * on entry: provides an un-created path for a dir to be created at
    * on exit: removes the dir
    """
    path = Path(tempfile.mktemp(dir=tmp_path))
    assert not path.exists()
    depth = 0

    @contextlib.contextmanager
    def un_created_tmp_dir():
        nonlocal path, depth
        depth += 1
        yield path
        depth -= 1
        assert depth >= 0
        if depth == 0:
            shutil.rmtree(path, ignore_errors=True)

    return un_created_tmp_dir


@pytest.fixture
def dummy_run_with_defaults(
    dummy_run, tidied_tmp_path: TmpPathManager, dzi_ms_add_path
):
    def dummy_run_with_defaults(args=None):
        with tidied_tmp_path() as tmp_path:
            args = {
                "<dzi-file>": str(dzi_ms_add_path),
                "<dest-directory>": str(tmp_path),
                **({} if args is None else args),
            }
            return dummy_run(args)

    return dummy_run_with_defaults


def test_run_uses_supplied_paths(
    dummy_run_with_defaults,
    tidied_tmp_path: TmpPathManager,
    dzi_ms_add_path: Path,
    dzi_ms_add_meta: Path,
):
    with tidied_tmp_path() as tmp_path:
        kwargs = dummy_run_with_defaults()

        assert kwargs["dzi_path"] == dzi_ms_add_path
        assert kwargs["dzi_meta"] == dzi_ms_add_meta
        assert kwargs["target_directory"] == tmp_path


@pytest.mark.parametrize(
    "args, expected",
    [
        [{}, create_file_methods[DEFAULT_FILE_METHOD]],
        [{"--file-creation-method": "copy"}, create_file_methods["copy"]],
        [{"--file-creation-method": "symlink"}, create_file_methods["symlink"]],
        [{"--file-creation-method": "hardlink"}, create_file_methods["hardlink"]],
    ],
)
def test_run_option_file_creation_method(args, expected, dummy_run_with_defaults):
    kwargs = dummy_run_with_defaults(args)
    assert kwargs["create_file"] == expected


@given(tile=tiles())
def test_run_option_tile_path_template(tile, dummy_run_with_defaults):
    kwargs = dummy_run_with_defaults({"--tile-path-template": "foo/{region.x}"})
    assert kwargs["get_dest_path"](tile) == Path(f"foo/{tile['src']['x']}")


@given(tile=tiles())
def test_run_option_tile_path_template_default(tile, dummy_run_with_defaults):
    kwargs = dummy_run_with_defaults()
    path = str(kwargs["get_dest_path"](tile))
    assert path == parse_template(DEFAULT_FILE_PATH_TEMPLATE).render(
        get_template_bindings(tile)
    )
    assert len(path) > 0


@given(tile=tiles())
@pytest.mark.parametrize(
    "dzi_file, tile_extension",
    [
        [DATA_DIR / "MS-ADD-00269-000-01075.dzi", "jpg"],
        [DATA_DIR / "MS-ADD-00269-000-01075_with-png-format.dzi", "png"],
        # jpeg format is normalised to jpg
        [DATA_DIR / "jpeg-format.dzi", "jpg"],
    ],
)
def test_tiles_use_format_from_dzi(
    tile, dzi_file, tile_extension, dummy_run_with_defaults
):
    kwargs = dummy_run_with_defaults(args={"<dzi-file>": str(dzi_file)})
    path = str(kwargs["get_dest_path"](tile))
    assert path == parse_template(DEFAULT_FILE_PATH_TEMPLATE).render(
        get_template_bindings(tile, format=tile_extension)
    )


def test_run_option_allow_existing_dest(
    dummy_run_with_defaults, tidied_tmp_path: TmpPathManager
):
    with tidied_tmp_path() as tmp_path:
        tmp_path.mkdir()
        kwargs = dummy_run_with_defaults({"--allow-existing-dest": True})
        assert kwargs["target_directory"] == tmp_path
