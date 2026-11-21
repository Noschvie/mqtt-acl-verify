# Test broker with Dynamic Security

`testbroker-dynsec/` contains a local Mosquitto **2.1.2** with the Dynamic Security plugin (DynSec). It grants the same rights as the Classic ACL test broker in `testbroker/`, so both run the same cases.

| File | Content |
|---|---|
| `mosquitto.conf` | Listeners 1883 (host 1884), 8883 (TLS), 8884–8887 (mTLS), DynSec plugin, debug logging |
| `dynsec-setup.txt` | DynSec commands equivalent to `testbroker/acl`, one `mosquitto_ctrl dynsec` command per line |
| `setup.sh` | Initialises DynSec, starts the broker, applies `dynsec-setup.txt` |
| `config.yaml` | Endpoint and identities for `mqtt-acl-verify` |
| `cases-dynsec.yaml` | Additional cases for the DynSec admin |
| `cases-mtls.yaml` | Admin login variants on the mTLS listeners and the PMSS design v0.7 |
| `cases-apps.yaml` | PMSS design v0.8: TLS with password (8883), app certificates (8887), intermediate CA |
| `cases-revocation.yaml` | Revoking app certificates: CRL (8888, 8889) vs. a separate TasmoFleet root CA (8890) |
| `reload-check.sh` | Changes CRL and cafile at runtime (8891, 8892) and checks SIGHUP vs. restart; restores the files |
| `make-certs.sh` | Server CA, admin CA, app CA with intermediate CAs, TasmoFleet root CA, CRLs, server and client certificates in `certs/` (called by `setup.sh`) |
| `compose.yaml` | Docker setup, image pinned to `eclipse-mosquitto:2.1.2-alpine` |

## Run

Prerequisites as in [testbroker.md](testbroker.md) (Docker, package installed in a venv in the repository root, `openssl`).

```sh
cd testbroker-dynsec
./setup.sh                    # first run: init + configure; all users get password "test"

export MQTT_OBSERVER_PASSWORD=test MQTT_DYNSEC_ADMIN_PASSWORD=test \
       MQTT_PW_KITCHEN=test MQTT_PW_LIVINGROOM=test MQTT_PW_TASMOFLEET=test \
       MQTT_PW_HOMEASSISTANT=test MQTT_PW_VIEWER=test MQTT_PW_UNKNOWN=wrong
../.venv/bin/mqtt-acl-verify run -c config.yaml -t ../testbroker/cases.yaml cases-dynsec.yaml cases-mtls.yaml cases-apps.yaml cases-revocation.yaml
./reload-check.sh
```

Expected: `75 cases: 75 passed, 0 failed, 0 errors`, and `reload-check.sh` prints 9 × `PASS`.

Host ports: **1884** (plain), **8883** (TLS), **8884** to **8892** (mTLS). It can run next to `testbroker/` (1883). `setup.sh` needs `openssl` on the host to create the test certificates.

`./setup.sh` keeps an existing DynSec configuration in `data/`. To start from scratch: `./setup.sh --reset`. After changing `mosquitto.conf`, run `./setup.sh` again (it recreates the container). After changing `dynsec-setup.txt`, run `./setup.sh --reset`.

## Users

| User | Purpose | Rights |
|---|---|---|
| `dynsec-admin` | Manages DynSec via `mosquitto_ctrl`, password | Only `$CONTROL/dynamic-security/#` and `$SYS/#`, no normal topics |
| `dynsec-admin-cert` | Same, **without password**, only via certificate on 8885 | Same role `admin` |
| `pmss-admin`, `pmss-breakglass-admin` | PMSS design v0.7: **without password**, only via certificate of the admin CA on 8886 | Role `role_security_manager`: only `$CONTROL/dynamic-security/#` and `$SYS/#` |
| `pmss-admin-disabled`, `pmss-admin-deleted` | Locking tests: disabled (`disableClient`) resp. deleted (`deleteClient`) | – |
| `dynsec-bootstrap` | Bootstrap admin with password, deleted after the setup | – |
| `CN=homeassistant,O=mqtt-apps`, `CN=viewer,O=mqtt-apps` | PMSS design v0.8: applications **without password**, only via app certificate on 8887 | `role_homeassistant` resp. `role_viewer` |
| `observer` | Observer for `mqtt-acl-verify` | Read and write `#` |
| `tasmofleet`, `homeassistant`, `viewer` | Applications | As in `testbroker/acl` |
| `kitchen`, `livingroom` | Tasmota devices, group `group_tasmota` | `cmnd/%u/#` read, `stat/%u/#` and `tele/%u/#` write |

## Differences to Classic ACL

**Deny by default must be set explicitly.** DynSec starts with `publishClientReceive` and `unsubscribe` allowed. `dynsec-setup.txt` sets publish, receive and subscribe to deny.

**The admin created by `dynsec init` can read every topic.** Its role `admin` includes `subscribePattern #` and `publishClientReceive #`. `dynsec-setup.txt` removes both, so the admin only manages DynSec. The cases `dynsec-admin-*` check this.

**Placeholders `%u` / `%c` need Mosquitto 2.1.** In 2.0.x, DynSec compares ACL topics literally, so `cmnd/%u/#` never matches and the Tasmota cases fail. With 2.1.2 they pass.

**Deny rules use priority.** FILEDOWNLOAD for Home Assistant:

```
addRoleACL role_homeassistant publishClientReceive stat/# allow
addRoleACL role_homeassistant publishClientReceive stat/+/FILEDOWNLOAD deny 10
```

Higher priority is evaluated first. Without the priority both rules have priority 0 and the order is not guaranteed.

**Subscribe granted, delivery denied.** For `ha-receive-filedownload`, SUBACK grants `stat/#`, but the FILEDOWNLOAD message is not delivered – the receive rule filters it.

## Admin login over mTLS (overview questions 11, 17, 18)

Two listeners compare the two designs for the DynSec admin:

| Listener | Design | Configuration |
|---|---|---|
| 8884 | Variant A (PMSS document): mTLS **plus** DynSec password | `require_certificate true` |
| 8885 | Variant B (overview): mTLS only, username = certificate CN | `require_certificate true`, `use_identity_as_username true` |

DynSec runs with `per_listener_settings false`, so the same clients exist on all listeners. Results (`cases-mtls.yaml`):

| Case | Result |
|---|---|
| A: admin with certificate and password on 8884 | ✅ allowed |
| A: admin without certificate on 8884 | ❌ refused (TLS handshake) |
| A: admin with wrong password on 8884 | ❌ refused |
| A: admin password with **someone else's** certificate on 8884 | ⚠️ allowed – the certificate is not bound to the user |
| A: admin password on the **plain** listener | ⚠️ allowed – question 18 |
| B: admin certificate only on 8885 | ✅ allowed, `mosquitto_ctrl` works without password |
| B: admin certificate, claiming another username | ✅ logs in as the CN, the claimed name is ignored |
| B: admin username on the plain listener, without or with password | ❌ refused – a client without password cannot log in by password |
| B: admin certificate on 8884 | ❌ refused |
| B: certificate with a CN unknown to DynSec | ⚠️ connects, but has no rights (deny by default) |

**Conclusion:** Only variant B keeps the admin off the plain listener at the broker level (question 18). Answer to question 11: DynSec accepts a client without password via `use_identity_as_username`. Condition for variant B: the CA behind listener 8885 issues certificates only for admins, since every CN that exists in DynSec logs in with that client's rights. Use a dedicated CA for this listener.

Managing DynSec with the certificate admin:

```sh
mosquitto_ctrl -h 127.0.0.1 -p 8885 --cafile certs/ca.crt \
    --cert certs/dynsec-admin-cert.crt --key certs/dynsec-admin-cert.key \
    dynsec getDefaultACLAccess
```

## PMSS design v0.7 (overview questions 17, 18, 27)

Decision after the variant comparison: variant B with a **dedicated admin CA**. Listener 8886 trusts only `admin-ca.crt`; the server certificate comes from the test CA (server CA). The admins `pmss-admin` and `pmss-breakglass-admin` have no password and the role `role_security_manager`. The bootstrap admin `dynsec-bootstrap` is deleted after the setup, as in production.

| Case | Result |
|---|---|
| `pmss-admin` / `pmss-breakglass-admin` certificate only on 8886 | ✅ allowed, `mosquitto_ctrl` works |
| `pmss-admin` reads `tele/#`, FILEDOWNLOAD or publishes on `cmnd/…` | ❌ refused |
| `pmss-admin` username on the plain listener, without or with password | ❌ refused (question 18) |
| `pmss-admin` certificate on 8885 (server CA) | ❌ refused (TLS handshake) |
| Certificate of the server CA on 8886 | ❌ refused (TLS handshake) – fixes the weakness of variant B |
| Deleted bootstrap admin with password | ❌ refused |
| Admin locked with `deleteClient` | ✅ connects without rights; an open connection is disconnected ("administrative action") |
| Admin locked with `disableClient` | ⚠️ **still connects with full admin rights** |
| Admin CA certificate with a CN unknown to DynSec | ⚠️ connects, but has no rights |

**Locking an admin certificate:** use `deleteClient` (or remove its roles), not `disableClient`. The plugin checks the `disabled` flag only for password logins (`plugins/dynamic-security/auth.c`), not for certificate logins via `use_identity_as_username`, and not in the ACL check.

**`mosquitto_ctrl` exit code:** it exits with 0 even on `Subscribe error: Not authorized`. Scripts must check the output (see the CI step).

**Role name:** `dynsec init` always creates the role `admin` (fixed in Mosquitto 2.1.2, the documented `[role-name]` argument is not accepted). Production creates `role_security_manager`, assigns it and deletes `admin`. The test broker keeps `admin` for `dynsec-admin`, which `setup.sh` uses.

```sh
mosquitto_ctrl -h 127.0.0.1 -p 8886 --cafile certs/ca.crt \
    --cert certs/pmss-breakglass-admin.crt --key certs/pmss-breakglass-admin.key \
    dynsec listClients
```

## PMSS design v0.8: TLS listeners and app certificates

Port mapping to production (PMSS document 6.3): test **8883** = production 8883 (TLS with password), test **8887** = production 8885 (app certificates). Production 8885 is taken here by the variant B listener.

| Listener | Configuration |
|---|---|
| 8883 | TLS (`server-ext`, RSA, `tls_version tlsv1.2`), password login, same rights as 1883 |
| 8887 | `cafile` = app CA only, `require_certificate true`, `use_subject_as_username true`, `tls_version tlsv1.2` |

On 8887 the username is the **full subject** in RFC 2253 order: `/O=mqtt-apps/CN=homeassistant` becomes `CN=homeassistant,O=mqtt-apps`. App clients exist in DynSec under this name and have no password.

| Case | Result |
|---|---|
| Password client on 8883 | ✅ allowed, same rights as on 1883 |
| Password client without certificate on 8887 | ❌ refused (TLS handshake) |
| App certificate on 8887 | ✅ allowed as `CN=homeassistant,O=mqtt-apps`, rights of that client, FILEDOWNLOAD denied |
| App client name on 1883 or 8883, without or with password | ❌ refused – "TLS required" is enforced |
| Certificate of the admin CA or server CA on 8887 | ❌ refused (TLS handshake) |
| App certificate on the admin listener 8886 | ❌ refused (TLS handshake) |
| App CA certificate with `CN=pmss-admin` | ⚠️ connects as `CN=pmss-admin,O=mqtt-apps`, **no** rights, no access to the control API |

**Intermediate CA** (later: TasmoFleet issues app certificates with its own intermediate CA below the app CA):

| Case | Result |
|---|---|
| Certificate of the intermediate CA, file contains certificate **and** intermediate CA | ✅ allowed – the listener trusts only the app CA, the chain is accepted |
| Same, file contains the client certificate only | ❌ refused (TLS handshake) |
| Intermediate CA issues `CN=pmss-admin` | ⚠️ connects as `CN=pmss-admin,O=mqtt-apps`, **no** rights, no access to the control API |

So whoever holds the key of the intermediate CA can log in as any application, but never as admin. Applications must send the intermediate CA: `cat client.crt intermediate-ca.crt > client-chain.crt`.

**Locking an app certificate and issuing a new one.** DynSec knows only the username, i.e. the subject, not the certificate. `deleteClient` locks every certificate with that subject.

| Case | Result |
|---|---|
| Client deleted and **created again under the same subject**, old (compromised) certificate | ⚠️ **has its rights back** |
| Client deleted, new certificate with a **new subject** (`CN=renamed-app-2`), old certificate | ❌ no rights |

Rule: after locking a certificate because of a compromise, never reuse its subject. The new certificate gets a new name, e.g. with a suffix `-2`. Without a CRL this is the only way to keep the old certificate locked.

## Revoking app certificates: CRL vs. separate TasmoFleet CA

For the later stage in which TasmoFleet issues app certificates, a compromised TasmoFleet signing key must be lockable. `deleteClient` does not help there, since the key can issue certificates for every existing application. Two ways were compared:

1. **CRL** on the listener (`crlfile`), TasmoFleet as intermediate CA below the app CA.
2. **Separate TasmoFleet root CA**, listed next to the app CA in `cafile`; locking = removing it from `cafile`.

**CRL** (`cases-revocation.yaml`, listeners 8888 and 8889):

| Case | Result |
|---|---|
| Valid app certificate, CRL present | ✅ allowed |
| App certificate revoked in the CRL of the app CA | ❌ refused |
| Certificate of the TasmoFleet intermediate CA, whose (empty) CRL is in `crlfile` | ✅ allowed |
| Certificate of an intermediate CA that is revoked in the CRL of the app CA | ❌ refused – the whole chain is checked |
| Certificate of a valid intermediate CA **without** a CRL of its own in `crlfile` | ❌ refused – every CA of the chain needs a CRL |
| **Expired** CRL | ❌ **every** certificate refused |

**Separate root CA** (listener 8890 with both CAs, 8887 with the app CA only):

| Case | Result |
|---|---|
| TasmoFleet certificate, both CAs in `cafile` | ✅ allowed |
| App certificate, both CAs in `cafile` | ✅ allowed |
| TasmoFleet certificate, TasmoFleet CA not in `cafile` | ❌ refused |

**Reload** (`reload-check.sh`, listeners 8891 and 8892): Mosquitto reads both files only when the listener is set up.

| Change | Effective after |
|---|---|
| New CRL in `crlfile` | **SIGHUP** (no restart needed) |
| CA removed from `cafile` | **restart** only – SIGHUP keeps the old CA |

**Consequences:**

- With a CRL, the CRL of the app CA **and** the CRL of the TasmoFleet intermediate CA must be in `crlfile` at all times and must be renewed before they expire. Otherwise every certificate on the listener is refused. The CRL of the app CA is signed with the offline key, the CRL of the intermediate CA by TasmoFleet.
- With a separate root CA there is nothing to renew. Locking needs a broker restart (short interruption for all clients on all listeners).

## Control API for PMSS

Three questions from the PMSS design (risks "Korrelation" and "Paho Go / MQTT 5", decision S-5), answered against Mosquitto 2.1.2 and `paho.golang` v0.23.0.

| Test | Location |
|---|---|
| `correlationData`, `getClient` | `tests/test_dynsec_control.py` (pytest, 13 tests) |
| autopaho reconnect | `probes/autopaho-reconnect/` (`go test`, see its [README](../probes/autopaho-reconnect/README.md)) |

```sh
MQTT_TEST_BROKER_DYNSEC=127.0.0.1:1884 ../.venv/bin/pytest ../tests/test_dynsec_control.py -v
cd ../probes/autopaho-reconnect && go mod tidy && MQTT_TEST_BROKER_DYNSEC=127.0.0.1:1884 go test -v ./...
```

### Is `correlationData` returned?

Yes, per command, also for errors, in the order of the batch (`src/control_common.c`).

| Case | Result |
|---|---|
| String `correlationData`, several commands in one request | ✅ each response carries its own value, order kept |
| Error response (`Client not found`, `Client already exists`) | ✅ carries `correlationData` |
| UUID, empty string | ✅ returned verbatim |
| No `correlationData` | field missing in the response |
| `correlationData` not a string (e.g. number) | ⚠️ error `Invalid correlationData data type.` **without** `correlationData`; the **remaining commands of the batch are not executed** |
| Payload not JSON, `commands` not an array | ⚠️ error without `correlationData` |
| MQTT 5 `Response Topic` / `Correlation Data` properties | ⚠️ ignored: the answer always goes to `$CONTROL/dynamic-security/v1/response`, without properties |
| Second admin subscribed to the response topic | ⚠️ receives **every** response (the plugin publishes to all subscribers, not to the requester) |

Consequences for PMSS: always send `correlationData` as string (UUID); responses without or with unknown `correlationData` are expected (other admins, `mosquitto_ctrl`, invalid requests) and are logged and dropped; a request whose response has no `correlationData` ends by timeout. Responses of PMSS are visible to every other client with read access to the response topic.

### Does `getClient` return a password hash?

No. The hash (`encoded_password`) is only in `dynamic-security.json`.

| Case | Result |
|---|---|
| `getClient` of a password client | ✅ no `password`, `encoded_password`, salt or iteration field |
| `listClients` with `verbose` | ✅ same |
| `getClient` before and after `setClientPassword` | ✅ identical – **S-5 holds**: a password change does not change the client ETag |
| `disabled` | appears only as `true`; enabled clients have no field. The ETag must treat missing and `false` alike |

### autopaho with pending requests during a reconnect

| Case | Result |
|---|---|
| 20 parallel requests on one response topic | ✅ all matched by `correlationData` |
| Reconnect, clean session, subscribed once after the first connect | ❌ **no responses** after the reconnect – autopaho does not subscribe again |
| Reconnect, subscription in `OnConnectionUp` | ✅ responses arrive |
| Reconnect, `SessionExpiryInterval` 60 s, subscribed once | ✅ `SessionPresent`, the broker session keeps the subscription |
| `Publish` while the connection is down | ⚠️ returns `ConnectionDownError` **immediately**, no waiting for the reconnect (`AwaitConnection` waits) |
| Connection lost after the broker executed `createClient` (PUBACK and response lost), clean session | ⚠️ `Publish` does **not** return on the connection loss, only when its context expires; the response is lost; the client **was created** |
| Same, `SessionExpiryInterval` 60 s | ⚠️ paho retransmits the PUBLISH after the reconnect, Mosquitto **executes the command a second time**; only the answer to the repetition arrives: `Client already exists` |

Consequences for PMSS:

- Subscribe to the response topic in `OnConnectionUp` (on every connection), not once after start.
- Use a clean session (`SessionExpiryInterval` 0): DynSec commands are not idempotent, and a retransmission after the reconnect returns the error of the second execution with the correlation ID of the first.
- Every request needs a context timeout; a connection loss does not end a pending `Publish`.
- After a timeout the state is unknown: the command may have been executed. PMSS reads the object back (`getClient`/`getRole`/`getGroup`) before it reports an error or retries.
- On `ConnectionDownError`, either answer `503` at once or wait with `AwaitConnection` for a limited time.

## CI

The integration test `test_dynsec_testbroker_cases` runs all 75 cases against this broker when `MQTT_TEST_BROKER_DYNSEC=host:port` is set. CI starts the broker with `./setup.sh` and checks the control API with `mosquitto_ctrl`: on 8886 access for `pmss-admin` and `pmss-breakglass-admin`, none for `pmss-admin-deleted`, known weakness for `pmss-admin-disabled`; on 8887 no access for app certificates with `CN=pmss-admin` from the app CA or the intermediate CA. After the tests it runs `reload-check.sh` and the autopaho probe (`go test` in `probes/autopaho-reconnect/`). The pytest run includes `tests/test_dynsec_control.py`.
