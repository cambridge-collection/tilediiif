FROM build-tilediiif-wheel-base AS build-tilediiif.core-wheel
ARG TILEDIIIF_CORE_SHA
RUN git fetch origin && git reset --hard "${TILEDIIIF_CORE_SHA}"
RUN cd tilediiif.core \
    && poetry build \
    && mkdir /tmp/wheels \
    && cp dist/tilediiif.core-*.whl /tmp/wheels/
