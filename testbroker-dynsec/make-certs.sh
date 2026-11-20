#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Create the test CAs, a server certificate and client certificates in ./certs.
#   ca.crt        test CA = server CA: server certificate and the clients of
#                 listeners 8884/8885 (variants A and B)
#   admin-ca.crt  admin CA: only admin certificates for listener 8886
#                 (PMSS design v0.7)
# For the test broker only: keys are unencrypted and world-readable so the
# container user can read them.
set -eu
cd "$(dirname "$0")"
mkdir -p certs
cd certs

days=3650
key() { openssl genpkey -algorithm EC -pkeyopt ec_paramgen_curve:P-256 -out "$1" 2>/dev/null; }

key ca.key
openssl req -x509 -new -key ca.key -out ca.crt -days $days -subj "/CN=mqtt-acl-verify test CA"

key server.key
openssl req -new -key server.key -out server.csr -subj "/CN=localhost"
printf 'subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n' > server.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out server.crt -days $days -extfile server.ext 2>/dev/null

# Client certificates; the CN is the username on listeners with use_identity_as_username
for cn in dynsec-admin dynsec-admin-cert stranger; do
    key "$cn.key"
    openssl req -new -key "$cn.key" -out "$cn.csr" -subj "/CN=$cn"
    printf 'extendedKeyUsage=clientAuth\n' > client.ext
    openssl x509 -req -in "$cn.csr" -CA ca.crt -CAkey ca.key -CAcreateserial \
        -out "$cn.crt" -days $days -extfile client.ext 2>/dev/null
done

# Admin CA (PMSS design v0.7): signs admin certificates only
key admin-ca.key
openssl req -x509 -new -key admin-ca.key -out admin-ca.crt -days $days -subj "/CN=mqtt-acl-verify test admin CA"

# pmss-admin-disabled: exists in DynSec but is disabled (disableClient)
# pmss-admin-deleted:  was an admin, deleted again (deleteClient)
# admin-ca-unknown:    CN never known to DynSec
for cn in pmss-admin pmss-breakglass-admin pmss-admin-disabled pmss-admin-deleted admin-ca-unknown; do
    key "$cn.key"
    openssl req -new -key "$cn.key" -out "$cn.csr" -subj "/CN=$cn"
    printf 'extendedKeyUsage=clientAuth\n' > client.ext
    openssl x509 -req -in "$cn.csr" -CA admin-ca.crt -CAkey admin-ca.key -CAcreateserial \
        -out "$cn.crt" -days $days -extfile client.ext 2>/dev/null
done

rm -f ./*.csr ./*.ext ./*.srl
chmod 0644 ./*.key ./*.crt
echo "Certificates created in $(pwd)"
