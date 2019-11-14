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

    from tilediiif.dzi_generation import main

    main()
