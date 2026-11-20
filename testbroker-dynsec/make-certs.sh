#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Create the test CAs, a server certificate and client certificates in ./certs.
#   ca.crt        test CA = server CA: server certificate and the clients of
#                 listeners 8884/8885 (variants A and B)
#   admin-ca.crt  admin CA: only admin certificates for listener 8886
#                 (PMSS design v0.7)
#   app-ca.crt    app CA: application certificates for listener 8887
#                 (PMSS design v0.8, production port 8885)
#   app-int-ca    intermediate CA below the app CA (later: TasmoFleet)
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

# --- PMSS design v0.8: TLS listeners 8883 (password) and 8887 (app certificates) ---

# Server certificate for 8883/8887 (production: server-ext, RSA for Tasmota/BearSSL)
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out server-ext.key 2>/dev/null
openssl req -new -key server-ext.key -out server-ext.csr -subj "/CN=localhost"
printf 'subjectAltName=DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth\n' > server.ext
openssl x509 -req -in server-ext.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out server-ext.crt -days $days -extfile server.ext 2>/dev/null

# App CA: signs application certificates, subject /O=mqtt-apps/CN=<name>
key app-ca.key
openssl req -x509 -new -key app-ca.key -out app-ca.crt -days $days -subj "/CN=mqtt-acl-verify test app CA"

# Intermediate CA below the app CA (later: TasmoFleet signs app certificates with it)
key app-int-ca.key
openssl req -new -key app-int-ca.key -out app-int-ca.csr -subj "/CN=mqtt-acl-verify test TasmoFleet intermediate CA"
printf 'basicConstraints=critical,CA:TRUE,pathlen:0\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n' > int.ext
openssl x509 -req -in app-int-ca.csr -CA app-ca.crt -CAkey app-ca.key -CAcreateserial \
    -out app-int-ca.crt -days $days -extfile int.ext 2>/dev/null

# app_cert <file> <cn> <signing CA basename>
app_cert() {
    key "$1.key"
    openssl req -new -key "$1.key" -out "$1.csr" -subj "/O=mqtt-apps/CN=$2"
    printf 'extendedKeyUsage=clientAuth\n' > client.ext
    openssl x509 -req -in "$1.csr" -CA "$3.crt" -CAkey "$3.key" -CAcreateserial \
        -out "$1.crt" -days $days -extfile client.ext 2>/dev/null
}

# Signed by the app CA
app_cert app-homeassistant homeassistant app-ca
app_cert app-pmss-admin pmss-admin app-ca            # mis-issued: CN of an admin

# Locking an app certificate (deleteClient), then issuing a new one:
#   reused:  same subject again       -> the old certificate works again
#   renamed: new subject (suffix -2)  -> the old certificate stays locked
app_cert app-reused-old reused-app app-ca            # compromised, client deleted
app_cert app-reused-new reused-app app-ca            # new certificate, same subject
app_cert app-renamed-old renamed-app app-ca          # compromised, client deleted
app_cert app-renamed-new renamed-app-2 app-ca        # new certificate, new subject

# Signed by the intermediate CA. *-chain.crt = client certificate + intermediate CA,
# as the application has to send it; *.crt alone lacks the intermediate CA.
app_cert int-viewer viewer app-int-ca
app_cert int-pmss-admin pmss-admin app-int-ca        # mis-issued via the intermediate CA
for f in int-viewer int-pmss-admin; do
    cat "$f.crt" app-int-ca.crt > "$f-chain.crt"
done

rm -f ./*.csr ./*.ext ./*.srl
chmod 0644 ./*.key ./*.crt
echo "Certificates created in $(pwd)"
