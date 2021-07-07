FROM base AS tools-dev
ARG DOCKER_CLI_PACKAGE=https://download.docker.com/linux/debian/dists/buster/pool/stable/amd64/docker-ce-cli_20.10.7~3-0~debian-buster_amd64.deb

RUN apt-get update && apt-get install -y \
    build-essential \
    # required to install node from nodesource
    curl \
    git
# Docker CLI is needed to build and push Docker images. (It's expected to talk
# to a remote Docker daemon.)
RUN curl -sL "${DOCKER_CLI_PACKAGE}" > /tmp/docker-ce-cli.deb \
    && dpkg -i /tmp/docker-ce-cli.deb \
    && rm /tmp/docker-ce-cli.deb
# node & npm required for npx projen ... commands
RUN curl -sL https://deb.nodesource.com/setup_14.x | bash -
RUN apt-get install -y nodejs
# not required, but speeds up npx projen ... commands
RUN npm install -g projen
RUN pip install poetry

# An image in which vips was built with mozjpeg, but mozjpeg is not available at runtime, so vips
# will blow up when trying to do things requiring mozjpeg.
FROM tools-dev AS tools-dev-with-broken-mozjpeg
RUN rm -rf /opt/mozjpeg /etc/ld.so.conf.d/00.mozjpeg.conf \
    && ldconfig
