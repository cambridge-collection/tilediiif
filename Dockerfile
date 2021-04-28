ARG MOZJPEG_VERSION=4.0.3
ARG VIPS_VERSION=8.10.6


FROM debian:buster-slim AS build-mozjpeg
ARG MOZJPEG_VERSION
WORKDIR /tmp
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y curl
RUN curl -L "https://github.com/mozilla/mozjpeg/archive/refs/tags/v${MOZJPEG_VERSION}.tar.gz" > mozjpeg.tar.gz \
    && tar -xf mozjpeg.tar.gz
RUN apt-get install -y build-essential cmake nasm libpng-dev
RUN cd /tmp/mozjpeg-${MOZJPEG_VERSION} \
    && cmake -G"Unix Makefiles" \
    && make \
    && make deb
RUN apt install /tmp/mozjpeg-${MOZJPEG_VERSION}/mozjpeg_${MOZJPEG_VERSION}_amd64.deb


FROM debian:buster-slim AS build-vips
ARG MOZJPEG_VERSION
ARG VIPS_VERSION
ARG VIPS_TARBALL=https://github.com/libvips/libvips/releases/download/v$VIPS_VERSION/vips-$VIPS_VERSION.tar.gz
ARG VIPS_TARBALL_SHA256=2468088d958e0e2de1be2991ff8940bf45664a826c0dad12342e1804e2805a6e
ENV DEBIAN_FRONTEND=noninteractive
ENV PKG_CONFIG_PATH=/opt/mozjpeg/lib64/pkgconfig
COPY --from=build-mozjpeg /opt/mozjpeg /opt/mozjpeg
WORKDIR /tmp
RUN apt-get update && apt-get install -y \
    build-essential \
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


FROM python:3.9-buster as base
ENV DEBIAN_FRONTEND=noninteractive
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
    libwebp6 \
    libopenexr23 \
    libopenslide0 \
    libheif1 \
    libgif7 \
    && rm -rf /var/cache/* /var/lib/cache/* /var/lib/apt/lists/* /var/log/*
ARG MOZJPEG_VERSION
ARG VIPS_VERSION
COPY --from=build-mozjpeg /opt/mozjpeg /opt/mozjpeg
COPY --from=build-vips /opt/vips /opt/vips
ENV VIPS_VERSION=$VIPS_VERSION \
    MOZJPEG_VERSION=$MOZJPEG_VERSION \
    PATH=$PATH:/opt/vips/bin:/opt/mozjpeg/bin \
    LD_LIBRARY_PATH=$LD_LIBRARY_PATH:/opt/vips/lib:/opt/mozjpeg/lib64 \
    PKG_CONFIG_PATH=$PKG_CONFIG_PATH:/opt/vips/lib/pkgconfig:/opt/mozjpeg/lib64/pkgconfig


FROM base AS dev

WORKDIR /opt/project
COPY pyproject.toml pyproject.toml
COPY poetry.lock poetry.lock
RUN apt-get update && apt-get install -y build-essential
RUN pip install poetry \
    && poetry config virtualenvs.create false \
    && poetry install --no-root --no-interaction --extras server --extras dzigeneration
