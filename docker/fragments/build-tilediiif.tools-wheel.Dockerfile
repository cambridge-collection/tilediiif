FROM build-tilediiif-wheel-base AS build-tilediiif.tools-wheel
ARG TILEDIIIF_TOOLS_SHA
RUN git fetch --tags origin && git reset --hard "${TILEDIIIF_TOOLS_SHA}"
RUN cd tilediiif.tools \
    && poetry build \
    && mkdir /tmp/wheels \
    && cp dist/tilediiif?tools-*.whl /tmp/wheels/
