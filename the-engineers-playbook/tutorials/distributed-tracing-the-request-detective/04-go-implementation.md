# Go Implementation: Production-Ready Distributed Tracing

## Overview

This implementation provides a production-ready distributed tracing system in Go, showcasing real-world patterns and best practices. We'll build a complete system with automatic instrumentation, context propagation, and observability.

## Project Structure

```
distributed-tracing/
├── cmd/
│   ├── api-gateway/
│   │   └── main.go
│   ├── user-service/
│   │   └── main.go
│   ├── order-service/
│   │   └── main.go
│   └── trace-collector/
│       └── main.go
├── pkg/
│   ├── tracing/
│   │   ├── context.go
│   │   ├── span.go
│   │   ├── tracer.go
│   │   └── collector.go
│   ├── instrumentation/
│   │   ├── http.go
│   │   ├── database.go
│   │   └── grpc.go
│   └── sampling/
│       ├── probabilistic.go
│       ├── adaptive.go
│       └── tail_based.go
├── go.mod
└── go.sum
```

## Core Tracing Framework

### Trace Context Implementation

```go
// pkg/tracing/context.go
package tracing

import (
    "context"
    "crypto/rand"
    "encoding/hex"
    "fmt"
    "strconv"
    "strings"
    "sync"
    "time"
)

type TraceContext struct {
    TraceID      string            `json:"trace_id"`
    SpanID       string            `json:"span_id"`
    ParentSpanID string            `json:"parent_span_id,omitempty"`
    Baggage      map[string]string `json:"baggage,omitempty"`
    Flags        TraceFlags        `json:"flags"`
    mutex        sync.RWMutex
}

type TraceFlags struct {
    Sampled bool `json:"sampled"`
    Debug   bool `json:"debug"`
}

const (
    TraceParentHeader = "traceparent"
    TraceStateHeader  = "tracestate"
    BaggageHeader     = "baggage"
)

func NewTraceContext() *TraceContext {
    return &TraceContext{
        TraceID: generateTraceID(),
        SpanID:  generateSpanID(),
        Baggage: make(map[string]string),
        Flags:   TraceFlags{Sampled: true},
    }
}

func (tc *TraceContext) CreateChildContext() *TraceContext {
    tc.mutex.RLock()
    defer tc.mutex.RUnlock()
    
    return &TraceContext{
        TraceID:      tc.TraceID,
        SpanID:       generateSpanID(),
        ParentSpanID: tc.SpanID,
        Baggage:      copyBaggage(tc.Baggage),
        Flags:        tc.Flags,
    }
}

func (tc *TraceContext) SetBaggage(key, value string) {
    tc.mutex.Lock()
    defer tc.mutex.Unlock()
    
    if tc.Baggage == nil {
        tc.Baggage = make(map[string]string)
    }
    tc.Baggage[key] = value
}

func (tc *TraceContext) GetBaggage(key string) (string, bool) {
    tc.mutex.RLock()
    defer tc.mutex.RUnlock()
    
    value, exists := tc.Baggage[key]
    return value, exists
}

func (tc *TraceContext) ToTraceParent() string {
    tc.mutex.RLock()
    defer tc.mutex.RUnlock()
    
    var flags byte
    if tc.Flags.Sampled {
        flags |= 0x01
    }
    if tc.Flags.Debug {
        flags |= 0x02
    }
    
    return fmt.Sprintf("00-%s-%s-%02x", tc.TraceID, tc.SpanID, flags)
}

func FromTraceParent(traceparent string) (*TraceContext, error) {
    parts := strings.Split(traceparent, "-")
    if len(parts) != 4 {
        return nil, fmt.Errorf("invalid traceparent format")
    }
    
    if parts[0] != "00" {
        return nil, fmt.Errorf("unsupported traceparent version: %s", parts[0])
    }
    
    flags, err := strconv.ParseUint(parts[3], 16, 8)
    if err != nil {
        return nil, fmt.Errorf("invalid flags: %v", err)
    }
    
    return &TraceContext{
        TraceID:      parts[1],
        SpanID:       parts[2],
        ParentSpanID: parts[2], // This becomes the parent for child spans
        Baggage:      make(map[string]string),
        Flags: TraceFlags{
            Sampled: (flags & 0x01) != 0,
            Debug:   (flags & 0x02) != 0,
        },
    }, nil
}

func generateTraceID() string {
    bytes := make([]byte, 16)
    rand.Read(bytes)
    return hex.EncodeToString(bytes)
}

func generateSpanID() string {
    bytes := make([]byte, 8)
    rand.Read(bytes)
    return hex.EncodeToString(bytes)
}

func copyBaggage(original map[string]string) map[string]string {
    copy := make(map[string]string)
    for k, v := range original {
        copy[k] = v
    }
    return copy
}
```

### Span Implementation

```go
// pkg/tracing/span.go
package tracing

import (
    "context"
    "encoding/json"
    "sync"
    "time"
)

type Span struct {
    TraceID       string            `json:"trace_id"`
    SpanID        string            `json:"span_id"`
    ParentSpanID  string            `json:"parent_span_id,omitempty"`
    OperationName string            `json:"operation_name"`
    ServiceName   string            `json:"service_name"`
    StartTime     time.Time         `json:"start_time"`
    EndTime       time.Time         `json:"end_time"`
    Duration      time.Duration     `json:"duration"`
    Status        SpanStatus        `json:"status"`
    Tags          map[string]string `json:"tags"`
    Events        []SpanEvent       `json:"events"`
    mutex         sync.RWMutex
    finished      bool
}

type SpanStatus struct {
    Code    StatusCode `json:"code"`
    Message string     `json:"message"`
}

type StatusCode int

const (
    StatusOK StatusCode = iota
    StatusError
    StatusTimeout
    StatusCancelled
)

type SpanEvent struct {
    Name      string            `json:"name"`
    Timestamp time.Time         `json:"timestamp"`
    Attrs     map[string]string `json:"attributes"`
}

func NewSpan(operationName, serviceName string, traceCtx *TraceContext) *Span {
    return &Span{
        TraceID:       traceCtx.TraceID,
        SpanID:        traceCtx.SpanID,
        ParentSpanID:  traceCtx.ParentSpanID,
        OperationName: operationName,
        ServiceName:   serviceName,
        StartTime:     time.Now(),
        Status:        SpanStatus{Code: StatusOK, Message: "OK"},
        Tags:          make(map[string]string),
        Events:        make([]SpanEvent, 0),
    }
}

func (s *Span) SetTag(key, value string) *Span {
    s.mutex.Lock()
    defer s.mutex.Unlock()
    
    if s.finished {
        return s
    }
    
    s.Tags[key] = value
    return s
}

func (s *Span) SetStatus(code StatusCode, message string) *Span {
    s.mutex.Lock()
    defer s.mutex.Unlock()
    
    if s.finished {
        return s
    }
    
    s.Status.Code = code
    s.Status.Message = message
    return s
}

func (s *Span) AddEvent(name string, attrs map[string]string) *Span {
    s.mutex.Lock()
    defer s.mutex.Unlock()
    
    if s.finished {
        return s
    }
    
    event := SpanEvent{
        Name:      name,
        Timestamp: time.Now(),
        Attrs:     attrs,
    }
    
    s.Events = append(s.Events, event)
    return s
}

func (s *Span) Finish() {
    s.mutex.Lock()
    defer s.mutex.Unlock()
    
    if s.finished {
        return
    }
    
    s.EndTime = time.Now()
    s.Duration = s.EndTime.Sub(s.StartTime)
    s.finished = true
    
    // Send to collector
    GlobalCollector.Collect(s)
}

func (s *Span) Context() *TraceContext {
    s.mutex.RLock()
    defer s.mutex.RUnlock()
    
    return &TraceContext{
        TraceID:      s.TraceID,
        SpanID:       s.SpanID,
        ParentSpanID: s.ParentSpanID,
        Baggage:      make(map[string]string),
        Flags:        TraceFlags{Sampled: true},
    }
}

func (s *Span) IsFinished() bool {
    s.mutex.RLock()
    defer s.mutex.RUnlock()
    return s.finished
}

func (s *Span) MarshalJSON() ([]byte, error) {
    s.mutex.RLock()
    defer s.mutex.RUnlock()
    
    type Alias Span
    return json.Marshal((*Alias)(s))
}
```

### Tracer Implementation

```go
// pkg/tracing/tracer.go
package tracing

import (
    "context"
    "net/http"
    "sync"
)

type Tracer struct {
    serviceName string
    sampler     Sampler
    mutex       sync.RWMutex
}

type Sampler interface {
    ShouldSample(traceID string, operationName string, tags map[string]string) bool
}

var GlobalTracer *Tracer

func NewTracer(serviceName string, sampler Sampler) *Tracer {
    return &Tracer{
        serviceName: serviceName,
        sampler:     sampler,
    }
}

func InitGlobalTracer(serviceName string, sampler Sampler) {
    GlobalTracer = NewTracer(serviceName, sampler)
}

func (t *Tracer) StartSpan(operationName string, opts ...SpanOption) *Span {
    options := &SpanOptions{}
    for _, opt := range opts {
        opt(options)
    }
    
    var traceCtx *TraceContext
    if options.Parent != nil {
        traceCtx = options.Parent.CreateChildContext()
    } else {
        traceCtx = NewTraceContext()
    }
    
    // Apply sampling
    if !t.sampler.ShouldSample(traceCtx.TraceID, operationName, options.Tags) {
        traceCtx.Flags.Sampled = false
    }
    
    span := NewSpan(operationName, t.serviceName, traceCtx)
    
    // Apply options
    for key, value := range options.Tags {
        span.SetTag(key, value)
    }
    
    return span
}

func (t *Tracer) StartSpanFromContext(ctx context.Context, operationName string, opts ...SpanOption) (*Span, context.Context) {
    var parentCtx *TraceContext
    if parent := SpanFromContext(ctx); parent != nil {
        parentCtx = parent.Context()
    }
    
    options := &SpanOptions{Parent: parentCtx}
    for _, opt := range opts {
        opt(options)
    }
    
    span := t.StartSpan(operationName, WithParent(parentCtx))
    
    // Apply options
    for key, value := range options.Tags {
        span.SetTag(key, value)
    }
    
    return span, ContextWithSpan(ctx, span)
}

func (t *Tracer) ExtractFromHTTPRequest(req *http.Request) *TraceContext {
    traceparent := req.Header.Get(TraceParentHeader)
    if traceparent == "" {
        return nil
    }
    
    traceCtx, err := FromTraceParent(traceparent)
    if err != nil {
        return nil
    }
    
    return traceCtx
}

func (t *Tracer) InjectToHTTPRequest(req *http.Request, traceCtx *TraceContext) {
    req.Header.Set(TraceParentHeader, traceCtx.ToTraceParent())
}

// Context helpers
type spanContextKey struct{}

func ContextWithSpan(ctx context.Context, span *Span) context.Context {
    return context.WithValue(ctx, spanContextKey{}, span)
}

func SpanFromContext(ctx context.Context) *Span {
    if span, ok := ctx.Value(spanContextKey{}).(*Span); ok {
        return span
    }
    return nil
}

// Span options
type SpanOptions struct {
    Parent *TraceContext
    Tags   map[string]string
}

type SpanOption func(*SpanOptions)

func WithParent(parent *TraceContext) SpanOption {
    return func(opts *SpanOptions) {
        opts.Parent = parent
    }
}

func WithTags(tags map[string]string) SpanOption {
    return func(opts *SpanOptions) {
        if opts.Tags == nil {
            opts.Tags = make(map[string]string)
        }
        for k, v := range tags {
            opts.Tags[k] = v
        }
    }
}

func WithTag(key, value string) SpanOption {
    return func(opts *SpanOptions) {
        if opts.Tags == nil {
            opts.Tags = make(map[string]string)
        }
        opts.Tags[key] = value
    }
}
```

### Collector Implementation

```go
// pkg/tracing/collector.go
package tracing

import (
    "bytes"
    "encoding/json"
    "fmt"
    "log"
    "net/http"
    "sync"
    "time"
)

type Collector struct {
    endpoint    string
    batchSize   int
    flushInterval time.Duration
    spans       []*Span
    mutex       sync.Mutex
    client      *http.Client
    stopChan    chan struct{}
    started     bool
}

var GlobalCollector *Collector

func NewCollector(endpoint string, batchSize int, flushInterval time.Duration) *Collector {
    return &Collector{
        endpoint:     endpoint,
        batchSize:    batchSize,
        flushInterval: flushInterval,
        spans:        make([]*Span, 0, batchSize),
        client:       &http.Client{Timeout: 10 * time.Second},
        stopChan:     make(chan struct{}),
    }
}

func InitGlobalCollector(endpoint string, batchSize int, flushInterval time.Duration) {
    GlobalCollector = NewCollector(endpoint, batchSize, flushInterval)
    GlobalCollector.Start()
}

func (c *Collector) Start() {
    c.mutex.Lock()
    defer c.mutex.Unlock()
    
    if c.started {
        return
    }
    
    c.started = true
    go c.flushLoop()
}

func (c *Collector) Stop() {
    c.mutex.Lock()
    defer c.mutex.Unlock()
    
    if !c.started {
        return
    }
    
    close(c.stopChan)
    c.flush() // Final flush
    c.started = false
}

func (c *Collector) Collect(span *Span) {
    if span == nil || !span.Context().Flags.Sampled {
        return
    }
    
    c.mutex.Lock()
    defer c.mutex.Unlock()
    
    c.spans = append(c.spans, span)
    
    if len(c.spans) >= c.batchSize {
        c.flush()
    }
}

func (c *Collector) flushLoop() {
    ticker := time.NewTicker(c.flushInterval)
    defer ticker.Stop()
    
    for {
        select {
        case <-ticker.C:
            c.mutex.Lock()
            if len(c.spans) > 0 {
                c.flush()
            }
            c.mutex.Unlock()
        case <-c.stopChan:
            return
        }
    }
}

func (c *Collector) flush() {
    if len(c.spans) == 0 {
        return
    }
    
    // Copy spans to avoid holding lock during network call
    spans := make([]*Span, len(c.spans))
    copy(spans, c.spans)
    c.spans = c.spans[:0]
    
    // Send asynchronously to avoid blocking
    go c.sendSpans(spans)
}

func (c *Collector) sendSpans(spans []*Span) {
    payload := map[string]interface{}{
        "spans": spans,
        "timestamp": time.Now(),
    }
    
    data, err := json.Marshal(payload)
    if err != nil {
        log.Printf("Failed to marshal spans: %v", err)
        return
    }
    
    req, err := http.NewRequest("POST", c.endpoint, bytes.NewBuffer(data))
    if err != nil {
        log.Printf("Failed to create request: %v", err)
        return
    }
    
    req.Header.Set("Content-Type", "application/json")
    
    resp, err := c.client.Do(req)
    if err != nil {
        log.Printf("Failed to send spans: %v", err)
        return
    }
    defer resp.Body.Close()
    
    if resp.StatusCode != http.StatusOK {
        log.Printf("Collector returned status %d", resp.StatusCode)
    }
}
```

## HTTP Instrumentation

```go
// pkg/instrumentation/http.go
package instrumentation

import (
    "context"
    "fmt"
    "net/http"
    "strconv"
    "time"
    
    "your-project/pkg/tracing"
)

type HTTPInstrumentation struct {
    tracer *tracing.Tracer
}

func NewHTTPInstrumentation(tracer *tracing.Tracer) *HTTPInstrumentation {
    return &HTTPInstrumentation{tracer: tracer}
}

// Server middleware
func (h *HTTPInstrumentation) ServerMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        // Extract trace context from headers
        traceCtx := h.tracer.ExtractFromHTTPRequest(r)
        
        // Create span for this request
        var span *tracing.Span
        var ctx context.Context
        
        if traceCtx != nil {
            span = h.tracer.StartSpan(fmt.Sprintf("%s %s", r.Method, r.URL.Path), 
                tracing.WithParent(traceCtx))
        } else {
            span, ctx = h.tracer.StartSpanFromContext(r.Context(), 
                fmt.Sprintf("%s %s", r.Method, r.URL.Path))
        }
        
        // Add HTTP tags
        span.SetTag("http.method", r.Method)
        span.SetTag("http.url", r.URL.String())
        span.SetTag("http.scheme", r.URL.Scheme)
        span.SetTag("http.host", r.Host)
        span.SetTag("http.user_agent", r.UserAgent())
        span.SetTag("http.remote_addr", r.RemoteAddr)
        
        // Wrap response writer to capture status code
        wrapped := &responseWriter{ResponseWriter: w, statusCode: 200}
        
        // Add span to context
        ctx = tracing.ContextWithSpan(r.Context(), span)
        
        // Call next handler
        start := time.Now()
        next.ServeHTTP(wrapped, r.WithContext(ctx))
        
        // Finish span
        span.SetTag("http.status_code", strconv.Itoa(wrapped.statusCode))
        span.SetTag("http.response_size", strconv.FormatInt(wrapped.bytesWritten, 10))
        
        if wrapped.statusCode >= 400 {
            span.SetStatus(tracing.StatusError, fmt.Sprintf("HTTP %d", wrapped.statusCode))
        }
        
        span.AddEvent("http.response", map[string]string{
            "duration": time.Since(start).String(),
            "status_code": strconv.Itoa(wrapped.statusCode),
        })
        
        span.Finish()
    })
}

// Client instrumentation
func (h *HTTPInstrumentation) RoundTripper(next http.RoundTripper) http.RoundTripper {
    return &instrumentedRoundTripper{
        next:   next,
        tracer: h.tracer,
    }
}

type instrumentedRoundTripper struct {
    next   http.RoundTripper
    tracer *tracing.Tracer
}

func (rt *instrumentedRoundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
    span := tracing.SpanFromContext(req.Context())
    if span == nil {
        return rt.next.RoundTrip(req)
    }
    
    // Create child span for the HTTP call
    childSpan := rt.tracer.StartSpan(fmt.Sprintf("HTTP %s", req.Method),
        tracing.WithParent(span.Context()))
    
    childSpan.SetTag("http.method", req.Method)
    childSpan.SetTag("http.url", req.URL.String())
    childSpan.SetTag("component", "http-client")
    
    // Inject trace context into request
    rt.tracer.InjectToHTTPRequest(req, childSpan.Context())
    
    // Make the request
    start := time.Now()
    resp, err := rt.next.RoundTrip(req)
    
    if err != nil {
        childSpan.SetStatus(tracing.StatusError, err.Error())
        childSpan.AddEvent("http.error", map[string]string{
            "error": err.Error(),
        })
    } else {
        childSpan.SetTag("http.status_code", strconv.Itoa(resp.StatusCode))
        if resp.StatusCode >= 400 {
            childSpan.SetStatus(tracing.StatusError, fmt.Sprintf("HTTP %d", resp.StatusCode))
        }
    }
    
    childSpan.AddEvent("http.request_completed", map[string]string{
        "duration": time.Since(start).String(),
    })
    
    childSpan.Finish()
    
    return resp, err
}

type responseWriter struct {
    http.ResponseWriter
    statusCode   int
    bytesWritten int64
}

func (rw *responseWriter) WriteHeader(code int) {
    rw.statusCode = code
    rw.ResponseWriter.WriteHeader(code)
}

func (rw *responseWriter) Write(b []byte) (int, error) {
    n, err := rw.ResponseWriter.Write(b)
    rw.bytesWritten += int64(n)
    return n, err
}
```

## Sampling Implementations

### Probabilistic Sampler

```go
// pkg/sampling/probabilistic.go
package sampling

import (
    "hash/fnv"
    "math"
)

type ProbabilisticSampler struct {
    rate float64
}

func NewProbabilisticSampler(rate float64) *ProbabilisticSampler {
    if rate < 0 {
        rate = 0
    }
    if rate > 1 {
        rate = 1
    }
    
    return &ProbabilisticSampler{rate: rate}
}

func (s *ProbabilisticSampler) ShouldSample(traceID string, operationName string, tags map[string]string) bool {
    if s.rate == 0 {
        return false
    }
    if s.rate == 1 {
        return true
    }
    
    hash := fnv.New64a()
    hash.Write([]byte(traceID))
    
    // Use the hash to make a deterministic decision
    threshold := uint64(s.rate * math.MaxUint64)
    return hash.Sum64() < threshold
}
```

### Adaptive Sampler

```go
// pkg/sampling/adaptive.go
package sampling

import (
    "sync"
    "time"
)

type AdaptiveSampler struct {
    targetTPS    int
    currentRate  float64
    windowSize   time.Duration
    measurements []measurement
    mutex        sync.RWMutex
    lastAdjust   time.Time
}

type measurement struct {
    timestamp  time.Time
    requests   int
    sampled    int
}

func NewAdaptiveSampler(targetTPS int, windowSize time.Duration) *AdaptiveSampler {
    return &AdaptiveSampler{
        targetTPS:    targetTPS,
        currentRate:  0.1, // Start with 10%
        windowSize:   windowSize,
        measurements: make([]measurement, 0),
        lastAdjust:   time.Now(),
    }
}

func (s *AdaptiveSampler) ShouldSample(traceID string, operationName string, tags map[string]string) bool {
    s.recordRequest()
    
    // Always sample errors
    if status, exists := tags["error"]; exists && status == "true" {
        return true
    }
    
    s.mutex.RLock()
    rate := s.currentRate
    s.mutex.RUnlock()
    
    return NewProbabilisticSampler(rate).ShouldSample(traceID, operationName, tags)
}

func (s *AdaptiveSampler) recordRequest() {
    s.mutex.Lock()
    defer s.mutex.Unlock()
    
    now := time.Now()
    
    // Add or update current measurement
    if len(s.measurements) == 0 || now.Sub(s.measurements[len(s.measurements)-1].timestamp) > time.Second {
        s.measurements = append(s.measurements, measurement{
            timestamp: now,
            requests:  1,
            sampled:   0,
        })
    } else {
        s.measurements[len(s.measurements)-1].requests++
    }
    
    // Clean old measurements
    cutoff := now.Add(-s.windowSize)
    for i, m := range s.measurements {
        if m.timestamp.After(cutoff) {
            s.measurements = s.measurements[i:]
            break
        }
    }
    
    // Adjust rate if needed
    if now.Sub(s.lastAdjust) > s.windowSize {
        s.adjustRate()
        s.lastAdjust = now
    }
}

func (s *AdaptiveSampler) adjustRate() {
    if len(s.measurements) < 2 {
        return
    }
    
    // Calculate current TPS
    totalRequests := 0
    totalSampled := 0
    
    for _, m := range s.measurements {
        totalRequests += m.requests
        totalSampled += m.sampled
    }
    
    currentTPS := totalSampled / int(s.windowSize.Seconds())
    
    // Adjust rate based on target
    if currentTPS > s.targetTPS {
        s.currentRate *= 0.9 // Reduce by 10%
    } else if currentTPS < s.targetTPS {
        s.currentRate *= 1.1 // Increase by 10%
    }
    
    // Keep rate within bounds
    if s.currentRate < 0.001 {
        s.currentRate = 0.001
    }
    if s.currentRate > 1.0 {
        s.currentRate = 1.0
    }
}
```

## Example Applications

### API Gateway Service

```go
// cmd/api-gateway/main.go
package main

import (
    "context"
    "encoding/json"
    "log"
    "net/http"
    "time"
    
    "your-project/pkg/tracing"
    "your-project/pkg/instrumentation"
    "your-project/pkg/sampling"
)

func main() {
    // Initialize tracing
    sampler := sampling.NewProbabilisticSampler(0.1)
    tracing.InitGlobalTracer("api-gateway", sampler)
    
    // Initialize collector
    tracing.InitGlobalCollector("http://localhost:9411/api/v2/spans", 100, 5*time.Second)
    defer tracing.GlobalCollector.Stop()
    
    // Setup HTTP instrumentation
    httpInst := instrumentation.NewHTTPInstrumentation(tracing.GlobalTracer)
    
    // Create HTTP client with instrumentation
    client := &http.Client{
        Transport: httpInst.RoundTripper(http.DefaultTransport),
        Timeout:   30 * time.Second,
    }
    
    // Routes
    mux := http.NewServeMux()
    mux.HandleFunc("/api/users/", func(w http.ResponseWriter, r *http.Request) {
        userHandler(w, r, client)
    })
    
    mux.HandleFunc("/api/orders/", func(w http.ResponseWriter, r *http.Request) {
        orderHandler(w, r, client)
    })
    
    // Apply instrumentation middleware
    handler := httpInst.ServerMiddleware(mux)
    
    log.Printf("API Gateway starting on :8080")
    log.Fatal(http.ListenAndServe(":8080", handler))
}

func userHandler(w http.ResponseWriter, r *http.Request, client *http.Client) {
    span := tracing.SpanFromContext(r.Context())
    span.AddEvent("calling_user_service", map[string]string{
        "service": "user-service",
        "endpoint": "/users",
    })
    
    // Create request to user service
    req, err := http.NewRequestWithContext(r.Context(), "GET", "http://localhost:8081/users", nil)
    if err != nil {
        span.SetStatus(tracing.StatusError, err.Error())
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    
    // Make the request
    resp, err := client.Do(req)
    if err != nil {
        span.SetStatus(tracing.StatusError, err.Error())
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    defer resp.Body.Close()
    
    // Forward response
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(resp.StatusCode)
    
    var response map[string]interface{}
    if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
        span.SetStatus(tracing.StatusError, err.Error())
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    
    span.AddEvent("user_service_response", map[string]string{
        "status": string(resp.StatusCode),
        "user_count": string(len(response)),
    })
    
    json.NewEncoder(w).Encode(response)
}

func orderHandler(w http.ResponseWriter, r *http.Request, client *http.Client) {
    span := tracing.SpanFromContext(r.Context())
    span.AddEvent("calling_order_service", map[string]string{
        "service": "order-service",
        "endpoint": "/orders",
    })
    
    // Create request to order service
    req, err := http.NewRequestWithContext(r.Context(), "GET", "http://localhost:8082/orders", nil)
    if err != nil {
        span.SetStatus(tracing.StatusError, err.Error())
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    
    // Make the request
    resp, err := client.Do(req)
    if err != nil {
        span.SetStatus(tracing.StatusError, err.Error())
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    defer resp.Body.Close()
    
    // Forward response
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(resp.StatusCode)
    
    var response map[string]interface{}
    if err := json.NewDecoder(resp.Body).Decode(&response); err != nil {
        span.SetStatus(tracing.StatusError, err.Error())
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    
    json.NewEncoder(w).Encode(response)
}
```

### User Service

```go
// cmd/user-service/main.go
package main

import (
    "context"
    "database/sql"
    "encoding/json"
    "log"
    "net/http"
    "time"
    
    _ "github.com/lib/pq"
    
    "your-project/pkg/tracing"
    "your-project/pkg/instrumentation"
    "your-project/pkg/sampling"
)

type User struct {
    ID       int    `json:"id"`
    Name     string `json:"name"`
    Email    string `json:"email"`
    Created  time.Time `json:"created"`
}

type UserService struct {
    db *sql.DB
}

func main() {
    // Initialize tracing
    sampler := sampling.NewProbabilisticSampler(0.1)
    tracing.InitGlobalTracer("user-service", sampler)
    
    // Initialize collector
    tracing.InitGlobalCollector("http://localhost:9411/api/v2/spans", 100, 5*time.Second)
    defer tracing.GlobalCollector.Stop()
    
    // Initialize database
    db, err := sql.Open("postgres", "postgresql://user:password@localhost/users?sslmode=disable")
    if err != nil {
        log.Fatal(err)
    }
    defer db.Close()
    
    service := &UserService{db: db}
    
    // Setup HTTP instrumentation
    httpInst := instrumentation.NewHTTPInstrumentation(tracing.GlobalTracer)
    
    // Routes
    mux := http.NewServeMux()
    mux.HandleFunc("/users", service.getUsersHandler)
    mux.HandleFunc("/users/", service.getUserHandler)
    
    // Apply instrumentation middleware
    handler := httpInst.ServerMiddleware(mux)
    
    log.Printf("User Service starting on :8081")
    log.Fatal(http.ListenAndServe(":8081", handler))
}

func (s *UserService) getUsersHandler(w http.ResponseWriter, r *http.Request) {
    span := tracing.SpanFromContext(r.Context())
    span.AddEvent("fetching_users", map[string]string{
        "operation": "list_users",
    })
    
    users, err := s.getUsers(r.Context())
    if err != nil {
        span.SetStatus(tracing.StatusError, err.Error())
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    
    span.SetTag("user_count", string(len(users)))
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(users)
}

func (s *UserService) getUserHandler(w http.ResponseWriter, r *http.Request) {
    span := tracing.SpanFromContext(r.Context())
    
    // Extract user ID from path
    userID := r.URL.Path[len("/users/"):]
    span.SetTag("user_id", userID)
    
    span.AddEvent("fetching_user", map[string]string{
        "user_id": userID,
    })
    
    user, err := s.getUser(r.Context(), userID)
    if err != nil {
        span.SetStatus(tracing.StatusError, err.Error())
        http.Error(w, err.Error(), http.StatusInternalServerError)
        return
    }
    
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(user)
}

func (s *UserService) getUsers(ctx context.Context) ([]User, error) {
    span, ctx := tracing.GlobalTracer.StartSpanFromContext(ctx, "database_query_users")
    defer span.Finish()
    
    span.SetTag("db.type", "postgresql")
    span.SetTag("db.statement", "SELECT id, name, email, created FROM users")
    
    rows, err := s.db.QueryContext(ctx, "SELECT id, name, email, created FROM users")
    if err != nil {
        span.SetStatus(tracing.StatusError, err.Error())
        return nil, err
    }
    defer rows.Close()
    
    var users []User
    for rows.Next() {
        var user User
        if err := rows.Scan(&user.ID, &user.Name, &user.Email, &user.Created); err != nil {
            span.SetStatus(tracing.StatusError, err.Error())
            return nil, err
        }
        users = append(users, user)
    }
    
    span.SetTag("rows_returned", string(len(users)))
    return users, nil
}

func (s *UserService) getUser(ctx context.Context, userID string) (*User, error) {
    span, ctx := tracing.GlobalTracer.StartSpanFromContext(ctx, "database_query_user")
    defer span.Finish()
    
    span.SetTag("db.type", "postgresql")
    span.SetTag("db.statement", "SELECT id, name, email, created FROM users WHERE id = $1")
    span.SetTag("user_id", userID)
    
    var user User
    err := s.db.QueryRowContext(ctx, "SELECT id, name, email, created FROM users WHERE id = $1", userID).
        Scan(&user.ID, &user.Name, &user.Email, &user.Created)
    
    if err != nil {
        span.SetStatus(tracing.StatusError, err.Error())
        return nil, err
    }
    
    return &user, nil
}
```

## Running the System

### 1. Start the services:

```bash
# Terminal 1: Start trace collector (Jaeger)
docker run -d --name jaeger \
  -p 16686:16686 \
  -p 14268:14268 \
  -p 9411:9411 \
  jaegertracing/all-in-one:latest

# Terminal 2: Start user service
go run cmd/user-service/main.go

# Terminal 3: Start API gateway
go run cmd/api-gateway/main.go
```

### 2. Make requests:

```bash
# Make some requests to generate traces
curl http://localhost:8080/api/users/
curl http://localhost:8080/api/users/123
```

### 3. View traces:

Open http://localhost:16686 to view traces in Jaeger UI.

## Key Features

1. **Automatic Context Propagation**: Trace context flows seamlessly between services
2. **Flexible Sampling**: Multiple sampling strategies with runtime configuration
3. **Rich Instrumentation**: Automatic HTTP client/server instrumentation
4. **Production Ready**: Proper error handling, batching, and async processing
5. **Extensible**: Easy to add new instrumentation for databases, message queues, etc.

## Performance Considerations

- **Sampling**: Use appropriate sampling rates to balance observability and performance
- **Batching**: Collector batches spans to reduce network overhead
- **Async Processing**: Span processing doesn't block request processing
- **Memory Management**: Spans are cleaned up after transmission

This implementation provides a solid foundation for distributed tracing in Go applications, with patterns that scale to production environments.

---

*This Go implementation demonstrates production-ready distributed tracing with automatic instrumentation, flexible sampling, and robust error handling. The modular design allows for easy extension and customization.*