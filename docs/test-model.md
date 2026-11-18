# Test model

## Roles

- **Client under test** – the identity named in the case (`client`). A fresh connection with a unique client ID is opened per case.
- **Observer** – one privileged identity (`observer` in `config.yaml`) with read and write access to every topic used in the cases. It injects messages and checks deliveries. Connect it via the TLS port.

## Actions

| Action | Procedure | "allow" means |
|---|---|---|
| `connect` | Client connects | CONNACK success |
| `publish` | Observer subscribes to `topic`, client publishes a unique payload (QoS 1, not retained) | Observer receives the payload |
| `receive` | Client subscribes to `topic` (filter), observer publishes a unique payload to `publish_topic` | Client receives the payload |

SUBACK and PUBACK reason codes are recorded in the detail column, but never decide the result. A broker may grant a subscription and still filter delivery, or (MQTT 3.1.1) silently drop a denied publish.

## Status

| Status | Meaning |
|---|---|
| ✅ pass | Observed behaviour matches `expect` |
| ❌ fail | Observed behaviour differs from `expect` |
| ⚠️ error | Case could not be evaluated: client cannot connect (for publish/receive), observer lacks rights, password variable missing |

A publish or receive case where the client cannot connect is an **error**, not a deny: a refused connection says nothing about topic rules.

For `receive`, the observer also subscribes to the concrete topic as a control. If the observer does not see its own message, the case is an error.

## Safety rules

- **`{probe}` placeholder:** Concrete topics must contain `{probe}`, which is replaced by a unique level such as `_aclprobe_3f9a1c`. Tasmota answers `cmnd/<topic>/_aclprobe_…` with "Unknown command" and does nothing. Cases on real topic names (e.g. `stat/<topic>/FILEDOWNLOAD`) must set `live: true` deliberately.
- **Never retained:** No test message is retained, so nothing stays on the broker.
- **Unique client IDs:** `<username>-aclprobe-<random>`. Reusing a live device's client ID would disconnect that device. Set `client_id` in an identity only if a rule depends on it – and remember that client-ID rules are no security boundary while devices share a user.
- **Passwords** come from environment variables only and are never printed.

## Limits

- A test shows behaviour for the topics tested, not for all topics. Deny cases for neighbouring topics (other device, other branch) matter as much as allow cases.
- Behaviour of existing connections after an ACL change is not covered yet.
- Wildcards: a `receive` case tests one concrete topic per filter. Add several cases for important branches.
