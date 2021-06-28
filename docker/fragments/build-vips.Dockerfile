ARG VIPS_VERSION=8.10.6
ARG VIPS_USE_MOZJPEG=1
ARG _MOZJPEG_VARIANT_ENABLED=${VIPS_USE_MOZJPEG:+with-mozjpeg}
ARG _MOZJPEG_VARIANT=${_MOZJPEG_VARIANT_ENABLED:-without-mozjpeg}

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
