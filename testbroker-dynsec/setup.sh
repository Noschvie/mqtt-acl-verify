#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Initialise and start the Dynamic Security test broker.
#
#   ./setup.sh           first run: init DynSec, start broker, apply dynsec-setup.txt
#                        later runs: just (re)start the broker
#   ./setup.sh --reset   delete the DynSec configuration and start from scratch
#
# All users get the password "test".
set -euf
cd "$(dirname "$0")"

IMAGE=$(sed -n 's/^ *image: *\([^ ]*\).*/\1/p' compose.yaml)
CTRL="mosquitto_ctrl -u dynsec-admin -P test dynsec"

if [ "${1:-}" = "--reset" ]; then
    docker compose down
    # data/ belongs to the container user (1883), so delete it from inside a container
    docker run --rm -v "$PWD:/work" "$IMAGE" rm -rf /work/data
fi

fresh=no
if [ ! -f data/dynamic-security.json ]; then
    mkdir -p data
    docker run --rm -v "$PWD/data:/mosquitto/data" "$IMAGE" sh -c '
        mosquitto_ctrl dynsec init /mosquitto/data/dynamic-security.json dynsec-admin test >/dev/null
        chown -R 1883:1883 /mosquitto/data
        chmod 0700 /mosquitto/data
        chmod 0600 /mosquitto/data/dynamic-security.json
    '
    fresh=yes
fi

docker compose up -d --force-recreate

# Wait until the broker answers DynSec requests
i=0
until docker compose exec -T mosquitto $CTRL getDefaultACLAccess >/dev/null 2>&1 </dev/null; do
    i=$((i + 1))
    if [ "$i" -ge 30 ]; then
        echo "broker not ready, see: docker compose logs mosquitto" >&2
        exit 1
    fi
    sleep 1
done

if [ "$fresh" = yes ]; then
    echo "Applying dynsec-setup.txt ..."
    grep -v -e '^# ' -e '^#$' -e '^[[:space:]]*$' dynsec-setup.txt | while read -r line; do
        # word splitting of $line is intended; globbing is disabled (set -f)
        if ! out=$(docker compose exec -T mosquitto $CTRL $line 2>&1 </dev/null); then
            echo "FAILED: $line" >&2
            echo "$out" | grep -v -e '^Warning: You are running' -e '^This means all of' >&2
            exit 1
        fi
    done
    echo "DynSec configured."
else
    echo "Existing DynSec configuration kept (use --reset to start from scratch)."
fi
