// SPDX-License-Identifier: AGPL-3.0-or-later

// Package reconnect checks how paho.golang/autopaho behaves on the DynSec
// control topics when the connection drops while requests are pending.
// PMSS design: autopaho manages the connection, requests are matched by
// correlationData (map correlationID -> chan), timeouts via context.
//
// A TCP proxy between client and broker cuts the connection at a chosen moment
// or swallows broker -> client traffic, so that a request reaches the broker
// but its PUBACK and response do not reach the client.
//
//	MQTT_TEST_BROKER_DYNSEC=127.0.0.1:1884 go test -v ./...
package reconnect

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/eclipse/paho.golang/autopaho"
	"github.com/eclipse/paho.golang/paho"
)

const (
	requestTopic  = "$CONTROL/dynamic-security/v1"
	responseTopic = "$CONTROL/dynamic-security/v1/response"
)

func env(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func broker(t *testing.T) string {
	addr := os.Getenv("MQTT_TEST_BROKER_DYNSEC")
	if addr == "" {
		t.Skip("MQTT_TEST_BROKER_DYNSEC not set (needs testbroker-dynsec/)")
	}
	return addr
}

// --- TCP proxy ---------------------------------------------------------------

type proxy struct {
	ln       net.Listener
	target   string
	refuse   atomic.Bool // close new connections immediately
	dropDown atomic.Bool // discard broker -> client bytes
	accepted atomic.Int32
	mu       sync.Mutex
	conns    []net.Conn
}

func newProxy(t *testing.T, target string) *proxy {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	p := &proxy{ln: ln, target: target}
	go p.serve()
	t.Cleanup(func() { ln.Close(); p.cut() })
	return p
}

func (p *proxy) url() *url.URL { return &url.URL{Scheme: "mqtt", Host: p.ln.Addr().String()} }

func (p *proxy) serve() {
	for {
		c, err := p.ln.Accept()
		if err != nil {
			return
		}
		if p.refuse.Load() {
			c.Close()
			continue
		}
		b, err := net.Dial("tcp", p.target)
		if err != nil {
			c.Close()
			continue
		}
		p.accepted.Add(1)
		p.mu.Lock()
		p.conns = append(p.conns, c, b)
		p.mu.Unlock()
		go func() { io.Copy(b, c); b.Close() }()
		go func() {
			buf := make([]byte, 32*1024)
			for {
				n, err := b.Read(buf)
				if n > 0 && !p.dropDown.Load() {
					if _, werr := c.Write(buf[:n]); werr != nil {
						break
					}
				}
				if err != nil {
					break
				}
			}
			c.Close()
		}()
	}
}

// cut closes all open connections (simulated network loss, no DISCONNECT).
func (p *proxy) cut() {
	p.mu.Lock()
	defer p.mu.Unlock()
	for _, c := range p.conns {
		c.Close()
	}
	p.conns = nil
}

// --- client with correlation map (as in the PMSS design) ---------------------

type response struct {
	Command         string          `json:"command"`
	Error           string          `json:"error,omitempty"`
	CorrelationData *string         `json:"correlationData,omitempty"`
	Data            json.RawMessage `json:"data,omitempty"`
}

type options struct {
	cleanStart    bool   // CleanStartOnInitialConnection
	sessionExpiry uint32 // SessionExpiryInterval
	subscribeOnUp bool   // subscribe in OnConnectionUp (on every connection)
}

type client struct {
	t       *testing.T
	cm      *autopaho.ConnectionManager
	ups     chan bool // SessionPresent of every CONNACK
	mu      sync.Mutex
	pending map[string]chan response
	unknown atomic.Int32
	seq     atomic.Int32
	id      string
}

func newClient(t *testing.T, srv *url.URL, o options) *client {
	c := &client{t: t, ups: make(chan bool, 16), pending: map[string]chan response{},
		id: fmt.Sprintf("probe-autopaho-%d", time.Now().UnixNano())}
	cfg := autopaho.ClientConfig{
		ServerUrls:                    []*url.URL{srv},
		KeepAlive:                     5,
		CleanStartOnInitialConnection: o.cleanStart,
		SessionExpiryInterval:         o.sessionExpiry,
		ReconnectBackoff:              func(int) time.Duration { return 200 * time.Millisecond },
		ConnectTimeout:                2 * time.Second,
		ConnectUsername:               env("MQTT_DYNSEC_ADMIN_USER", "dynsec-admin"),
		ConnectPassword:               []byte(env("MQTT_DYNSEC_ADMIN_PASSWORD", "test")),
		OnConnectionUp: func(cm *autopaho.ConnectionManager, ca *paho.Connack) {
			if o.subscribeOnUp {
				go func() { // must not block
					if _, err := cm.Subscribe(context.Background(), subscribePacket()); err != nil {
						t.Logf("subscribe in OnConnectionUp: %v", err)
					}
					c.ups <- ca.SessionPresent
				}()
				return
			}
			c.ups <- ca.SessionPresent
		},
		ClientConfig: paho.ClientConfig{
			ClientID:          c.id,
			OnPublishReceived: []func(paho.PublishReceived) (bool, error){c.onPublish},
		},
	}
	ctx, cancel := context.WithCancel(context.Background())
	cm, err := autopaho.NewConnection(ctx, cfg)
	if err != nil {
		t.Fatal(err)
	}
	c.cm = cm
	t.Cleanup(func() {
		dctx, dcancel := context.WithTimeout(context.Background(), time.Second)
		cm.Disconnect(dctx)
		dcancel()
		cancel()
	})
	c.waitUp(1)
	if !o.subscribeOnUp {
		if _, err := cm.Subscribe(context.Background(), subscribePacket()); err != nil {
			t.Fatal(err)
		}
	}
	return c
}

func subscribePacket() *paho.Subscribe {
	return &paho.Subscribe{Subscriptions: []paho.SubscribeOptions{{Topic: responseTopic, QoS: 1}}}
}

// waitUp waits for the n-th OnConnectionUp (counted from the last call) and
// returns its SessionPresent flag.
func (c *client) waitUp(n int) bool {
	var sp bool
	for range n {
		select {
		case sp = <-c.ups:
		case <-time.After(10 * time.Second):
			c.t.Fatal("no connection within 10s")
		}
	}
	return sp
}

func (c *client) onPublish(pr paho.PublishReceived) (bool, error) {
	var body struct{ Responses []response }
	if err := json.Unmarshal(pr.Packet.Payload, &body); err != nil {
		return true, nil
	}
	for _, r := range body.Responses {
		if r.CorrelationData == nil {
			c.unknown.Add(1)
			continue
		}
		c.mu.Lock()
		ch, ok := c.pending[*r.CorrelationData]
		c.mu.Unlock()
		if !ok {
			c.unknown.Add(1) // e.g. responses to other admins (broadcast)
			continue
		}
		select {
		case ch <- r:
		default:
		}
	}
	return true, nil
}

func (c *client) newID() string { return fmt.Sprintf("%s-%d", c.id, c.seq.Add(1)) }

// register a pending request; the channel buffers duplicate responses.
func (c *client) register(id string) chan response {
	ch := make(chan response, 4)
	c.mu.Lock()
	c.pending[id] = ch
	c.mu.Unlock()
	return ch
}

func (c *client) unregister(id string) {
	c.mu.Lock()
	delete(c.pending, id)
	c.mu.Unlock()
}

func (c *client) publish(ctx context.Context, id string, cmd map[string]any) error {
	cmd["correlationData"] = id
	payload, _ := json.Marshal(map[string]any{"commands": []any{cmd}})
	_, err := c.cm.Publish(ctx, &paho.Publish{Topic: requestTopic, QoS: 1, Payload: payload})
	return err
}

// request sends one command and waits for its response.
func (c *client) request(timeout time.Duration, cmd map[string]any) (response, error) {
	id := c.newID()
	ch := c.register(id)
	defer c.unregister(id)
	ctx, cancel := context.WithTimeout(context.Background(), timeout)
	defer cancel()
	if err := c.publish(ctx, id, cmd); err != nil {
		return response{}, fmt.Errorf("publish: %w", err)
	}
	select {
	case r := <-ch:
		return r, nil
	case <-ctx.Done():
		return response{}, ctx.Err()
	}
}

func probeName(prefix string) string {
	return fmt.Sprintf("probe-%s-%d", prefix, time.Now().UnixNano())
}

// --- tests -------------------------------------------------------------------

// Baseline: parallel requests on one response topic are matched correctly.
func TestParallelRequestsMatchedByCorrelationData(t *testing.T) {
	p := newProxy(t, broker(t))
	c := newClient(t, p.url(), options{cleanStart: true, subscribeOnUp: true})

	var wg sync.WaitGroup
	errs := make(chan error, 20)
	for i := range 20 {
		wg.Add(1)
		go func() {
			defer wg.Done()
			user := fmt.Sprintf("does-not-exist-%d", i)
			r, err := c.request(3*time.Second, map[string]any{"command": "getClient", "username": user})
			if err != nil {
				errs <- err
				return
			}
			if r.Command != "getClient" || r.Error != "Client not found" {
				errs <- fmt.Errorf("request %d: unexpected response %+v", i, r)
			}
		}()
	}
	wg.Wait()
	close(errs)
	for err := range errs {
		t.Error(err)
	}
}

// Does autopaho subscribe again after a reconnect? No: the subscription
// survives only in the broker session, otherwise OnConnectionUp must do it.
func TestResubscribeAfterReconnect(t *testing.T) {
	cases := []struct {
		name     string
		opts     options
		sessPres bool
		answered bool
	}{
		{"clean session, subscribed once", options{cleanStart: true}, false, false},
		{"clean session, subscribe in OnConnectionUp", options{cleanStart: true, subscribeOnUp: true}, false, true},
		{"session expiry 60s, subscribed once", options{cleanStart: true, sessionExpiry: 60}, true, true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p := newProxy(t, broker(t))
			c := newClient(t, p.url(), tc.opts)
			if _, err := c.request(2*time.Second, map[string]any{"command": "listRoles"}); err != nil {
				t.Fatalf("before reconnect: %v", err)
			}
			p.cut()
			if sp := c.waitUp(1); sp != tc.sessPres {
				t.Errorf("SessionPresent = %v, want %v", sp, tc.sessPres)
			}
			_, err := c.request(2*time.Second, map[string]any{"command": "listRoles"})
			if got := err == nil; got != tc.answered {
				t.Errorf("response after reconnect: got %v (err %v), want %v", got, err, tc.answered)
			}
		})
	}
}

// Publish while the connection is down does not wait for the reconnect: it
// fails immediately with ConnectionDownError. AwaitConnection waits.
func TestPublishWhileDisconnected(t *testing.T) {
	p := newProxy(t, broker(t))
	c := newClient(t, p.url(), options{cleanStart: true, subscribeOnUp: true})

	p.refuse.Store(true)
	p.cut()
	time.Sleep(300 * time.Millisecond) // autopaho notices the loss

	start := time.Now()
	_, err := c.request(5*time.Second, map[string]any{"command": "listRoles"})
	elapsed := time.Since(start)
	if !errors.Is(err, autopaho.ConnectionDownError) {
		t.Fatalf("err = %v, want ConnectionDownError", err)
	}
	if elapsed > time.Second {
		t.Errorf("Publish blocked for %v, expected an immediate error", elapsed)
	}
	t.Logf("Publish while down: %v after %v", err, elapsed.Round(time.Millisecond))

	p.refuse.Store(false)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := c.cm.AwaitConnection(ctx); err != nil {
		t.Fatal(err)
	}
	c.waitUp(1) // subscription in OnConnectionUp done
	if _, err := c.request(2*time.Second, map[string]any{"command": "listRoles"}); err != nil {
		t.Fatalf("after AwaitConnection: %v", err)
	}
}

// A request reaches the broker and is executed, but PUBACK and response are
// lost because the connection drops. What does the caller see, and is the
// command executed once or twice?
func TestPendingRequestDuringReconnect(t *testing.T) {
	cases := []struct {
		name string
		opts options
	}{
		{"clean session", options{cleanStart: true, subscribeOnUp: true}},
		{"session expiry 60s", options{cleanStart: true, sessionExpiry: 60, subscribeOnUp: true}},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			p := newProxy(t, broker(t))
			c := newClient(t, p.url(), tc.opts)
			name := probeName("pending")
			t.Cleanup(func() {
				c.request(2*time.Second, map[string]any{"command": "deleteClient", "username": name})
			})

			id := c.newID()
			ch := c.register(id)
			defer c.unregister(id)

			p.dropDown.Store(true)
			pubErr := make(chan error, 1)
			start := time.Now()
			var pubTime time.Duration
			go func() {
				ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
				defer cancel()
				err := c.publish(ctx, id, map[string]any{"command": "createClient", "username": name})
				pubTime = time.Since(start)
				pubErr <- err
			}()
			time.Sleep(500 * time.Millisecond) // broker executes, PUBACK + response swallowed
			p.cut()
			p.dropDown.Store(false)
			sp := c.waitUp(1)

			var perr error
			select {
			case perr = <-pubErr:
			case <-time.After(10 * time.Second):
				t.Fatal("Publish did not return")
			}

			var got []string
			timeout := time.After(2 * time.Second)
		collect:
			for {
				select {
				case r := <-ch:
					got = append(got, fmt.Sprintf("%q", r.Error))
				case <-timeout:
					break collect
				}
			}

			r, err := c.request(2*time.Second, map[string]any{"command": "getClient", "username": name})
			exists := err == nil && r.Error == ""
			t.Logf("SessionPresent=%v Publish err=%v after %v, responses after reconnect=%v, client exists=%v",
				sp, perr, pubTime.Round(100*time.Millisecond), got, exists)

			if !exists {
				t.Error("command was not executed")
			}
			report(t, tc.opts.sessionExpiry > 0, perr, got)
		})
	}
}

// report checks the observed behaviour (see README in this directory).
func report(t *testing.T, session bool, perr error, got []string) {
	t.Helper()
	if !session {
		// Clean session: the connection loss does not end Publish; it waits for
		// its context. The response is lost, there is no retransmission.
		if !errors.Is(perr, context.DeadlineExceeded) {
			t.Errorf("Publish err = %v, want context.DeadlineExceeded", perr)
		}
		if len(got) != 0 {
			t.Errorf("unexpected responses %v", got)
		}
		return
	}
	// Session kept: paho retransmits the PUBLISH (DUP), Mosquitto executes the
	// command a second time; only the answer to the repetition arrives.
	if perr != nil {
		t.Errorf("Publish err = %v, want nil (PUBACK of the retransmission)", perr)
	}
	if len(got) != 1 || got[0] != `"Client already exists"` {
		t.Errorf("responses = %v, want one \"Client already exists\"", got)
	}
}
