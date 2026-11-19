# Topic inventory

Subscribing to `#` shows which topics exist, but not **who** published a message – MQTT does not carry that information. Only the broker knows. The `inventory` command reads broker logs and lists, per client, what it publishes and subscribes.

## Mosquitto

Enable debug logging (temporarily – it is verbose):

```
log_type all
log_timestamp true
```

Then let the system run for a while, ideally covering daily routines (backups, discovery after restart, scheduled rules), and evaluate:

```sh
mqtt-acl-verify inventory /var/log/mosquitto/mosquitto.log                 # Markdown
mqtt-acl-verify inventory mosquitto.log -f csv > inventory.csv             # CSV
mqtt-acl-verify inventory mosquitto.log --placeholders --by-user           # profile view
mqtt-acl-verify inventory mosquitto.log -p -u -x                           # same, without test traffic
```

| Option | Effect |
|---|---|
| `-p`, `--placeholders` | Replaces a topic level equal to the client's username by `%u` and equal to its client ID by `%c`. With the convention *username = Tasmota Topic*, `tele/kitchen/STATE` becomes `tele/%u/STATE`. |
| `-u`, `--by-user` | Merges all client IDs of a username into one row |
| `-x`, `--exclude-probes` | Drops traffic of mqtt-acl-verify's own test connections (client IDs `…-aclprobe-…`). Use it on production logs while tests ran. |

The unique probe levels of test messages (`_aclprobe_3f9a1c`) are always shown as `{probe}`, so repeated test runs collapse into one row.

Parsed log lines:

- `New client connected … as <clientid> (…, u'<username>')` – maps client ID to username
- `Received PUBLISH from <clientid> (…, '<topic>', …)` – publish
- `Denied PUBLISH from <clientid> (…)` – publish refused by the ACL
- `Received SUBSCRIBE from <clientid>` followed by `\t<filter> (QoS n)` – subscriptions

Clients that connected before logging started appear with username `?`. Restart them, or the broker, after enabling debug logging.

## Recommended procedure

1. **Observe:** debug logging on, no new restrictions.
2. **Derive profiles:** `--placeholders --by-user`, group similar clients.
3. **Write cases:** one allow case per needed topic, deny cases for neighbours.
4. **Restrict:** apply ACLs, run `mqtt-acl-verify run`, watch `publish-denied` rows in the inventory.

## EMQX 5

Planned: evaluation of client traces (`emqx ctl trace start client <clientid> …`).
