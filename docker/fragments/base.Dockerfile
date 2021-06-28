FROM python-base AS base-without-mozjpeg
FROM python-base AS base-with-mozjpeg
ARG MOZJPEG_VERSION
ENV MOZJPEG_VERSION=$MOZJPEG_VERSION \
    PATH=$PATH:/opt/mozjpeg/bin
COPY --from=build-mozjpeg /opt/mozjpeg /opt/mozjpeg
COPY --from=build-mozjpeg /etc/ld.so.conf.d/00.mozjpeg.conf /etc/ld.so.conf.d/00.mozjpeg.conf

FROM base-$_MOZJPEG_VARIANT AS base
ENV DEBIAN_FRONTEND=noninteractive
ARG VIPS_VERSION
COPY --from=build-vips /opt/vips /opt/vips
COPY --from=build-vips /etc/ld.so.conf.d/00.vips.conf /etc/ld.so.conf.d/00.vips.conf
RUN apt-get update && apt-get install -y \
    libexif12 \
    librsvg2-2 \
    libgsf-1-114 \
    libtiff5 \
    libfftw3-3 \
    liblcms2-2 \
    libpng16-16 \
    libimagequant0 \
    graphicsmagick \
    libpangocairo-1.0-0 \
    liborc-0.4-0 \
    libmatio4 \
    libcfitsio7 \
    libwebpdemux2 \
    libopenexr23 \
    libopenslide0 \
    libheif1 \
    libgif7 \
    # update the linker cache to contain libs added via /etc/ld.so.conf.d
    && ldconfig \
    && rm -rf /var/cache/* /var/lib/cache/* /var/lib/apt/lists/* /var/log/*
ENV VIPS_VERSION=$VIPS_VERSION \
    PATH=$PATH:/opt/vips/bin \
    # required when building pyvips
    PKG_CONFIG_PATH=$PKG_CONFIG_PATH:/opt/vips/lib/pkgconfig
