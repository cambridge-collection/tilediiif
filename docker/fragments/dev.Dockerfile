FROM base AS tools-dev
RUN apt-get update && apt-get install -y \
    build-essential \
    # required to install node from nodesource
    curl
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
