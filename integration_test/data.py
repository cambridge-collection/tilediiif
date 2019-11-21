from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]
PROFILE_SRGB_PATH = PROJECT_ROOT / "tilediiif/data/sRGB2014.icc"
DATA = Path(__file__).parents[0] / "data"
IMAGE_DATA = DATA / "images"

TEST_IMG_PEARS_SRGB_EMBEDDED = {
    "path": PROJECT_ROOT / "test_tilediiif/server/data/pears_small.jpg",
    "width": 1000,
    "height": 750,
    "colour_profile": "srgb",
    "colour_profile_location": "embedded",
}

TEST_IMG_PEARS_SRGB_STRIPPED = {
    "path": IMAGE_DATA / "pears_small_srgb_stripped.jpg",
    "width": 1000,
    "height": 750,
    "colour_profile": "srgb",
    "colour_profile_location": None,
}


TEST_IMG_PEARS_ADOBERGB1998_EMBEDDED = {
    "path": IMAGE_DATA / "pears_small_adobergb1998.jpg",
    "width": 1000,
    "height": 750,
    "colour_profile": "adobergb1998",
    "colour_profile_location": "embedded",
}

TEST_IMG_PEARS_ADOBERGB1998_STRIPPED = {
    "path": IMAGE_DATA / "pears_small_adobergb1998_stripped.jpg",
    "width": 1000,
    "height": 750,
    "colour_profile": "adobergb1998",
    "colour_profile_location": DATA / "profiles/AdobeRGB1998.icc",
}
