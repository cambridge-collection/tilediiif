#!/usr/bin/env bash
set -euxo pipefail
cd "$(dirname "$0")"

NAME=pears_small_size512
vips dzsave pears_small.jpg $NAME --overlap 0 --tile-size 512 --properties --strip --suffix .jpg[Q=80]
iiif-tiles from-dzi ${NAME}.dzi ${NAME}
infojson from-dzi ${NAME}.dzi --indent 2 --id "http://localhost:8000/${NAME}" > ${NAME}/info.json
