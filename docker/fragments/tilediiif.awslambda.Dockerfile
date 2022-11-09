FROM base AS tilediiif.awslambda
ARG TILEDIIIF_AWSLAMBDA_SHA
ARG TILEDIIIF_TOOLS_SHA
ARG TILEDIIIF_CORE_SHA

COPY --from=build-tilediiif.awslambda-wheel \
    /tmp/wheels/* \
    /tmp/wheels/
COPY --from=build-tilediiif.tools-wheel \
    /tmp/wheels/* \
    /tmp/wheels/
COPY --from=build-tilediiif.core-wheel \
    /tmp/wheels/* \
    /tmp/wheels/
RUN pip install \
    /tmp/wheels/tilediiif?core-*.whl \
    /tmp/wheels/tilediiif?tools-*.whl \
    $(ls /tmp/wheels/tilediiif?awslambda-*.whl)[lambda-runtime] \
    && rm -rf /tmp/wheels

# AWS Lambda Python images need to use the AWS Lambda Python Runtime Interface
# Client to host the actual lambda function code. See:
#   https://pypi.org/project/awslambdaric/
ENTRYPOINT [ "/usr/local/bin/python", "-m", "awslambdaric" ]
# The Python import path to our default lambda handler function
CMD [ "tilediiif.awslambda.tilegenerator_lambda.handle_direct" ]
