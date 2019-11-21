import sys


def run_dzi_generation_with_faulthandler_enabled():
    """
    Run tilediiif.dzi_generation:main() with error handlers enabled for segfaults.

    This is necessary to show a traceback if pyvips fails to load libvips. This can
    happen if the shared libraries used by vips are not set up correctly. e.g. if vips
    is compiled to support mozjpeg but regular libjpeg is used at runtime vips will
    segfault.
    """
    import faulthandler

    faulthandler.enable()

    try:
        from tilediiif.dzi_generation import main
    except ModuleNotFoundError as e:
        import traceback

        print(
            f"""\
Error: {e}

tilediiif must be installed with the 'dzigeneration' extra to use dzi-tiles. e.g:
  $ pip install tilediiif[dzigeneration]
""",
            file=sys.stderr,
        )
        traceback.print_exc()
        sys.exit(2)

    main()
