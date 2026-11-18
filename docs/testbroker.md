# Test broker

`testbroker/` contains a local Mosquitto 2 with Classic ACL for development and demonstration.

| File | Content |
|---|---|
| `mosquitto.conf` | One plain listener, password file, ACL file, debug logging |
| `acl` | Rules for admin, tasmofleet, homeassistant, viewer and Tasmota devices (`%u`) |
| `config.yaml`, `cases.yaml` | Matching configuration and cases |
| `compose.yaml`, `create-passwd.sh` | Docker setup |

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

Expected: all cases pass except `ha-receive-filedownload`. Classic ACL has no deny rules, so "read `stat/#` but not `stat/+/FILEDOWNLOAD`" cannot be expressed. The failing case documents that limitation.

The integration test (`tests/test_integration.py`) runs the same cases against a locally installed `mosquitto` binary and is skipped if it is missing.
