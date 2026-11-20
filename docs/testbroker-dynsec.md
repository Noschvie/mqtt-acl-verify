# Test broker with Dynamic Security

`testbroker-dynsec/` contains a local Mosquitto **2.1.2** with the Dynamic Security plugin (DynSec). It grants the same rights as the Classic ACL test broker in `testbroker/`, so both run the same cases.

| File | Content |
|---|---|
| `mosquitto.conf` | Listener 1883 (host port 1884), DynSec plugin, debug logging |
| `dynsec-setup.txt` | DynSec commands equivalent to `testbroker/acl`, one `mosquitto_ctrl dynsec` command per line |
| `setup.sh` | Initialises DynSec, starts the broker, applies `dynsec-setup.txt` |
| `config.yaml` | Endpoint and identities for `mqtt-acl-verify` |
| `cases-dynsec.yaml` | Additional cases for the DynSec admin |
| `compose.yaml` | Docker setup, image pinned to `eclipse-mosquitto:2.1.2-alpine` |

## Run

Prerequisites as in [testbroker.md](testbroker.md) (Docker, package installed in a venv).

```sh
cd testbroker-dynsec
./setup.sh                    # first run: init + configure; all users get password "test"

export MQTT_OBSERVER_PASSWORD=test MQTT_DYNSEC_ADMIN_PASSWORD=test \
       MQTT_PW_KITCHEN=test MQTT_PW_LIVINGROOM=test MQTT_PW_TASMOFLEET=test \
       MQTT_PW_HOMEASSISTANT=test MQTT_PW_VIEWER=test MQTT_PW_UNKNOWN=wrong
../.venv/bin/mqtt-acl-verify run -c config.yaml -t ../testbroker/cases.yaml cases-dynsec.yaml
```

Expected: `15 cases: 15 passed, 0 failed, 0 errors`.

The broker listens on host port **1884**, so it can run next to `testbroker/` (1883).

`./setup.sh` keeps an existing DynSec configuration in `data/`. To start from scratch: `./setup.sh --reset`. After changing `mosquitto.conf`, run `./setup.sh` again (it recreates the container). After changing `dynsec-setup.txt`, run `./setup.sh --reset`.

## Users

| User | Purpose | Rights |
|---|---|---|
| `dynsec-admin` | Manages DynSec via `mosquitto_ctrl` | Only `$CONTROL/dynamic-security/#` and `$SYS/#`, no normal topics |
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

## CI

The integration test `test_dynsec_testbroker_cases` runs all 15 cases against this broker when `MQTT_TEST_BROKER_DYNSEC=host:port` is set. CI starts the broker with `./setup.sh`.
