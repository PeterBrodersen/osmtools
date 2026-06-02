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

docker run -d --restart unless-stopped -p 127.0.0.1:5010:5010 --name osrm-restrictions -v "${PWD}:/data" ghcr.io/project-osrm/osrm-backend osrm-routed --port 5010 --algorithm mld /data/${OSMFILE:?}

docker run -d --restart unless-stopped -t -i --env-file .env -p 127.0.0.1:9976:9966 --name osrm-denmark-exclude-frontend ghcr.io/project-osrm/osrm-frontend:latest
