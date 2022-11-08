ARG MOZJPEG_VERSION=4.0.3

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
RUN apt install /tmp/mozjpeg-${MOZJPEG_VERSION}/mozjpeg_${MOZJPEG_VERSION}_*.deb
