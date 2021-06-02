ARG MOZJPEG_VERSION=4.0.3
ARG VIPS_VERSION=8.10.6
ARG VIPS_USE_MOZJPEG=1

ARG _MOZJPEG_VARIANT_ENABLED=${VIPS_USE_MOZJPEG:+with-mozjpeg}
ARG _MOZJPEG_VARIANT=${_MOZJPEG_VARIANT_ENABLED:-without-mozjpeg}

FROM python:3.9-slim-buster as python-base

FROM debian:buster-slim AS build-mozjpeg
ARG MOZJPEG_VERSION
WORKDIR /tmp
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y curl
RUN curl -L "https://github.com/mozilla/mozjpeg/archive/refs/tags/v${MOZJPEG_VERSION}.tar.gz" > mozjpeg.tar.gz \
    && tar -xf mozjpeg.tar.gz
WORKDIR /tmp/mozjpeg-${MOZJPEG_VERSION}
RUN apt-get install -y cmake make nasm clang libpng-dev
ENV CC=/usr/bin/clang CXX=/usr/bin/clang++
RUN cmake -G"Unix Makefiles" -DWITH_JPEG8=1 | tee cmake.log
    # Ensure arithmetic coding is enabled
RUN ((fgrep -q '(WITH_ARITH_DEC = 1)' cmake.log && fgrep -q '(WITH_ARITH_ENC = 1)' cmake.log) \
        || (printf '\nError: Arithmetic coding is required, but appears not to be enabled in CMake output\n' && exit 2))
RUN make \
    && make deb
RUN printf "%s\n" /opt/mozjpeg/lib64 > /etc/ld.so.conf.d/00.mozjpeg.conf
RUN apt install /tmp/mozjpeg-${MOZJPEG_VERSION}/mozjpeg_${MOZJPEG_VERSION}_amd64.deb


FROM debian:buster-slim AS build-vips-base-with-mozjpeg
ARG MOZJPEG_VERSION
ENV MOZJPEG_VERSION=$MOZJPEG_VERSION
ENV PKG_CONFIG_PATH=/opt/mozjpeg/lib64/pkgconfig:$PKG_CONFIG_PATH
COPY --from=build-mozjpeg /opt/mozjpeg /opt/mozjpeg

FROM debian:buster-slim AS build-vips-base-without-mozjpeg


FROM build-vips-base-$_MOZJPEG_VARIANT AS build-vips
ARG VIPS_VERSION
ARG VIPS_TARBALL=https://github.com/libvips/libvips/releases/download/v$VIPS_VERSION/vips-$VIPS_VERSION.tar.gz
ARG VIPS_TARBALL_SHA256=2468088d958e0e2de1be2991ff8940bf45664a826c0dad12342e1804e2805a6e
ENV DEBIAN_FRONTEND=noninteractive \
    CC=/usr/bin/clang \
    CXX=/usr/bin/clang++
WORKDIR /tmp
RUN apt-get update && apt-get install -y \
    build-essential \
    clang \
    pkg-config \
    libglib2.0-dev \
    libexpat1-dev \
    curl \
    # Packages for optional VIPS features
    # Not available:
    #  - libspng
    #  - libniftiio
    #  - libjxl
    libexif-dev \
    librsvg2-dev \
    libgsf-1-dev \
    libtiff-dev \
    libfftw3-dev \
    liblcms2-dev \
    libpng-dev \
    libimagequant-dev \
    libgraphicsmagick1-dev \
    libpango1.0-dev \
    liborc-0.4-dev \
    libmatio-dev \
    libcfitsio-dev \
    libwebp-dev \
    libopenexr-dev \
    libopenslide-dev \
    libheif-dev \
    libgif-dev
RUN curl -L "$VIPS_TARBALL" > vips-$VIPS_VERSION.tar.gz \
    && echo "$VIPS_TARBALL_SHA256  vips-$VIPS_VERSION.tar.gz" > vips-$VIPS_VERSION.tar.gz.sha256 \
    && sha256sum -c vips-$VIPS_VERSION.tar.gz.sha256 \
    && tar -xf vips-$VIPS_VERSION.tar.gz
RUN cd vips-$VIPS_VERSION \
    && ./configure --prefix=/opt/vips --with-magickpackage=GraphicsMagick | tee /tmp/vips-configure-output \
    && make | tee /tmp/vips-build-output \
    && make install
RUN printf "%s\n" /opt/vips/lib > /etc/ld.so.conf.d/00.vips.conf


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


FROM base AS tools-dev
RUN apt-get update && apt-get install -y build-essential \
    && pip install poetry


# An image in which vips was built with mozjpeg, but mozjpeg is not available at runtime, so vips
# will blow up when trying to do things requiring mozjpeg.
FROM tools-dev AS tools-dev-with-broken-mozjpeg
RUN rm -rf /opt/mozjpeg /etc/ld.so.conf.d/00.mozjpeg.conf \
    && ldconfig
