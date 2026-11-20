#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Create ./passwd for the test broker. Every user gets the password "test".
# Export the matching variables before running the example cases:
#   export MQTT_ADMIN_PASSWORD=test MQTT_PW_KITCHEN=test ...
set -eu
cd "$(dirname "$0")"

USERS="admin kitchen livingroom tasmofleet homeassistant viewer"
IMAGE=$(sed -n 's/^ *image: *\([^ ]*\).*/\1/p' compose.yaml)

# Runs inside the container so the file ends up owned by the mosquitto user (1883)
# with mode 0700, as Mosquitto 2 expects.
rm -f passwd
docker run --rm -v "$PWD:/work" -e USERS="$USERS" "$IMAGE" sh -c '
    touch /work/passwd
    for user in $USERS; do mosquitto_passwd -b /work/passwd "$user" test; done
    chown 1883:1883 /work/passwd
    chmod 0700 /work/passwd
'
echo "passwd created for: admin kitchen livingroom tasmofleet homeassistant viewer"
