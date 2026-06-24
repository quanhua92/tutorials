//go:build ignore

// streaming_websockets.go — Phase 8 bundle (streaming: SSE + WebSockets).
//
// GOAL (one line): show, by driving an IN-PROCESS client against a loopback
// server, how Server-Sent Events (SSE) stream server->client over HTTP with
// http.Flusher, the SSE wire format (event/data/id/retry), and how WebSockets
// (github.com/coder/websocket) open a bidirectional, full-duplex channel via an
// HTTP Upgrade handshake — plus how a bounded buffer provides backpressure.
//
// This is the GROUND TRUTH for STREAMING_WEBSOCKETS.md. Every value below is
// computed by this file; the .md guide pastes it verbatim. Never hand-compute.
//
// DETERMINISM (critical — see HOW_TO_RESEARCH.md §4.2):
//   - httptest.NewServer runs on a RANDOM loopback port we NEVER print. The
//     in-process client connects via http.Get (SSE) and coder/websocket.Dial
//     (ws) to that URL; only the streamed MESSAGES are printed.
//   - SSE payloads, ws echo bytes, frame types, and close codes are FIXED
//     sequences. Collected sets are SORTED before printing.
//   - No time.Now() is ever printed; timeouts exist only to bound a blocked
//     call, never as a verified value. No real network and no browser.
//   - The websocket close handshake completes promptly: coder/websocket
//     auto-writes a close frame back when Read observes the peer's close frame
//     (read.go), so the graceful Close() does not stall on its 5s wait.
//   - Backpressure is demonstrated on a bounded channel with NO goroutines
//     (single-threaded, in-order) -> byte-identical across runs.
//
// STDLIB-FIRST + one allowed dep: github.com/coder/websocket (already in
// go.mod). Do NOT edit go.mod.
//
// Run:
//
//	go run streaming_websockets.go

package main

import (
	"bufio"
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"slices"
	"strings"
	"time"

	"github.com/coder/websocket"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth) // a const initializer cannot call a function, so this is a var

// sectionBanner prints a clearly delimited section divider (the house style).
func sectionBanner(title string) {
	fmt.Printf("\n%s\nSECTION %s\n%s\n", banner, title, banner)
}

// check asserts an invariant and prints a uniform "[check] ... OK" line.
// On failure it panics (non-zero exit) so `just check` / `just sweep` catch it.
func check(description string, ok bool) {
	if !ok {
		panic("INVARIANT VIOLATED: " + description)
	}
	fmt.Printf("[check] %s: OK\n", description)
}

// wsURL converts an httptest "http://127.0.0.1:<random>" URL to the ws:// scheme
// coder/websocket.Dial expects. (Dial also accepts http:// directly, but ws:// is
// explicit and matches the README examples.)
func wsURL(ts *httptest.Server) string { return "ws" + strings.TrimPrefix(ts.URL, "http") }

// echoWSHandler is the canonical coder/websocket server: Accept the handshake,
// then echo every message back with its original frame type until the peer
// closes (Read then errors). CloseNow (no close-handshake) keeps the demo fast.
func echoWSHandler(w http.ResponseWriter, r *http.Request) {
	c, err := websocket.Accept(w, r, nil)
	if err != nil {
		return
	}
	defer c.CloseNow()
	ctx, cancel := context.WithTimeout(r.Context(), 2*time.Second)
	defer cancel()
	for {
		typ, msg, err := c.Read(ctx)
		if err != nil {
			return
		}
		if err := c.Write(ctx, typ, msg); err != nil {
			return
		}
	}
}

// sectionA — SSE basics. A handler advertises Content-Type: text/event-stream,
// writes three "data: <payload>\n\n" events, and Flush()es after each so the
// bytes leave the server immediately (chunked transfer coding). The in-process
// client is a plain http.Get that reads the body line by line with a Scanner.
// We prove the ResponseWriter implements http.Flusher (the interface that makes
// streaming possible) and that the client received the 3 events as a set.
func sectionA() {
	sectionBanner("A — SSE basics: text/event-stream + http.Flusher + 3 events")

	flusherImplemented := make(chan bool, 1)
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// The SSE response contract: this Content-Type is what a browser's
		// EventSource (and our client) keys on; Cache-Control: no-cache stops
		// intermediaries from buffering the stream.
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")
		w.WriteHeader(http.StatusOK)

		// http.Flusher is the interface that lets a handler push bytes to the
		// wire BEFORE the handler returns. net/http's ResponseWriter implements
		// it; without asserting + calling Flush, the default buffering would
		// delay (or swallow) the streamed events.
		flusher, ok := w.(http.Flusher)
		flusherImplemented <- ok
		if !ok {
			return
		}
		for _, payload := range []string{"bravo", "alpha", "charlie"} {
			fmt.Fprintf(w, "data: %s\n\n", payload) // the SSE frame: data line + blank line
			flusher.Flush()                         // push now (do not wait for handler return)
		}
	}))
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/events")
	if err != nil {
		panic(err)
	}
	defer resp.Body.Close()

	// Read the streamed body line by line until EOF (handler return -> EOF).
	// The blank line that terminates each SSE event shows up here as "".
	var payloads []string
	sc := bufio.NewScanner(resp.Body)
	for sc.Scan() {
		line := sc.Text()
		if data, ok := strings.CutPrefix(line, "data: "); ok {
			payloads = append(payloads, data)
		}
	}
	if err := sc.Err(); err != nil {
		panic(err)
	}
	slices.Sort(payloads) // deterministic order regardless of arrival

	ct := resp.Header.Get("Content-Type")
	impl := <-flusherImplemented
	fmt.Printf("Content-Type received   : %q\n", ct)
	fmt.Printf("ResponseWriter is http.Flusher: %v\n", impl)
	fmt.Printf("client received %d data events (sorted): %v\n", len(payloads), payloads)

	check("Content-Type is text/event-stream", strings.HasPrefix(ct, "text/event-stream"))
	check("ResponseWriter implements http.Flusher", impl)
	check("client received exactly 3 events", len(payloads) == 3)
	check("sorted payloads == [alpha bravo charlie]", fmt.Sprint(payloads) == "[alpha bravo charlie]")
}

// sseEvent is one decoded SSE event. The default event type is "message".
type sseEvent struct {
	event string
	data  string
	id    string
}

// parseSSE decodes the text/event-stream wire format per the HTML spec
// (§9.2.5/§9.2.6). Blocks are separated by a blank line; within a block the
// fields are event/data/id/retry. Multiple "data:" lines join with "\n"; a
// trailing "\n" is stripped before dispatch. A pending block at EOF with no
// terminating blank line is discarded (spec: the incomplete event is not
// dispatched). This is exactly what a browser EventSource does internally.
func parseSSE(raw []byte) []sseEvent {
	var (
		events  []sseEvent
		cur     sseEvent
		dataBuf strings.Builder
	)
	dispatch := func() {
		// An empty block (no data/event/id) fires nothing.
		if dataBuf.Len() == 0 && cur.event == "" && cur.id == "" {
			return
		}
		s := dataBuf.String()
		s = strings.TrimSuffix(s, "\n") // spec: strip the single trailing LF
		cur.data = s
		events = append(events, cur)
		cur = sseEvent{}
		dataBuf.Reset()
	}
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimRight(line, "\r") // tolerate CRLF
		switch {
		case line == "":
			dispatch() // blank line terminates the event
		case strings.HasPrefix(line, ":"):
			// comment line — ignored (used as a keep-alive every ~15s)
		default:
			field, value, _ := strings.Cut(line, ":")
			value = strings.TrimPrefix(value, " ") // strip exactly one leading space
			switch field {
			case "event":
				cur.event = value
			case "data":
				dataBuf.WriteString(value)
				dataBuf.WriteByte('\n') // spec: append value then a LF
			case "id":
				cur.id = value
			case "retry":
				// reconnection time (ms) — parsed by the browser, not asserted here
			}
		}
	}
	// At EOF: any block without a terminating blank line is discarded (spec).
	return events
}

// sectionB — the SSE wire format. One block uses the full field set
// (event: tick / data: 42 / id: 7); another uses two "data:" lines to show how
// multi-line payloads join with "\n". We parse the raw body with parseSSE
// (the same algorithm a browser EventSource runs) and assert every field.
func sectionB() {
	sectionBanner("B — SSE wire format: event/data/id + multi-line data")

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.WriteHeader(http.StatusOK)
		flusher, ok := w.(http.Flusher)
		if !ok {
			return
		}
		// Block 1: a named "tick" event with a single data line and an id.
		// The id is replayed as the Last-Event-ID header on reconnect.
		io.WriteString(w, "event: tick\ndata: 42\nid: 7\n\n")
		flusher.Flush()
		// Block 2: multi-line data. The two "data:" lines concatenate with a
		// "\n" -> the client sees "line1\nline2".
		io.WriteString(w, "data: line1\ndata: line2\n\n")
		flusher.Flush()
		// Block 3: a comment (keep-alive) followed by a retry hint. The comment
		// is ignored; retry sets the browser's reconnect delay (ms).
		io.WriteString(w, ": this is a comment, ignored\nretry: 1234\n\n")
		flusher.Flush()
	}))
	defer ts.Close()

	resp, err := http.Get(ts.URL + "/fmt")
	if err != nil {
		panic(err)
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(resp.Body)
	if err != nil {
		panic(err)
	}
	events := parseSSE(raw)

	fmt.Printf("decoded %d SSE events from the stream:\n", len(events))
	for i, e := range events {
		fmt.Printf("  event#%d: type=%q data=%q id=%q\n", i, e.event, e.data, e.id)
	}

	check("exactly 2 dispatchable events (the comment/retry block has no data)", len(events) == 2)
	check("event#0 type == \"tick\"", events[0].event == "tick")
	check("event#0 data == \"42\"", events[0].data == "42")
	check("event#0 id == \"7\"", events[0].id == "7")
	check("event#1 multi-line data == \"line1\\nline2\"", events[1].data == "line1\nline2")
	check("event#1 has default type \"\" (no event: field)", events[1].event == "")
}

// sectionC — WebSocket basics. A server built on coder/websocket.Accept echoes
// every frame; an in-process client built on coder/websocket.Dial (to the
// loopback ws:// URL) sends one text message and reads the echo back. We assert
// the bytes round-trip and that the frame type is MessageText. (Dial sends no
// Origin header, so Accept's default same-origin check passes with nil options.)
func sectionC() {
	sectionBanner("C — WebSocket basics: Accept + Dial + echo (coder/websocket)")

	ts := httptest.NewServer(http.HandlerFunc(echoWSHandler))
	defer ts.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	c, _, err := websocket.Dial(ctx, wsURL(ts), nil)
	if err != nil {
		panic(err)
	}
	defer c.CloseNow()

	sent := []byte("hello-ws")
	if err := c.Write(ctx, websocket.MessageText, sent); err != nil {
		panic(err)
	}
	typ, got, err := c.Read(ctx)
	if err != nil {
		panic(err)
	}

	fmt.Printf("client sent %q as a text frame; server echoed back %q (type=%v)\n",
		sent, got, typ)
	check("echo: received the same bytes back", bytes.Equal(sent, got))
	check("echo frame type == MessageText", typ == websocket.MessageText)
}

// sectionD — WebSocket text vs binary frames. The same echo handler preserves
// the frame type, so a MessageText round-trips as MessageText and a
// MessageBinary (arbitrary bytes, incl. 0x00/0xFF) round-trips as MessageBinary.
// This is the binary capability SSE lacks (SSE is UTF-8 text only).
func sectionD() {
	sectionBanner("D — WebSocket frames: MessageText vs MessageBinary round-trip")

	ts := httptest.NewServer(http.HandlerFunc(echoWSHandler))
	defer ts.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	c, _, err := websocket.Dial(ctx, wsURL(ts), nil)
	if err != nil {
		panic(err)
	}
	defer c.CloseNow()

	textMsg := []byte("plain text")
	binMsg := []byte{0x00, 0xFF, 0x42, 0x01, 0xFE}

	// Text frame.
	if err := c.Write(ctx, websocket.MessageText, textMsg); err != nil {
		panic(err)
	}
	ttyp, tgot, err := c.Read(ctx)
	if err != nil {
		panic(err)
	}
	// Binary frame (note: 0x00/0xFF are NOT valid UTF-8 — fine for binary).
	if err := c.Write(ctx, websocket.MessageBinary, binMsg); err != nil {
		panic(err)
	}
	btyp, bgot, err := c.Read(ctx)
	if err != nil {
		panic(err)
	}

	fmt.Printf("text frame   -> sent %q, echoed type=%v, bytes equal=%v\n",
		textMsg, ttyp, bytes.Equal(textMsg, tgot))
	fmt.Printf("binary frame -> sent %v,  echoed type=%v, bytes equal=%v\n",
		binMsg, btyp, bytes.Equal(binMsg, bgot))

	check("text frame echoed with type MessageText", ttyp == websocket.MessageText)
	check("text frame bytes round-trip", bytes.Equal(textMsg, tgot))
	check("binary frame echoed with type MessageBinary", btyp == websocket.MessageBinary)
	check("binary frame bytes round-trip (incl. 0x00/0xFF)", bytes.Equal(binMsg, bgot))
}

// sectionE — the WebSocket close handshake. The server calls
// c.Close(StatusNormalClosure, "bye"): it writes a close frame (code 1000) and
// waits for the peer's close frame. The client's Read observes the close frame,
// returns a websocket.CloseError, AND coder/websocket auto-writes a close frame
// back — so the handshake completes promptly. We assert the status code via
// both websocket.CloseStatus and errors.As(&CloseError).
func sectionE() {
	sectionBanner("E — WebSocket close handshake: StatusNormalClosure (1000)")

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		defer c.CloseNow()
		// Initiate the graceful close: code 1000 + a short reason.
		c.Close(websocket.StatusNormalClosure, "bye")
	}))
	defer ts.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	c, _, err := websocket.Dial(ctx, wsURL(ts), nil)
	if err != nil {
		panic(err)
	}
	defer c.CloseNow()

	// Reading after the peer closed yields a CloseError wrapping the code.
	_, _, rerr := c.Read(ctx)

	st := websocket.CloseStatus(rerr)
	var ce websocket.CloseError
	isCloseErr := errors.As(rerr, &ce)
	fmt.Printf("client Read after server Close(1000,\"bye\") ->\n")
	fmt.Printf("  CloseStatus(err) = %d  (StatusNormalClosure = %d)\n", st, websocket.StatusNormalClosure)
	fmt.Printf("  errors.As(err, &CloseError) = %v  -> Code=%d Reason=%q\n",
		isCloseErr, ce.Code, ce.Reason)

	check("CloseStatus(err) == StatusNormalClosure", st == websocket.StatusNormalClosure)
	check("errors.As(err, &CloseError) succeeds", isCloseErr)
	check("CloseError.Code == 1000", ce.Code == websocket.StatusNormalClosure)
	check("CloseError.Reason == \"bye\"", ce.Reason == "bye")
}

// sectionF — (1) the SSE-vs-WebSocket decision (documented), including the
// browser EventSource API; (2) backpressure: a bounded channel throttles a fast
// producer when a slow consumer cannot keep up. Demonstrated single-threaded
// with a drop policy so the outcome is deterministic (no goroutine scheduling).
func sectionF() {
	sectionBanner("F — SSE vs WebSocket decision + backpressure (bounded buffer)")

	const (
		sseDirection = "server->client (one-way)"
		wsDirection  = "bidirectional (full-duplex)"
		sseTransport = "HTTP response stream (text/event-stream, chunked)"
		wsTransport  = "HTTP Upgrade handshake -> binary frames"
		sseReconnect = "built-in (EventSource auto-reconnect + Last-Event-ID)"
		wsReconnect  = "manual (the app must detect + re-dial)"
		sseDataKinds = "UTF-8 text only"
		wsDataKinds  = "text (UTF-8) and binary frames"
	)
	fmt.Println("SSE vs WebSocket — when to choose which:")
	fmt.Printf("  direction   : SSE=%-32s  WS=%s\n", sseDirection, wsDirection)
	fmt.Printf("  transport   : SSE=%s\n               WS=%s\n", sseTransport, wsTransport)
	fmt.Printf("  reconnect   : SSE=%s\n               WS=%s\n", sseReconnect, wsReconnect)
	fmt.Printf("  data kinds  : SSE=%-20s          WS=%s\n", sseDataKinds, wsDataKinds)
	fmt.Println("  rule of thumb: SSE for server-push (feeds, notifications, dashboards)")
	fmt.Println("                 WS  for interactive (chat, collaboration, multiplayer)")
	fmt.Println("browser SSE consumer (EventSource) — DOCUMENTED, not runnable here:")
	fmt.Println("  const es = new EventSource('/events');")
	fmt.Println("  es.onmessage = (e) => console.log(e.data);          // default 'message' events")
	fmt.Println("  es.addEventListener('tick', (e) => ...);            // named events (event: tick)")
	fmt.Println("  // reconnect is automatic; Last-Event-ID carries the id: field.")

	// --- backpressure: a bounded buffer caps a fast producer behind a slow consumer ---
	const cap = 2
	buf := make(chan string, cap) // the bounded buffer

	buf <- "m1"
	buf <- "m2" // buffer is now full (cap=2)

	// DROP policy: a non-blocking send that fails when full -> the producer is
	// NOT blocked; the overflowing message is dropped. (Alternative: a BLOCKING
	// send, which propagates backpressure to the producer.)
	dropped := false
	select {
	case buf <- "m3":
	default:
		dropped = true // consumer too slow -> buffer full -> drop
	}
	<-buf // consumer drains one item; a slot frees up

	// After a drain, a non-blocking send must succeed again.
	accepted := false
	select {
	case buf <- "m4":
		accepted = true
	default:
		accepted = false
	}

	// Drain whatever remains, deterministically.
	var remaining []string
loop:
	for {
		select {
		case m := <-buf:
			remaining = append(remaining, m)
		default:
			break loop
		}
	}
	slices.Sort(remaining)

	fmt.Printf("\nbackpressure demo (bounded chan, cap=%d, drop policy):\n", cap)
	fmt.Printf("  enqueued m1,m2 (buffer full); m3 send -> dropped=%v\n", dropped)
	fmt.Printf("  drained 1; m4 send -> accepted=%v\n", accepted)
	fmt.Printf("  remaining in buffer (sorted): %v\n", remaining)

	check("SSE is one-way (server->client)", sseDirection != wsDirection)
	check("WS is bidirectional (full-duplex)", strings.Contains(wsDirection, "bidirectional"))
	check("SSE data is text-only; WS supports binary", sseDataKinds != wsDataKinds)
	check("bounded buffer cap == 2", cap == 2)
	check("send while full was dropped (producer not blocked)", dropped)
	check("send after a drain was accepted", accepted)
	check("remaining buffer == [m2 m4] (m3 dropped, m4 enqueued)", fmt.Sprint(remaining) == "[m2 m4]")
}

func main() {
	fmt.Println("streaming_websockets.go — Phase 8 bundle (streaming: SSE + WebSockets).")
	fmt.Println("Every value below is produced by this file; the .md guide pastes it verbatim.")
	fmt.Println("Deterministic: in-process client + loopback server; random port never printed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
