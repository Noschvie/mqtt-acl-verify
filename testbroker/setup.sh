#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Create the password file (if missing) and (re)start the Classic ACL test broker.
#
#   ./setup.sh           create passwd on first run, then (re)create the container
#   ./setup.sh --reset   recreate passwd from scratch
#
# All users get the password "test". After changing acl or mosquitto.conf,
# just run ./setup.sh again.
set -eu
cd "$(dirname "$0")"

IMAGE=$(sed -n 's/^ *image: *\([^ ]*\).*/\1/p' compose.yaml)
USERS="admin kitchen livingroom tasmofleet homeassistant viewer"

if [ "${1:-}" = "--reset" ]; then
    docker compose down
    # passwd belongs to the container user (1883), so delete it from inside a container
    docker run --rm -v "$PWD:/work" "$IMAGE" rm -f /work/passwd
fi

if [ ! -f passwd ]; then
    # Created inside the container: owner 1883 and mode 0700 from the start,
    # as Mosquitto 2 expects (no "world readable" warnings).
    docker run --rm -v "$PWD:/work" -e USERS="$USERS" "$IMAGE" sh -c '
        umask 077
        touch /work/passwd
        for user in $USERS; do mosquitto_passwd -b /work/passwd "$user" test; done
        chown 1883:1883 /work/passwd
    '
    echo "passwd created for: $USERS"
else
    echo "Existing passwd kept (use --reset to recreate it)."
fi

docker compose up -d --force-recreate

# Wait until the broker accepts an authenticated publish
i=0
until docker compose exec -T mosquitto mosquitto_pub -u admin -P test -t setup/ready -m ok -q 1 >/dev/null 2>&1 </dev/null; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
        echo "broker not ready, see: docker compose logs mosquitto" >&2
        exit 1
    fi
    sleep 1
done
echo "Broker ready on 127.0.0.1:1883."
