# Test broker

`testbroker/` contains a local Mosquitto 2 with Classic ACL for development and demonstration.

| File | Content |
|---|---|
| `mosquitto.conf` | One plain listener, password file, ACL file, debug logging |
| `acl` | Rules for admin, tasmofleet, homeassistant, viewer and Tasmota devices (`%u`) |
| `config.yaml`, `cases.yaml` | Matching configuration and cases |
| `compose.yaml`, `create-passwd.sh` | Docker setup |

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
./create-passwd.sh            # all users get password "test"
docker compose up -d

export MQTT_ADMIN_PASSWORD=test MQTT_PW_KITCHEN=test MQTT_PW_LIVINGROOM=test \
       MQTT_PW_TASMOFLEET=test MQTT_PW_HOMEASSISTANT=test MQTT_PW_VIEWER=test \
       MQTT_PW_UNKNOWN=wrong
mqtt-acl-verify run -c config.yaml -t cases.yaml

docker compose logs mosquitto > broker.log
mqtt-acl-verify inventory broker.log -p -u
```

Expected: `11 cases: 11 passed, 0 failed, 0 errors` (exit code 0).

`ha-receive-filedownload` checks a deny rule: Home Assistant may read `stat/#`, but not `stat/+/FILEDOWNLOAD` (backup content). In the ACL file this is `topic deny stat/+/FILEDOWNLOAD`. A deny rule takes precedence over read/write rules regardless of line order. Remove the line and the case fails.

**After changing `acl` or `mosquitto.conf`** (including via `git pull`), recreate the container:

```sh
docker compose up -d --force-recreate
docker compose exec mosquitto grep deny /mosquitto/config/acl   # check what the broker sees
```

Mosquitto reads these files only at startup, and a single-file bind mount keeps pointing to the old file once git replaces it. A plain `docker compose up -d` does nothing while the container is running, and a reload via SIGHUP still sees the old file.

The integration test (`tests/test_integration.py`) runs the same cases against a locally installed `mosquitto` binary and is skipped if it is missing.
