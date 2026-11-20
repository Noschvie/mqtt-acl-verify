# Test broker

`testbroker/` contains a local Mosquitto 2.1.2 (`eclipse-mosquitto:2.1.2-alpine`, same version as production) with Classic ACL for development and demonstration.

| File | Content |
|---|---|
| `mosquitto.conf` | One plain listener, password file, ACL file, debug logging |
| `acl` | Rules for admin, tasmofleet, homeassistant, viewer and Tasmota devices (`%u`) |
| `config.yaml`, `cases.yaml` | Matching configuration and cases |
| `compose.yaml`, `setup.sh` | Docker setup; `setup.sh` creates the password file and (re)starts the broker |

Prerequisites: Docker with the compose plugin, and the package installed in a virtual environment in the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

The `mqtt-acl-verify` command is only available while the venv is active. In a new shell, run `. .venv/bin/activate` again (from `testbroker/`: `. ../.venv/bin/activate`), or call it directly as `../.venv/bin/mqtt-acl-verify`.

Start the broker and run the cases:

```sh
cd testbroker
./setup.sh                    # first run creates passwd; all users get password "test"

export MQTT_ADMIN_PASSWORD=test MQTT_PW_KITCHEN=test MQTT_PW_LIVINGROOM=test \
       MQTT_PW_TASMOFLEET=test MQTT_PW_HOMEASSISTANT=test MQTT_PW_VIEWER=test \
       MQTT_PW_UNKNOWN=wrong
../.venv/bin/mqtt-acl-verify run -c config.yaml -t cases.yaml

docker compose logs mosquitto > broker.log
../.venv/bin/mqtt-acl-verify inventory broker.log -p -u
```

The examples call the command from the venv directly, so they also work in a new shell. With an activated venv, plain `mqtt-acl-verify` works as well.

Expected: `11 cases: 11 passed, 0 failed, 0 errors` (exit code 0).

`ha-receive-filedownload` checks a deny rule: Home Assistant may read `stat/#`, but not `stat/+/FILEDOWNLOAD` (backup content). In the ACL file this is `topic deny stat/+/FILEDOWNLOAD`. A deny rule takes precedence over read/write rules regardless of line order. Remove the line and the case fails.

**After changing `acl` or `mosquitto.conf`** (including via `git pull`), run `./setup.sh` again. It recreates the container. Mosquitto reads these files only at startup, and a single-file bind mount keeps pointing to the old file once git replaces it, so a plain `docker compose up -d` or a reload via SIGHUP is not enough. To check what the broker sees:

```sh
docker compose exec mosquitto grep deny /mosquitto/config/acl
```

`passwd` belongs to the container user (1883, mode 0700), so you cannot read it as yourself. To recreate it: `./setup.sh --reset`.

The integration test (`tests/test_integration.py`) runs the same cases against this broker when `MQTT_TEST_BROKER=host:port` is set (as in CI), otherwise against a locally installed `mosquitto` binary, and is skipped if neither is available.
