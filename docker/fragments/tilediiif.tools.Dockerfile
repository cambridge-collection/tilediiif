FROM base AS tilediiif.tools
ARG TILEDIIIF_TOOLS_SHA
ARG TILEDIIIF_CORE_SHA
LABEL org.opencontainers.image.title="camdl/tilediiif.tools"
LABEL org.opencontainers.image.source="https://github.com/cambridge-collection/tilediiif"

COPY --from=build-tilediiif.tools-wheel \
    /tmp/wheels/* \
    /tmp/wheels/
COPY --from=build-tilediiif.core-wheel \
    /tmp/wheels/* \
    /tmp/wheels/
RUN pip install \
    /tmp/wheels/tilediiif.core-*.whl \
    /tmp/wheels/tilediiif.tools-*.whl \
    && rm -rf /tmp/wheels
