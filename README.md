# mqtt-acl-verify

Broker-independent test suite to verify MQTT ACLs: checks which messages each client can **actually** publish and receive.

A successful CONNECT or SUBSCRIBE proves nothing. Mosquitto, for example, grants a subscription to `cmnd/other-device/#` and then silently drops every message on it. `mqtt-acl-verify` therefore injects a unique test message and checks whether it arrives.

## Features

- **ACL tests** (`run`): connect, publish and receive cases with expected result `allow` or `deny`, Markdown report, non-zero exit code on failure (CI-friendly).
- **Topic inventory** (`inventory`): who publishes and subscribes what, parsed from broker debug logs. Includes denied publishes, which is useful in an observation phase before rules are tightened.
- **Safe by default**: test topics carry a `{probe}` level so no real device command is triggered; unique client IDs so no live device is kicked off; passwords only from environment variables.

| Backend | ACL tests | Inventory |
|---|---|---|
| Mosquitto Classic ACL | ✅ | ✅ (log) |
| Mosquitto Dynamic Security (2.1+) | ✅ | ✅ (log) |
| EMQX 5 | ✅ | planned (trace) |

ACL tests work against any MQTT 3.1.1 / 5 broker, since they only use the protocol.

## Quick start

Requires Python 3.13 or later. Install into a virtual environment (Debian/Ubuntu refuse system-wide `pip install`):

```sh
python3 -m venv .venv
. .venv/bin/activate     # needed in every new shell, or call .venv/bin/mqtt-acl-verify
pip install .            # or for development: pip install -e '.[dev]'

cp examples/config.example.yaml config.yaml
cp examples/cases.example.yaml  cases.yaml
# adapt both, then provide passwords:
export MQTT_ADMIN_PASSWORD=... MQTT_PW_KITCHEN=...

mqtt-acl-verify run -c config.yaml -t cases.yaml -r reports/acl.md
```

Example output:

```
PASS  dev-receive-own-cmnd      expect=allow actual=allow SUBACK: Granted QoS 1; message received
PASS  dev-receive-foreign-cmnd  expect=deny  actual=deny  SUBACK: Granted QoS 1; message not received
PASS  dev-publish-foreign-stat  expect=deny  actual=deny  PUBACK: Not authorized; message not delivered
FAIL  ha-receive-filedownload   expect=deny  actual=allow SUBACK: Granted QoS 1; message received
```

Topic inventory from a Mosquitto log (`log_type all`):

```sh
mqtt-acl-verify inventory broker.log --placeholders --by-user
```

## Try it locally

- `testbroker/` – Mosquitto with Classic ACL. See [docs/testbroker.md](docs/testbroker.md).
- `testbroker-dynsec/` – Mosquitto 2.1.4 with Dynamic Security, same rights. See [docs/testbroker-dynsec.md](docs/testbroker-dynsec.md).
- `tests/test_dynsec_control.py`, `probes/autopaho-reconnect/` – DynSec control API checks for PMSS (`correlationData`, `getClient`, autopaho reconnect). See [docs/testbroker-dynsec.md](docs/testbroker-dynsec.md#control-api-for-pmss).

## Documentation

- [Test model](docs/test-model.md) – how cases are executed, what "allow" and "deny" mean, safety rules
- [Configuration](docs/configuration.md) – `config.yaml` and `cases.yaml` reference
- [Topic inventory](docs/inventory.md) – deriving profiles from broker logs
- [Test broker](docs/testbroker.md) – local Mosquitto with Classic ACL
- [Test broker with Dynamic Security](docs/testbroker-dynsec.md) – local Mosquitto 2.1.4 with DynSec

## Background

Part of the MQTT security work for [TasmoFleet](https://github.com/hellwand/tasmofleet): moving from one shared MQTT user to individual identities with least-privilege profiles. The test cases follow the communication model in TasmoFleet's [`docs/mqtt-broker-acl.md`](https://github.com/hellwand/tasmofleet/blob/main/docs/mqtt-broker-acl.md).

## License

[GNU Affero General Public License v3.0 or later](LICENSE) (`AGPL-3.0-or-later`).
