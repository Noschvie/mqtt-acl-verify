#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# When does Mosquitto pick up a changed CRL or cafile: SIGHUP or restart?
#   listener 8891: crlfile certs/crl-reload.pem    - app-homeassistant is revoked
#   listener 8892: cafile  certs/cafile-reload.crt - the TasmoFleet CA is removed
# The files are restored at the end. Needs the running test broker (./setup.sh).
set -eu
cd "$(dirname "$0")"

# connects <port> <cert> <key>: 0 if the TLS handshake and CONNECT succeed
connects() {
    docker compose exec -T mosquitto timeout 10 mosquitto_pub -h localhost -p "$1" \
        --cafile /mosquitto/certs/ca.crt \
        --cert "/mosquitto/certs/$2" --key "/mosquitto/certs/$3" \
        -t reload/check -m x -q 1 >/dev/null 2>&1 </dev/null
}

failed=0
# expect <label> <ok|refused> <port> <cert> <key>
expect() {
    if connects "$3" "$4" "$5"; then got=ok; else got=refused; fi
    if [ "$got" = "$2" ]; then mark="PASS"; else mark="FAIL"; failed=1; fi
    printf '%-5s %-46s expect=%-7s actual=%s\n' "$mark" "$1" "$2" "$got"
}

wait_ready() {
    i=0
    until docker compose exec -T mosquitto mosquitto_ctrl -u dynsec-admin -P test dynsec getDefaultACLAccess >/dev/null 2>&1 </dev/null; do
        i=$((i + 1)); [ "$i" -lt 30 ] || { echo "broker not ready" >&2; exit 1; }
        sleep 1
    done
}

restore() {
    cp certs/crl.pem certs/crl-reload.pem
    cp certs/app-and-tf-ca.crt certs/cafile-reload.crt
}
trap restore EXIT

restore
docker compose restart >/dev/null 2>&1; wait_ready
expect "initial: app cert on 8891"            ok 8891 app-homeassistant.crt app-homeassistant.key
expect "initial: TasmoFleet cert on 8892"     ok 8892 tf-app.crt tf-app.key

# New CRL revoking app-homeassistant, built on a copy of the CA database
tmp=$(mktemp -d)
cp -r certs/crl-db certs/app-ca.crt certs/app-ca.key certs/app-homeassistant.crt "$tmp/"
(cd "$tmp" &&
 openssl ca -config crl-db/app-ca.cnf -cert app-ca.crt -keyfile app-ca.key -revoke app-homeassistant.crt 2>/dev/null &&
 openssl ca -config crl-db/app-ca.cnf -cert app-ca.crt -keyfile app-ca.key -gencrl -out app-ca.crl 2>/dev/null)
cat "$tmp/app-ca.crl" certs/app-int-ca.crl > certs/crl-reload.pem
rm -rf "$tmp"
cp certs/app-ca.crt certs/cafile-reload.crt

expect "files changed, no reload: 8891"       ok 8891 app-homeassistant.crt app-homeassistant.key
expect "files changed, no reload: 8892"       ok 8892 tf-app.crt tf-app.key

docker compose kill -s HUP mosquitto >/dev/null 2>&1; sleep 2
expect "after SIGHUP: revoked cert on 8891"   refused 8891 app-homeassistant.crt app-homeassistant.key
expect "after SIGHUP: removed CA on 8892"     ok 8892 tf-app.crt tf-app.key

docker compose restart >/dev/null 2>&1; wait_ready
expect "after restart: removed CA on 8892"    refused 8892 tf-app.crt tf-app.key

restore
docker compose restart >/dev/null 2>&1; wait_ready
expect "restored: app cert on 8891"           ok 8891 app-homeassistant.crt app-homeassistant.key
expect "restored: TasmoFleet cert on 8892"    ok 8892 tf-app.crt tf-app.key

trap - EXIT
exit $failed
