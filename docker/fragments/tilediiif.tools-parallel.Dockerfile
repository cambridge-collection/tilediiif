FROM tilediiif.tools AS tilediiif.tools-parallel
RUN apt-get update \
    && apt-get install -y parallel \
    && rm -rf /var/lib/apt/lists/*
