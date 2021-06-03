import enum
import os
import subprocess

import pytest
from integration_tests.data import TEST_IMG_PEARS_SRGB_EMBEDDED

PEARS_SMALL = TEST_IMG_PEARS_SRGB_EMBEDDED["path"]


class MozjpegSupport(enum.Enum):
    ENABLED = "enabled"
    BROKEN = "broken"
    DISABLED = "disabled"


try:
    EXPECT_MOZJPEG_SUPPORT = MozjpegSupport(
        os.environ["EXPECT_MOZJPEG_SUPPORT"] or "enabled"
    )
except KeyError:
    EXPECT_MOZJPEG_SUPPORT = MozjpegSupport.ENABLED
except ValueError as e:
    raise ValueError(
        "Invalid value for environment variable EXPECT_MOZJPEG_SUPPORT: "
        f'{os.environ["EXPECT_MOZJPEG_SUPPORT"]}, expected one of '
        f"{' or '.join(repr(x.value) for x in MozjpegSupport)}"
    ) from e


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


@pytest.mark.skipif("EXPECT_MOZJPEG_SUPPORT == MozjpegSupport.ENABLED")
def test_using_mozjpeg_options_without_mozjpeg_fails(
    dzi_path,
    cli_option_requiring_mozjpeg,
):
    result = subprocess.run(
        [
            "dzi-tiles",
            cli_option_requiring_mozjpeg,
            PEARS_SMALL,
            dzi_path,
        ],
        env={
            "PATH": os.environ["PATH"],
        },
        capture_output=True,
        encoding="utf-8",
    )

    if EXPECT_MOZJPEG_SUPPORT == MozjpegSupport.BROKEN:
        assert result.returncode == 1
        assert "No module named '_libvips'" in result.stderr
    else:
        assert EXPECT_MOZJPEG_SUPPORT == MozjpegSupport.DISABLED
        # Otherwise we'll notice
        assert result.returncode == 1
        assert result.stdout == ""
        assert (
            "Error: DZI generation failed: JPEG compression options requiring mozjpeg "
            "are enabled, but mozjpeg is not supported:"
            in result.stderr
        )
        assert "• libjpeg supports param API: False" in result.stderr
        assert "• libvips supports libjpeg params: False" in result.stderr
