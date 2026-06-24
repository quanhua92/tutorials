//go:build ignore

// docker_k8s_deploy.go — Phase 8 bundle.
//
// GOAL (one line): show, by exercising the RUNNABLE mechanics (a /healthz +
// /readyz probe server and a graceful-termination simulation) and by DOCUMENTING
// the deployment artifacts (a multi-stage scratch Dockerfile and a k8s
// Deployment manifest with the three probes + preStop + grace period), how a Go
// service is built small and operated safely on Kubernetes.
//
// This is the GROUND TRUTH for DOCKER_K8S_DEPLOY.md. Every status code and
// [check] below is produced by this file; the .md guide pastes it verbatim. The
// Dockerfile and manifest are printed by Sections E and F (DOCUMENTED artifacts
// a developer applies; not executed from main()). Nothing is hand-computed.
//
// Determinism: httptest.NewRecorder drives the probe handlers with NO socket;
// the one real listener (Section C) uses a random loopback port we NEVER print.
// We print only status codes, error sentinels, and booleans — never elapsed
// time or addresses. Two `just out` runs are byte-identical.
//
// Run:
//
//	go run docker_k8s_deploy.go

package main

import (
	"context"
	"fmt"
	"net"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const bannerWidth = 70

var banner = strings.Repeat("=", bannerWidth)

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

// probeApp is a minimal service exposing the two endpoints a k8s probe hits:
//   - /healthz (liveness):  200 while the process can make progress; 503 if not.
//   - /readyz  (readiness): 200 only when warmed + deps connected; 503 otherwise.
//
// Two atomic flags model the two INDEPENDENT failure modes the probes detect:
// `alive` (liveness — is the process itself healthy?) and `ready` (readiness —
// is it able to serve traffic right now?). They are independent on purpose: a
// failing readiness must NOT take down liveness, and vice-versa.
type probeApp struct {
	alive atomic.Bool // liveness:  is the app itself healthy (making progress)?
	ready atomic.Bool // readiness: is it ready to serve traffic right now?
}

func (a *probeApp) healthzHandler(w http.ResponseWriter, r *http.Request) {
	if !a.alive.Load() {
		http.Error(w, "unhealthy", http.StatusServiceUnavailable) // 503
		return
	}
	w.WriteHeader(http.StatusOK) // 200
	_, _ = w.Write([]byte("alive"))
}

func (a *probeApp) readyzHandler(w http.ResponseWriter, r *http.Request) {
	if !a.ready.Load() {
		http.Error(w, "not ready", http.StatusServiceUnavailable) // 503
		return
	}
	w.WriteHeader(http.StatusOK) // 200
	_, _ = w.Write([]byte("ready"))
}

// newProbeMux wires the two handlers behind a Go 1.22 method+path pattern.
func newProbeMux(a *probeApp) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", a.healthzHandler)
	mux.HandleFunc("GET /readyz", a.readyzHandler)
	return mux
}

// sectionA pins the liveness-vs-readiness distinction: /healthz reflects
// "process alive" and /readyz reflects "ready to serve traffic". We toggle only
// readiness and assert liveness stays 200 the whole time. No socket: NewRecorder
// drives the handlers directly, so output is fully deterministic.
func sectionA() {
	sectionBanner("A — /healthz (liveness) vs /readyz (readiness)")

	app := &probeApp{}
	app.alive.Store(true)  // the process is up
	app.ready.Store(false) // ...but not yet ready (warming up / DB not connected)
	mux := newProbeMux(app)

	hit := func(path string) *httptest.ResponseRecorder {
		rec := httptest.NewRecorder()
		mux.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, path, nil))
		return rec
	}

	recH1 := hit("/healthz")
	recR1 := hit("/readyz")
	fmt.Printf("ready=false: GET /healthz -> %d   GET /readyz -> %d  (warming, not in Service)\n",
		recH1.Code, recR1.Code)

	// Dependencies come up / caches warm -> flip readiness ON. Liveness is untouched.
	app.ready.Store(true)
	recH2 := hit("/healthz")
	recR2 := hit("/readyz")
	fmt.Printf("ready=true : GET /healthz -> %d   GET /readyz -> %d  (now receiving traffic)\n",
		recH2.Code, recR2.Code)

	check("liveness /healthz is 200 even while NOT ready", recH1.Code == http.StatusOK)
	check("readiness /readyz is 503 when NOT ready", recR1.Code == http.StatusServiceUnavailable)
	check("liveness /healthz stays 200 once ready", recH2.Code == http.StatusOK)
	check("readiness /readyz is 200 once ready", recR2.Code == http.StatusOK)
	check("liveness never moved (200 both times)", recH1.Code == recH2.Code)
}

// sectionB shows the two FAILURE modes and maps each status code to its k8s
// consequence. A failing liveness -> kubelet RESTARTS the container; a failing
// readiness -> Pod removed from the Service (NO restart). We assert the codes
// and DOCUMENT the cluster-side action (a running program cannot make k8s
// restart itself, so the consequence is printed as a labeled fact, not a check).
func sectionB() {
	sectionBanner("B — Probe failure semantics -> k8s consequence")

	// 1) LIVENESS failure: the process is up but deadlocked/unhealthy.
	appLive := &probeApp{}
	appLive.alive.Store(false) // deadlock: liveness fails
	appLive.ready.Store(true)
	muxLive := newProbeMux(appLive)
	recL := httptest.NewRecorder()
	muxLive.ServeHTTP(recL, httptest.NewRequest(http.MethodGet, "/healthz", nil))
	fmt.Printf("liveness  /healthz -> %d  -> kubelet RESTARTS the container (after failureThreshold)\n",
		recL.Code)

	// 2) READINESS failure: process healthy, but a dependency is down / overloaded.
	appReady := &probeApp{}
	appReady.alive.Store(true)
	appReady.ready.Store(false) // dep down: readiness fails
	muxReady := newProbeMux(appReady)
	recR := httptest.NewRecorder()
	muxReady.ServeHTTP(recR, httptest.NewRequest(http.MethodGet, "/readyz", nil))
	fmt.Printf("readiness /readyz  -> %d  -> Pod removed from Service (NOT restarted)\n",
		recR.Code)

	// The k8s consequence table (DOCUMENTED; verbatim semantics from the probe docs).
	fmt.Println("probe type  on failure                          k8s action")
	fmt.Println("----------  --------------------------------    ------------------------------------------")
	fmt.Println("liveness    /healthz returns 503 (N times)       kubelet KILLS + restarts the container")
	fmt.Println("readiness   /readyz  returns 503                 Pod's IP removed from EndpointSlice (no traffic, still runs)")
	fmt.Println("startup     /healthz never succeeds in time     kubelet KILLS + restarts the container")

	check("liveness failure yields 503", recL.Code == http.StatusServiceUnavailable)
	check("readiness failure yields 503", recR.Code == http.StatusServiceUnavailable)
	check("both failure modes are 503 (k8s distinguishes by WHICH probe)", recL.Code == recR.Code)
}

// sectionC simulates the app side of the k8s graceful-termination sequence:
// preStop hook runs -> SIGTERM arrives -> the app stops accepting new conns,
// drains in-flight requests (http.Server.Shutdown) and its background worker,
// then exits cleanly BEFORE terminationGracePeriodSeconds (so SIGKILL never
// fires). We assert STATE (Shutdown err == nil, drained), never elapsed time.
func sectionC() {
	sectionBanner("C — Graceful termination: preStop -> SIGTERM -> Shutdown -> drain -> exit")

	// A real http.Server + listener so we can exercise http.Server.Shutdown
	// (the exact API a k8s Go app calls from its signal handler). The random
	// loopback port is NEVER printed.
	mux := http.NewServeMux()
	handling := make(chan struct{})
	var served atomic.Bool
	mux.HandleFunc("GET /work", func(w http.ResponseWriter, r *http.Request) {
		close(handling)                   // signal: the request is now in-flight
		time.Sleep(20 * time.Millisecond) // simulate an in-flight request doing work
		_, _ = w.Write([]byte("work done"))
		served.Store(true) // handler completed (drain proof)
	})

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		panic(err)
	}
	srv := &http.Server{Handler: mux}
	go func() { _ = srv.Serve(ln) }() // accept loop in the background
	baseURL := "http://" + ln.Addr().String()

	// A background worker with a fixed in-flight batch (drained on shutdown).
	var wg sync.WaitGroup
	var items atomic.Int64
	wg.Add(1)
	go func() {
		defer wg.Done()
		for i := 0; i < 3; i++ {
			time.Sleep(5 * time.Millisecond)
			items.Add(1)
		}
	}()

	// Open an in-flight request (the connection a client/probe established).
	client := &http.Client{Timeout: 2 * time.Second}
	go func() {
		resp, err := client.Get(baseURL + "/work")
		if err != nil {
			return
		}
		_ = resp.Body.Close()
	}()

	<-handling // the request is now being handled -> it MUST be drained

	// ---- Simulate the k8s termination sequence (app side) ----
	fmt.Println("STEP 1: pod marked Terminating; removed from Service endpoints (no new traffic)")
	fmt.Println("STEP 2: preStop hook executed (bridges endpoint-removal/SIGTERM propagation latency)")
	fmt.Println("STEP 3: SIGTERM delivered to PID 1  -> app stops accepting new connections, begins drain")

	// The app receives "SIGTERM" (here we simply begin Shutdown). Shutdown closes
	// the listener (no NEW conns) and waits for in-flight handlers to finish, with
	// a deadline STRICTLY LESS than terminationGracePeriodSeconds — the "drain
	// faster than the grace period" rule that guarantees no SIGKILL.
	const gracePeriod = 5 * time.Second             // spec.terminationGracePeriodSeconds
	const shutdownDeadline = 500 * time.Millisecond // < gracePeriod (NON-NEGOTIABLE)

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), shutdownDeadline)
	defer shutdownCancel()
	shutErr := srv.Shutdown(shutdownCtx) // drains the in-flight /work handler
	wg.Wait()                            // drain the background worker's in-flight batch

	fmt.Println("STEP 4: in-flight request drained; background worker drained")
	fmt.Printf("STEP 5: app exits cleanly (drained in %v < grace %v) -> no SIGKILL\n",
		shutdownDeadline, gracePeriod)
	fmt.Printf("        server.Shutdown(ctx) err = %v\n", shutErr)
	fmt.Printf("        background worker items drained = %d\n", items.Load())

	check("in-flight request drained (handler completed)", served.Load())
	check("background worker drained (finished batch of 3)", items.Load() == 3)
	check("server.Shutdown returned nil (drained within deadline)", shutErr == nil)
	check("graceful exit within grace period (no SIGKILL needed)", shutErr == nil)
}

// sectionD models the startup gate: a "warming" flag that gates readiness until
// the app has finished slow initialization. Before warm, readiness=503 (the Pod
// is NOT yet in the Service); after warm, readiness=200 (traffic flows). With a
// startupProbe configured, k8s suspends liveness/readiness until this gate opens.
func sectionD() {
	sectionBanner("D — Startup gate: readiness 503 -> 200 as the app warms up")

	type warmingApp struct{ warmed atomic.Bool }
	app := &warmingApp{}
	readyz := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if !app.warmed.Load() {
			http.Error(w, "warming up", http.StatusServiceUnavailable) // 503
			return
		}
		w.WriteHeader(http.StatusOK) // 200
		_, _ = w.Write([]byte("ready"))
	})

	probe := func() int {
		rec := httptest.NewRecorder()
		readyz.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/readyz", nil))
		return rec.Code
	}

	before := probe()
	fmt.Printf("before warm (still loading caches / connecting DB): /readyz -> %d\n", before)

	// Simulate slow startup finishing (a fixed, short warm-up). startupProbe gates
	// liveness+readiness until this moment so the slow start is not mistaken for a
	// liveness failure (which would restart the container mid-boot).
	time.Sleep(10 * time.Millisecond)
	app.warmed.Store(true)

	after := probe()
	fmt.Printf("after warm  (warmed up, deps connected):          /readyz -> %d\n", after)

	check("readiness is 503 while still warming", before == http.StatusServiceUnavailable)
	check("readiness transitions to 200 once warmed", after == http.StatusOK)
	check("the warm-up flipped readiness exactly once (503 -> 200)",
		before == http.StatusServiceUnavailable && after == http.StatusOK)
}

// sectionE DOCUMENTS the multi-stage Dockerfile (a build-time artifact). The .go
// prints it verbatim and asserts its key properties; a running program cannot
// `docker build`, so this is shown as the exact Dockerfile a developer applies,
// never executed from main(). CGO_ENABLED=0 produces a static binary -> scratch.
func sectionE() {
	sectionBanner("E — DOCKERFILE (documented): multi-stage, CGO_ENABLED=0, FROM scratch")
	fmt.Print(dockerfileDoc)
	fmt.Println("[properties]")
	check("Dockerfile is multi-stage (has an AS builder stage)",
		strings.Contains(dockerfileDoc, "AS builder"))
	check("builder disables CGO for a static binary (CGO_ENABLED=0)",
		strings.Contains(dockerfileDoc, "CGO_ENABLED=0"))
	check("builder targets linux (GOOS=linux)",
		strings.Contains(dockerfileDoc, "GOOS=linux"))
	check("final stage is FROM scratch (no OS, no shell)",
		strings.Contains(dockerfileDoc, "FROM scratch"))
	check("final stage runs as a non-root UID (USER 65532)",
		strings.Contains(dockerfileDoc, "USER 65532"))
	check("image documents its port (EXPOSE 8080)",
		strings.Contains(dockerfileDoc, "EXPOSE 8080"))
}

// sectionF DOCUMENTS the k8s Deployment manifest (a deployment artifact). It
// carries the three probes (startup gates liveness+readiness until up;
// liveness fail restarts; readiness fail removes from Service), a preStop hook,
// terminationGracePeriodSeconds >= drain time, and resource requests/limits.
func sectionF() {
	sectionBanner("F — K8S MANIFEST (documented): 3 probes + preStop + grace period")
	fmt.Print(manifestDoc)
	fmt.Println("[properties]")
	check("manifest sets terminationGracePeriodSeconds",
		strings.Contains(manifestDoc, "terminationGracePeriodSeconds"))
	check("manifest defines a startupProbe (gates liveness+readiness)",
		strings.Contains(manifestDoc, "startupProbe"))
	check("manifest defines a livenessProbe (failure -> restart)",
		strings.Contains(manifestDoc, "livenessProbe"))
	check("manifest defines a readinessProbe (failure -> removed from Service)",
		strings.Contains(manifestDoc, "readinessProbe"))
	check("manifest has a preStop lifecycle hook",
		strings.Contains(manifestDoc, "preStop"))
	check("probes use httpGet against /healthz and /readyz",
		strings.Contains(manifestDoc, "/healthz") && strings.Contains(manifestDoc, "/readyz"))
	check("manifest sets resource requests and limits",
		strings.Contains(manifestDoc, "requests") && strings.Contains(manifestDoc, "limits"))
}

// dockerfileDoc is the canonical Go multi-stage Dockerfile. Held in a const raw
// string (not a bare comment) so no tool misreads it as a real directive.
const dockerfileDoc = `
# syntax=docker/dockerfile:1
# =============================================================================
# Stage 1 (builder): compile a STATIC binary. CGO disabled => no libc link =>
# the binary runs in 'scratch' (which has zero shared libraries).
# =============================================================================
FROM golang:1.26-alpine AS builder
WORKDIR /src
# Cache deps: copy manifests first, download, THEN copy source.
COPY go.mod go.sum ./
RUN go mod download
COPY . .
# Static binary: -trimpath + -ldflags="-s -w" strip paths/symbols for a tiny
# reproducible image; -X injects the release version at link time.
RUN CGO_ENABLED=0 GOOS=linux go build \
      -trimpath -ldflags="-s -w -X main.version=v1.2.3" -o /out/app .

# =============================================================================
# Stage 2 (runtime): FROM scratch. ~5 MB image; no shell, no package manager,
# no libc -> minimal attack surface. A static Go binary + CA certs is all it has.
# (Alternative: FROM gcr.io/distroless/static:nonroot -> ships CA certs + tzdata
#  + a nonroot user (UID 65532); still no shell/package manager.)
# =============================================================================
FROM scratch
# CA certs so net/http can do TLS to external services (scratch ships none).
COPY --from=builder /etc/ssl/certs/ca-certificates.crt /etc/ssl/certs/
# The static binary (and only that).
COPY --from=builder /out/app /app
# Run as non-root (numeric UID works in scratch with no /etc/passwd).
USER 65532:65532
EXPOSE 8080
# No HEALTHCHECK: scratch has no shell/binary to run one. Rely on k8s probes.
ENTRYPOINT ["/app"]
`

// manifestDoc is a k8s Deployment wiring the three probes, a preStop hook, the
// grace period, resources, and env config — the production baseline.
const manifestDoc = `
apiVersion: apps/v1
kind: Deployment
metadata:
  name: app
spec:
  replicas: 3
  selector:
    matchLabels: { app: app }
  template:
    metadata:
      labels: { app: app }
    spec:
      terminationGracePeriodSeconds: 30   # SIGTERM..SIGKILL window (default 30s)
      containers:
        - name: app
          image: registry.example.com/app:v1.2.3
          ports:
            - { containerPort: 8080 }
          env:
            - { name: PORT, value: "8080" }
            - { name: LOG_LEVEL, value: "info" }
          # startupProbe GATES liveness+readiness until the app is up, so a slow
          # boot is not mistaken for a liveness failure. (failureThreshold x
          # periodSeconds = the max boot time the app is granted.)
          startupProbe:
            httpGet: { path: /healthz, port: 8080 }
            failureThreshold: 30            # 30 x 10s = up to 5 min to come up
            periodSeconds: 10
          # livenessProbe failure => kubelet RESTARTS the container.
          livenessProbe:
            httpGet: { path: /healthz, port: 8080 }
            periodSeconds: 10
            failureThreshold: 3
          # readinessProbe failure => Pod removed from the Service (NOT restarted).
          readinessProbe:
            httpGet: { path: /readyz, port: 8080 }
            periodSeconds: 5
            failureThreshold: 1
          lifecycle:
            preStop:
              exec:
                # scratch has no 'sleep': the binary ships its own grace-sleep
                # to bridge the endpoint-removal/SIGTERM propagation race.
                command: ["/app", "-grace-sleep", "5s"]
          resources:
            requests: { cpu: 100m, memory: 64Mi }
            limits:   { cpu: 500m, memory: 256Mi }
`

func main() {
	fmt.Println("docker_k8s_deploy.go — Phase 8 bundle.")
	fmt.Println("RUNNABLE: the /healthz vs /readyz probe server + the graceful-")
	fmt.Println("termination simulation. DOCUMENTED (Sections E,F): the multi-stage")
	fmt.Println("scratch Dockerfile and the k8s Deployment manifest. The .md guide")
	fmt.Println("pastes every status code and [check] verbatim. No real cluster;")
	fmt.Println("no printed ports/addresses/elapsed-time (deterministic output).")
	sectionA()
	sectionB()
	sectionC()
	sectionD()
	sectionE()
	sectionF()
	sectionBanner("DONE — all sections printed")
}
