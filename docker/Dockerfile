FROM ubuntu:19.04

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl ca-certificates \
        python3.7 python3.7-dev python3.7-venv python3-pip \
        libvips-dev libvips42 build-essential
RUN apt-get install -y --no-install-recommends python3-setuptools python3-wheel
