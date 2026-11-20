# Test broker with Dynamic Security

`testbroker-dynsec/` contains a local Mosquitto **2.1.2** with the Dynamic Security plugin (DynSec). It grants the same rights as the Classic ACL test broker in `testbroker/`, so both run the same cases.

| File | Content |
|---|---|
| `mosquitto.conf` | Listeners 1883 (host 1884), 8884 and 8885 (mTLS), DynSec plugin, debug logging |
| `dynsec-setup.txt` | DynSec commands equivalent to `testbroker/acl`, one `mosquitto_ctrl dynsec` command per line |
| `setup.sh` | Initialises DynSec, starts the broker, applies `dynsec-setup.txt` |
| `config.yaml` | Endpoint and identities for `mqtt-acl-verify` |
| `cases-dynsec.yaml` | Additional cases for the DynSec admin |
| `cases-mtls.yaml` | Admin login variants on the mTLS listeners |
| `make-certs.sh` | Test CA, server and client certificates in `certs/` (called by `setup.sh`) |
| `compose.yaml` | Docker setup, image pinned to `eclipse-mosquitto:2.1.2-alpine` |

## Run

Prerequisites as in [testbroker.md](testbroker.md) (Docker, package installed in a venv).

```sh
cd testbroker-dynsec
./setup.sh                    # first run: init + configure; all users get password "test"

export MQTT_OBSERVER_PASSWORD=test MQTT_DYNSEC_ADMIN_PASSWORD=test \
       MQTT_PW_KITCHEN=test MQTT_PW_LIVINGROOM=test MQTT_PW_TASMOFLEET=test \
       MQTT_PW_HOMEASSISTANT=test MQTT_PW_VIEWER=test MQTT_PW_UNKNOWN=wrong
../.venv/bin/mqtt-acl-verify run -c config.yaml -t ../testbroker/cases.yaml cases-dynsec.yaml cases-mtls.yaml
```

Expected: `27 cases: 27 passed, 0 failed, 0 errors`.

Host ports: **1884** (plain), **8884** and **8885** (mTLS). It can run next to `testbroker/` (1883). `setup.sh` needs `openssl` on the host to create the test certificates.

`./setup.sh` keeps an existing DynSec configuration in `data/`. To start from scratch: `./setup.sh --reset`. After changing `mosquitto.conf`, run `./setup.sh` again (it recreates the container). After changing `dynsec-setup.txt`, run `./setup.sh --reset`.

## Users

| User | Purpose | Rights |
|---|---|---|
| `dynsec-admin` | Manages DynSec via `mosquitto_ctrl`, password | Only `$CONTROL/dynamic-security/#` and `$SYS/#`, no normal topics |
| `dynsec-admin-cert` | Same, **without password**, only via certificate on 8885 | Same role `admin` |
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

## CI

The integration test `test_dynsec_testbroker_cases` runs all 27 cases against this broker when `MQTT_TEST_BROKER_DYNSEC=host:port` is set. CI starts the broker with `./setup.sh`.
