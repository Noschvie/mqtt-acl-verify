# autopaho reconnect probe

Go tests for the PMSS design: how does [`paho.golang/autopaho`](https://github.com/eclipse-paho/paho.golang) behave on the DynSec control topics when the connection drops while requests are pending?

The tests talk to `testbroker-dynsec/` (plain listener, user `dynsec-admin`) through a small TCP proxy. The proxy cuts the connection without DISCONNECT, refuses reconnects, or swallows broker → client traffic, so that a request reaches the broker but its PUBACK and response do not reach the client. Requests are matched by `correlationData` as in the PMSS design (map `correlationID → chan`).

```sh
cd testbroker-dynsec && ./setup.sh && cd ..
cd probes/autopaho-reconnect
go mod tidy          # first run: creates go.sum
MQTT_TEST_BROKER_DYNSEC=127.0.0.1:1884 go test -v ./...
```

Results and consequences: see [docs/testbroker-dynsec.md](../../docs/testbroker-dynsec.md#control-api-for-pmss).
