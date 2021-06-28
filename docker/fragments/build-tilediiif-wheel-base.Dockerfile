FROM python-base AS build-tilediiif-wheel-base
RUN apt-get update && apt-get install -y git && pip install poetry
WORKDIR /tmp/build-tilediiif/
COPY .git tilediiif.git
RUN git init tilediiif && cd tilediiif && git remote add origin ../tilediiif.git
WORKDIR /tmp/build-tilediiif/tilediiif
