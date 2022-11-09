FROM build-tilediiif-wheel-base AS build-tilediiif.awslambda-wheel
ARG TILEDIIIF_AWSLAMBDA_SHA
RUN git fetch --tags origin && git reset --hard "${TILEDIIIF_AWSLAMBDA_SHA}"
RUN cd tilediiif.awslambda \
    && poetry build \
    && mkdir /tmp/wheels \
    && cp dist/tilediiif?awslambda-*.whl /tmp/wheels/
