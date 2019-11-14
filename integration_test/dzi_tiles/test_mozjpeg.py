import os
import platform
import subprocess
from pathlib import Path
from signal import Signals
from tempfile import TemporaryDirectory

import pytest

PROJECT_ROOT = Path(__file__).parents[2]

PLATFORM = f"{platform.system()}-{platform.machine()}"
PLATFORMS_WITH_TEST_LIBS = frozenset(["Linux-x86_64"])
PLATFORM_HAS_NO_TEST_LIBS = PLATFORM not in PLATFORMS_WITH_TEST_LIBS
COND_PLATFORM_HAS_NO_TEST_LIBS = "PLATFORM not in PLATFORMS_WITH_TEST_LIBS"

LIBS_DIR = Path(__file__).parent.parent / "data/libs"
LIB_PATH_LIBJPEG = LIBS_DIR / "libjpeg" / PLATFORM
LIB_PATH_MOZJPEG = LIBS_DIR / "mozjpeg" / PLATFORM
LIB_PATH_VIPS_WITHOUT_MOZJPEG = LIBS_DIR / "vips-without-mozjpeg" / PLATFORM
LIB_PATH_VIPS_WITH_MOZJPEG = LIBS_DIR / "vips-with-mozjpeg" / PLATFORM


@pytest.yield_fixture()
def tmp_data_path(tmp_path):
    with TemporaryDirectory(dir=tmp_path) as path:
        yield Path(path)


LIBS_WITHOUT_MOZJPEG_SUPPORT = pytest.mark.parametrize(
    "libjpeg_is_mozjpeg, libvips_supports_mozjpeg",
    [[False, False], [False, True], [True, False]],
)


@pytest.fixture
def libjpeg_path(libjpeg_is_mozjpeg):
    return LIB_PATH_MOZJPEG if libjpeg_is_mozjpeg else LIB_PATH_LIBJPEG


@pytest.fixture
def libvips_path(libvips_supports_mozjpeg):
    return (
        LIB_PATH_VIPS_WITH_MOZJPEG
        if libvips_supports_mozjpeg
        else LIB_PATH_VIPS_WITHOUT_MOZJPEG
    )


@pytest.fixture(
    params=[
        "--jpeg-trellis-quant",
        "--jpeg-overshoot-deringing",
        "--jpeg-optimize-scans",
        "--jpeg-quant-table=3",
    ]
)
def cli_option_requiring_mozjpeg(request):
    return request.param


@pytest.mark.skipif(COND_PLATFORM_HAS_NO_TEST_LIBS)
@LIBS_WITHOUT_MOZJPEG_SUPPORT
def test_using_mozjpeg_options_without_mozjpeg_fails(
    tmp_data_path,
    cli_option_requiring_mozjpeg,
    libjpeg_path,
    libvips_path,
    libjpeg_is_mozjpeg,
    libvips_supports_mozjpeg,
):
    dzi_path = tmp_data_path / "result"
    result = subprocess.run(
        [
            "dzi-tiles",
            cli_option_requiring_mozjpeg,
            PROJECT_ROOT / "test_tilediiif/server/data/pears_small.jpg",
            dzi_path,
        ],
        env={
            "PATH": os.environ["PATH"],
            "LD_LIBRARY_PATH": f"{libvips_path}:{libjpeg_path}",
        },
        capture_output=True,
        encoding="utf-8",
    )

    if libvips_supports_mozjpeg and not libjpeg_is_mozjpeg:
        # We'll get a segfault if libvips compiled for mozjpeg is used with regular
        # libjpeg. This occurs when pyvips is imported, but we only check for mozjpeg
        # support after that, so currently we are not able to handle this nicely.
        assert -result.returncode == Signals.SIGSEGV.value
        assert "Fatal Python error: Segmentation fault" in result.stderr
    else:
        # Otherwise we'll notice
        assert result.returncode == 1
        assert result.stdout == ""
        assert (
            "Error: DZI generation failed: JPEG compression options requiring mozjpeg "
            "are enabled, but mozjpeg is not supported:" in result.stderr
        )
        assert f"• libjpeg supports param API: {libjpeg_is_mozjpeg}" in result.stderr
        assert (
            f"• libvips supports libjpeg params: {libvips_supports_mozjpeg}"
            in result.stderr
        )
