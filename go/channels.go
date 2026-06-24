//go:build ignore

// channels.go — Phase 3 bundle #2 (channels).
//
// GOAL (one line): show, by printing every value, how Go channels behave —
// unbuffered rendezvous, buffered queues, close, range, nil channels, and the
// directional channel types — and prove the four channel axioms at run time.
//
// This is the GROUND TRUTH for CHANNELS.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// Run:
//
//	go run channels.go

package main

import (
	"fmt"
	"slices"
	"strings"
	"sync"
	"time"
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

// mustPanic runs fn under a defer/recover and reports whether it panicked,
// capturing the panic value as a string. It lets us PROVE (without aborting the
// whole program) that a send on — or a close of — a closed channel panics, and
// inspect the exact runtime message. Go has no `assert`; recover is the idiom.
func mustPanic(fn func()) (panicked bool, msg string) {
	defer func() {
		if r := recover(); r != nil {
			panicked = true
			msg = fmt.Sprint(r)
		}
	}()
	fn()
	return false, ""
}

// sectionA demonstrates the UNBUFFERED channel as a rendezvous: a send blocks
// until another goroutine receives (and vice-versa). Single producer => the
// values arrive at the consumer in send order (a deterministic handshake).
func sectionA() {
	sectionBanner("A — Unbuffered chan: a SEND blocks until a RECEIVE (rendezvous)")

	c := make(chan int) // no capacity => UNBUFFERED
	fmt.Printf("make(chan int): cap=%d len=%d   (unbuffered: capacity 0)\n", cap(c), len(c))
	check("unbuffered channel has capacity 0", cap(c) == 0)

	// PROBE: a non-blocking send on an unbuffered channel with NO receiver ready
	// cannot proceed, so the `default` case fires. This proves the send would
	// block until a receiver appears (the rendezvous is not complete).
	sent := false
	select {
	case c <- 1:
		sent = true
	default:
	}
	fmt.Println("probe send (no receiver): BLOCKED -> default fired (send cannot proceed alone)")
	check("unbuffered send with no receiver does not proceed (default fired)", !sent)

	// RENDEZVOUS: a single producer goroutine sends 0..4; main receives each.
	// Every send blocks until the matching receive -> the two sides "meet". With
	// one producer the values arrive in send order (no interleaving to sort).
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < 5; i++ {
			c <- i // blocks until main receives i
		}
	}()
	got := make([]int, 0, 5)
	for i := 0; i < 5; i++ {
		got = append(got, <-c) // blocks until producer sends
	}
	wg.Wait()
	fmt.Printf("rendezvous: producer sent 0..4, consumer received %v   (order preserved)\n", got)
	check("unbuffered rendezvous preserved send order [0 1 2 3 4]", fmt.Sprint(got) == "[0 1 2 3 4]")
}

// sectionB demonstrates the BUFFERED channel: a send blocks ONLY when the buffer
// is FULL; a receive blocks ONLY when it is EMPTY. cap(c) is the buffer size;
// len(c) is how many values are currently queued. Drain is FIFO.
func sectionB() {
	sectionBanner("B — Buffered chan: send blocks only when FULL")

	c := make(chan int, 3) // buffered, capacity 3
	fmt.Printf("make(chan int, 3): cap=%d\n", cap(c))

	// Three sends with NO receiver present do NOT block: the buffer is not full.
	c <- 1
	c <- 2
	c <- 3
	fmt.Printf("after 3 sends (no receiver): len=%d   (buffer full, sends did not block)\n", len(c))
	check("buffered channel cap==3", cap(c) == 3)
	check("buffered channel len==3 after 3 sends", len(c) == 3)

	// PROBE: a 4th send would block (buffer is full), so `default` fires.
	fourth := false
	select {
	case c <- 4:
		fourth = true
	default:
	}
	fmt.Println("probe 4th send: BLOCKED (buffer full) -> would block until a receive frees a slot")
	check("4th send to a full buffer-3 would block (default fired)", !fourth)

	// Drain in FIFO order — buffered channels are queues.
	d1, d2, d3 := <-c, <-c, <-c
	fmt.Printf("drain: <-c <-c <-c -> %d %d %d   (FIFO: 1 2 3)\n", d1, d2, d3)
	check("buffered drain is FIFO (1, 2, 3)", d1 == 1 && d2 == 2 && d3 == 3)
	check("buffered channel len==0 after draining", len(c) == 0)
}

// sectionC demonstrates close + range, and that close is a BROADCAST: closing
// unblocks EVERY receiver ranging the channel (all their `range` loops exit).
// Per the "sender closes" convention, only the writer goroutine closes here.
func sectionC() {
	sectionBanner("C — close + range (sender closes; close broadcasts to all receivers)")

	// Single consumer: producer sends 0..4 then closes; `range` collects until close.
	c := make(chan int, 5)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < 5; i++ {
			c <- i
		}
		close(c) // the SENDER closes (only the writer may close)
	}()
	var got []int
	for v := range c { // range exits when the channel is closed and drained
		got = append(got, v)
	}
	wg.Wait()
	fmt.Printf("single consumer, range over closed channel: %v\n", got)
	check("range collected [0 1 2 3 4] (exited on close)", fmt.Sprint(got) == "[0 1 2 3 4]")

	// BROADCAST: TWO consumers both range the SAME unbuffered channel. Which
	// consumer gets which value is nondeterministic, so we collect into a shared
	// slice (mutex-guarded) and SORT the union. The deterministic facts are:
	// (1) all 6 values are received exactly once; (2) on close BOTH consumers
	// exit their ranges (wg joins both) — that is the broadcast.
	bc := make(chan int)
	var mu sync.Mutex
	var all []int
	var wg2 sync.WaitGroup
	wg2.Add(1)
	go func() { // producer (the sole writer -> the sole closer)
		defer wg2.Done()
		for i := 0; i < 6; i++ {
			bc <- i
		}
		close(bc)
	}()
	const consumers = 2
	for k := 0; k < consumers; k++ {
		wg2.Add(1)
		go func() {
			defer wg2.Done()
			for v := range bc { // BOTH exit when bc is closed (the broadcast)
				mu.Lock()
				all = append(all, v)
				mu.Unlock()
			}
		}()
	}
	wg2.Wait()
	slices.Sort(all) // order between consumers is nondeterministic -> sort the union
	fmt.Printf("broadcast: %d consumers, sorted union of received values: %v\n", consumers, all)
	check("broadcast: close unblocked both consumers, sorted union == [0 1 2 3 4 5]",
		fmt.Sprint(all) == "[0 1 2 3 4 5]")
}

// sectionD proves the close-related axioms: receiving from a closed channel
// returns (zero value, ok==false); SENDING to a closed channel PANICS; closing
// an already-closed channel PANICS. Panics are observed via defer/recover.
func sectionD() {
	sectionBanner("D — close: receive returns (zero, false); send/close on closed PANIC")

	c := make(chan int, 1)
	c <- 7
	close(c)

	v1, ok1 := <-c // the one buffered value, delivered before close is observed
	v2, ok2 := <-c // closed AND empty -> the element zero value, ok==false
	fmt.Printf("after close: 1st recv  v=%d ok=%v   (the value sent before close)\n", v1, ok1)
	fmt.Printf("             2nd recv  v=%d ok=%v   (closed+empty -> zero value, false)\n", v2, ok2)
	check("1st receive after close returns the sent value 7 (ok==true)", v1 == 7 && ok1)
	check("2nd receive after close returns zero value 0 (ok==false)", v2 == 0 && !ok2)

	// AXIOM (Dave Cheney): a send on a closed channel PANICS.
	sendPanicked, sendMsg := mustPanic(func() { c <- 9 })
	fmt.Printf("axiom: send on closed channel  -> panic=%v  msg=%q\n", sendPanicked, sendMsg)
	check("axiom: send on closed channel panics (\"send on closed channel\")",
		sendPanicked && strings.Contains(sendMsg, "send on closed channel"))

	// AXIOM (Dave Cheney): closing an already-closed channel PANICS.
	closePanicked, closeMsg := mustPanic(func() { close(c) })
	fmt.Printf("axiom: close of closed channel -> panic=%v  msg=%q\n", closePanicked, closeMsg)
	check("axiom: close of closed channel panics (\"close of closed channel\")",
		closePanicked && strings.Contains(closeMsg, "close of closed channel"))
}

// sectionE proves the nil-channel axiom: a nil channel is NEVER ready, so a send
// or receive on it blocks FOREVER. We observe "never ready" deterministically
// with select+timeout (the nil case can never win) and a non-blocking probe.
func sectionE() {
	sectionBanner("E — nil channel: send/receive blocks FOREVER")

	var c chan int // uninitialized -> nil (the zero value of a channel type)
	fmt.Printf("var c chan int -> c==nil: %v   cap=%d len=%d\n", c == nil, cap(c), len(c))
	check("uninitialized channel is nil", c == nil)
	check("cap(nil channel)==0", cap(c) == 0)
	check("len(nil channel)==0", len(c) == 0)

	// A nil receive can never proceed; only the timeout can win. In a plain
	// (non-select) `<-c` this would block forever (= deadlock the goroutine).
	timedOut := false
	select {
	case <-c:
	case <-time.After(20 * time.Millisecond):
		timedOut = true
	}
	fmt.Println("nil receive: select timed out after 20ms (nil channel never ready -> blocks forever)")
	check("nil channel receive never becomes ready (timeout won)", timedOut)

	// Symmetric on the send side: a non-blocking send probe also cannot proceed.
	sendBlocked := false
	select {
	case c <- 1:
	default:
		sendBlocked = true // the nil send case is never selected
	}
	fmt.Println("nil send probe: BLOCKED -> default fired (nil send never ready -> blocks forever)")
	check("nil channel send never becomes ready (default fired)", sendBlocked)
}

// onlySend takes a SEND-ONLY channel and sends on it. The directional type makes
// "who is allowed to send" a compile-time fact, not a convention.
func onlySend(c chan<- int, v int) { c <- v }

// onlyRecv takes a RECEIVE-ONLY channel and returns the next value.
func onlyRecv(c <-chan int) int { return <-c }

// sectionF demonstrates the DIRECTIONAL channel types: chan<- T (send-only) and
// <-chan T (receive-only). A bidirectional channel converts to either by
// assignment; the direction is then enforced by the compiler.
func sectionF() {
	sectionBanner("F — Directional types: chan<- (send-only) & <-chan (receive-only)")

	c := make(chan int, 1) // bidirectional
	var s chan<- int = c   // assign bidirectional -> send-only
	var r <-chan int = c   // assign bidirectional -> receive-only
	fmt.Printf("type of c: %T   (bidirectional)\n", c)
	fmt.Printf("type of s: %T   (send-only)\n", s)
	fmt.Printf("type of r: %T   (receive-only)\n", r)
	check("s is send-only chan<- int", fmt.Sprintf("%T", s) == "chan<- int")
	check("r is receive-only <-chan int", fmt.Sprintf("%T", r) == "<-chan int")

	onlySend(s, 42) // send-only param accepts the send-only value
	got := onlyRecv(r)
	fmt.Printf("onlySend(s, 42) then onlyRecv(r) -> %d   (directional round-trip)\n", got)
	check("directional send/receive round-tripped 42", got == 42)

	// DOCUMENTED compile errors (a file containing these would not build):
	//   <-s       // invalid operation: cannot receive from send-only channel chan<- int
	//   r <- 1    // invalid operation: cannot send to receive-only channel <-chan int
	fmt.Println("COMPILE ERROR (documented): <-s       // cannot receive from send-only channel chan<- int")
	fmt.Println("COMPILE ERROR (documented): r <- 1    // cannot send to receive-only channel <-chan int")
}

func main() {
	fmt.Println("channels.go — Phase 3 bundle #2 (channels).")
	fmt.Println("Every value below is computed by this file; the .md guide pastes")
	fmt.Println("it verbatim. Nothing is hand-computed.")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
