# Configuration

Two YAML files: `config.yaml` (broker access) and `cases.yaml` (expectations). Both names are git-ignored; start from `examples/`.

## config.yaml

```yaml
endpoints:
  plain: {host: mqtt.example.lan, port: 1883}
  tls:   {host: mqtt.example.lan, port: 8883, tls: true}

default_endpoint: plain   # optional, default: first endpoint
timeout: 2.0              # seconds to wait for CONNACK/SUBACK/PUBACK/messages
observer: admin

identities:
  admin:
    username: admin
    password_env: MQTT_ADMIN_PASSWORD
    endpoint: tls
  kitchen:
    username: kitchen
    password_env: MQTT_PW_KITCHEN
```

### endpoints

| Key | Default | Description |
|---|---|---|
| `host`, `port` | – | Broker address |
| `tls` | `false` | Use TLS, server certificate is verified |
| `ca_file` | system store | CA file for the server certificate |
| `protocol` | `5` | `5` = MQTT v5, `4` = MQTT 3.1.1 |

### identities

| Key | Description |
|---|---|
| `username` | MQTT username; omit for anonymous |
| `password_env` | Name of the environment variable holding the password |
| `endpoint` | Endpoint used by default for this identity |
| `client_id` | Fixed client ID. Default: unique `<username>-aclprobe-<random>` |
| `cert_file`, `key_file` | Client certificate and key for mTLS (only used on TLS endpoints). Set both or neither |

`username: null` connects without username, e.g. on a listener with `use_identity_as_username`, where the certificate CN becomes the username.

File paths (`ca_file`, `cert_file`, `key_file`) are relative to the directory of `config.yaml`.

## cases.yaml

```yaml
cases:
  - id: dev-receive-foreign-cmnd
    client: kitchen
    action: receive
    topic: cmnd/livingroom/#
    publish_topic: cmnd/livingroom/{probe}
    expect: deny
```

| Key | Required | Description |
|---|---|---|
| `id` | ✅ | Unique case ID |
| `client` | ✅ | Identity under test |
| `action` | ✅ | `connect`, `publish` or `receive` |
| `expect` | ✅ | `allow` or `deny` |
| `topic` | publish, receive | Publish topic, or subscription filter for `receive` |
| `publish_topic` | receive with wildcards | Concrete topic the observer publishes to; must match `topic` |
| `endpoint` | | Overrides the identity's endpoint (e.g. admin on the plain port) |
| `live` | | `true` allows topics without `{probe}` |
| `description` | | Free text |

Several case files can be combined, e.g. shared cases plus broker-specific ones: `-t ../testbroker/cases.yaml cases-dynsec.yaml`. Case IDs must be unique across all files.

Run selected cases only: `mqtt-acl-verify run -c config.yaml -t cases.yaml --only dev-receive-own-cmnd unknown-connect`

Exit codes: `0` all passed, `1` at least one fail or error, `2` configuration error.
