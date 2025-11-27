#!/usr/bin/sh
OSMFILE=$1
LUAFILE=$2

# Check if the file exists
if [ ! -f "$OSMFILE" ]; then
    echo "File $OSMFILE does not exist."
    exit 1
fi

docker run --rm -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-extract -p /data/${LUAFILE:?} /data/${OSMFILE:?}
docker run --rm -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-partition /data/${OSMFILE:?}
docker run --rm -t -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-customize /data/${OSMFILE:?}
docker run --rm -p 127.0.0.1:5000:5000 --name osrm-restrictions -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-routed --algorithm mld /data/${OSMFILE:?}
