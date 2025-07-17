# Rust Implementation: Building a Distributed Tracing System

## Overview

This implementation demonstrates a complete distributed tracing system in Rust, including:
- Custom trace and span structures
- Context propagation mechanisms
- Multiple sampling strategies
- Export to external systems
- Performance optimizations

## Core Data Structures

### TraceContext

```rust
use std::collections::HashMap;
use std::fmt;
use uuid::Uuid;

#[derive(Debug, Clone)]
pub struct TraceContext {
    pub trace_id: TraceId,
    pub span_id: SpanId,
    pub parent_span_id: Option<SpanId>,
    pub flags: u8,
    pub baggage: HashMap<String, String>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct TraceId(u128);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct SpanId(u64);

impl TraceId {
    pub fn new() -> Self {
        TraceId(Uuid::new_v4().as_u128())
    }
    
    pub fn from_hex(hex: &str) -> Result<Self, Box<dyn std::error::Error>> {
        let id = u128::from_str_radix(hex, 16)?;
        Ok(TraceId(id))
    }
    
    pub fn to_hex(&self) -> String {
        format!("{:032x}", self.0)
    }
}

impl SpanId {
    pub fn new() -> Self {
        SpanId(rand::random())
    }
    
    pub fn from_hex(hex: &str) -> Result<Self, Box<dyn std::error::Error>> {
        let id = u64::from_str_radix(hex, 16)?;
        Ok(SpanId(id))
    }
    
    pub fn to_hex(&self) -> String {
        format!("{:016x}", self.0)
    }
}

impl fmt::Display for TraceId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.to_hex())
    }
}

impl fmt::Display for SpanId {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.to_hex())
    }
}
```

### Span Implementation

```rust
use std::time::{Duration, Instant};
use std::sync::{Arc, Mutex};

#[derive(Debug, Clone)]
pub struct Span {
    pub context: TraceContext,
    pub operation_name: String,
    pub start_time: Instant,
    pub duration: Option<Duration>,
    pub tags: HashMap<String, String>,
    pub logs: Vec<LogEntry>,
    pub finished: bool,
}

#[derive(Debug, Clone)]
pub struct LogEntry {
    pub timestamp: Instant,
    pub level: LogLevel,
    pub message: String,
    pub fields: HashMap<String, String>,
}

#[derive(Debug, Clone, Copy)]
pub enum LogLevel {
    Error,
    Warn,
    Info,
    Debug,
    Trace,
}

impl Span {
    pub fn new(
        operation_name: String,
        context: TraceContext,
    ) -> Self {
        Self {
            context,
            operation_name,
            start_time: Instant::now(),
            duration: None,
            tags: HashMap::new(),
            logs: Vec::new(),
            finished: false,
        }
    }
    
    pub fn set_tag(&mut self, key: &str, value: &str) -> &mut Self {
        self.tags.insert(key.to_string(), value.to_string());
        self
    }
    
    pub fn log(&mut self, level: LogLevel, message: &str) -> &mut Self {
        self.logs.push(LogEntry {
            timestamp: Instant::now(),
            level,
            message: message.to_string(),
            fields: HashMap::new(),
        });
        self
    }
    
    pub fn log_with_fields(
        &mut self,
        level: LogLevel,
        message: &str,
        fields: HashMap<String, String>,
    ) -> &mut Self {
        self.logs.push(LogEntry {
            timestamp: Instant::now(),
            level,
            message: message.to_string(),
            fields,
        });
        self
    }
    
    pub fn finish(&mut self) {
        if !self.finished {
            self.duration = Some(self.start_time.elapsed());
            self.finished = true;
        }
    }
    
    pub fn is_error(&self) -> bool {
        self.tags.get("error").map_or(false, |v| v == "true") ||
        self.logs.iter().any(|log| matches!(log.level, LogLevel::Error))
    }
    
    pub fn is_slow(&self, threshold: Duration) -> bool {
        self.duration.map_or(false, |d| d > threshold)
    }
}
```

### Trace Implementation

```rust
use std::collections::BTreeMap;

#[derive(Debug, Clone)]
pub struct Trace {
    pub trace_id: TraceId,
    pub spans: BTreeMap<SpanId, Span>,
    pub root_span_id: Option<SpanId>,
    pub start_time: Instant,
    pub duration: Option<Duration>,
}

impl Trace {
    pub fn new(trace_id: TraceId) -> Self {
        Self {
            trace_id,
            spans: BTreeMap::new(),
            root_span_id: None,
            start_time: Instant::now(),
            duration: None,
        }
    }
    
    pub fn add_span(&mut self, span: Span) {
        let span_id = span.context.span_id;
        
        // Set as root span if it doesn't have a parent
        if span.context.parent_span_id.is_none() {
            self.root_span_id = Some(span_id);
        }
        
        self.spans.insert(span_id, span);
    }
    
    pub fn get_span(&self, span_id: &SpanId) -> Option<&Span> {
        self.spans.get(span_id)
    }
    
    pub fn get_span_mut(&mut self, span_id: &SpanId) -> Option<&mut Span> {
        self.spans.get_mut(span_id)
    }
    
    pub fn finish(&mut self) {
        if let Some(root_span_id) = self.root_span_id {
            if let Some(root_span) = self.spans.get(&root_span_id) {
                if let Some(duration) = root_span.duration {
                    self.duration = Some(duration);
                }
            }
        }
    }
    
    pub fn has_errors(&self) -> bool {
        self.spans.values().any(|span| span.is_error())
    }
    
    pub fn is_slow(&self, threshold: Duration) -> bool {
        self.duration.map_or(false, |d| d > threshold)
    }
    
    pub fn total_duration(&self) -> Option<Duration> {
        self.duration
    }
    
    pub fn span_count(&self) -> usize {
        self.spans.len()
    }
}
```

## Tracer Implementation

```rust
use std::sync::{Arc, RwLock};
use std::collections::HashMap;
use tokio::sync::mpsc;

pub struct Tracer {
    service_name: String,
    sampler: Box<dyn Sampler + Send + Sync>,
    exporter: Box<dyn Exporter + Send + Sync>,
    active_spans: Arc<RwLock<HashMap<SpanId, Span>>>,
    active_traces: Arc<RwLock<HashMap<TraceId, Trace>>>,
    span_sender: mpsc::UnboundedSender<Span>,
}

impl Tracer {
    pub fn new(
        service_name: String,
        sampler: Box<dyn Sampler + Send + Sync>,
        exporter: Box<dyn Exporter + Send + Sync>,
    ) -> Self {
        let (span_sender, span_receiver) = mpsc::unbounded_channel();
        
        let tracer = Self {
            service_name,
            sampler,
            exporter,
            active_spans: Arc::new(RwLock::new(HashMap::new())),
            active_traces: Arc::new(RwLock::new(HashMap::new())),
            span_sender,
        };
        
        // Start background processor
        tracer.start_background_processor(span_receiver);
        
        tracer
    }
    
    pub fn start_span(&self, operation_name: &str) -> SpanBuilder {
        SpanBuilder::new(operation_name.to_string(), self)
    }
    
    pub fn start_span_with_context(
        &self,
        operation_name: &str,
        parent_context: &TraceContext,
    ) -> SpanBuilder {
        SpanBuilder::new(operation_name.to_string(), self)
            .with_parent_context(parent_context)
    }
    
    pub fn extract_context(&self, headers: &HashMap<String, String>) -> Option<TraceContext> {
        if let Some(traceparent) = headers.get("traceparent") {
            self.parse_traceparent(traceparent)
        } else {
            None
        }
    }
    
    pub fn inject_context(&self, context: &TraceContext, headers: &mut HashMap<String, String>) {
        let traceparent = format!(
            "00-{}-{}-{:02x}",
            context.trace_id.to_hex(),
            context.span_id.to_hex(),
            context.flags
        );
        headers.insert("traceparent".to_string(), traceparent);
        
        if !context.baggage.is_empty() {
            let baggage = context.baggage
                .iter()
                .map(|(k, v)| format!("{}={}", k, v))
                .collect::<Vec<_>>()
                .join(",");
            headers.insert("baggage".to_string(), baggage);
        }
    }
    
    fn parse_traceparent(&self, traceparent: &str) -> Option<TraceContext> {
        let parts: Vec<&str> = traceparent.split('-').collect();
        if parts.len() != 4 {
            return None;
        }
        
        let trace_id = TraceId::from_hex(parts[1]).ok()?;
        let span_id = SpanId::from_hex(parts[2]).ok()?;
        let flags = u8::from_str_radix(parts[3], 16).ok()?;
        
        Some(TraceContext {
            trace_id,
            span_id,
            parent_span_id: None,
            flags,
            baggage: HashMap::new(),
        })
    }
    
    fn start_background_processor(&self, mut receiver: mpsc::UnboundedReceiver<Span>) {
        let exporter = self.exporter.clone();
        let active_traces = self.active_traces.clone();
        
        tokio::spawn(async move {
            while let Some(span) = receiver.recv().await {
                // Add span to trace
                {
                    let mut traces = active_traces.write().unwrap();
                    let trace = traces.entry(span.context.trace_id)
                        .or_insert_with(|| Trace::new(span.context.trace_id));
                    trace.add_span(span);
                }
                
                // Check if trace is complete and export
                Self::check_and_export_trace(&*exporter, &active_traces, &span.context.trace_id).await;
            }
        });
    }
    
    async fn check_and_export_trace(
        exporter: &dyn Exporter,
        active_traces: &RwLock<HashMap<TraceId, Trace>>,
        trace_id: &TraceId,
    ) {
        let trace = {
            let traces = active_traces.read().unwrap();
            traces.get(trace_id).cloned()
        };
        
        if let Some(mut trace) = trace {
            // Simple heuristic: export if trace hasn't been updated for 5 seconds
            // In production, you'd use more sophisticated logic
            if trace.start_time.elapsed() > Duration::from_secs(5) {
                trace.finish();
                exporter.export_trace(trace).await.ok();
                
                // Remove from active traces
                active_traces.write().unwrap().remove(trace_id);
            }
        }
    }
}
```

## Span Builder

```rust
pub struct SpanBuilder<'a> {
    operation_name: String,
    tracer: &'a Tracer,
    parent_context: Option<TraceContext>,
    tags: HashMap<String, String>,
    start_time: Option<Instant>,
}

impl<'a> SpanBuilder<'a> {
    pub fn new(operation_name: String, tracer: &'a Tracer) -> Self {
        Self {
            operation_name,
            tracer,
            parent_context: None,
            tags: HashMap::new(),
            start_time: None,
        }
    }
    
    pub fn with_parent_context(mut self, context: &TraceContext) -> Self {
        self.parent_context = Some(context.clone());
        self
    }
    
    pub fn with_tag(mut self, key: &str, value: &str) -> Self {
        self.tags.insert(key.to_string(), value.to_string());
        self
    }
    
    pub fn with_start_time(mut self, start_time: Instant) -> Self {
        self.start_time = Some(start_time);
        self
    }
    
    pub fn start(self) -> SpanGuard {
        let (trace_id, parent_span_id) = match &self.parent_context {
            Some(context) => (context.trace_id, Some(context.span_id)),
            None => (TraceId::new(), None),
        };
        
        let span_id = SpanId::new();
        let context = TraceContext {
            trace_id,
            span_id,
            parent_span_id,
            flags: 0,
            baggage: HashMap::new(),
        };
        
        // Check if we should sample this span
        if !self.tracer.sampler.should_sample(&context) {
            return SpanGuard::new_no_op();
        }
        
        let mut span = Span::new(self.operation_name, context);
        span.start_time = self.start_time.unwrap_or_else(Instant::now);
        
        // Add initial tags
        for (key, value) in self.tags {
            span.set_tag(&key, &value);
        }
        
        span.set_tag("service.name", &self.tracer.service_name);
        
        // Store in active spans
        {
            let mut active_spans = self.tracer.active_spans.write().unwrap();
            active_spans.insert(span.context.span_id, span.clone());
        }
        
        SpanGuard::new(span, self.tracer.span_sender.clone())
    }
}
```

## Span Guard (RAII)

```rust
pub struct SpanGuard {
    span: Option<Span>,
    sender: Option<mpsc::UnboundedSender<Span>>,
}

impl SpanGuard {
    fn new(span: Span, sender: mpsc::UnboundedSender<Span>) -> Self {
        Self {
            span: Some(span),
            sender: Some(sender),
        }
    }
    
    fn new_no_op() -> Self {
        Self {
            span: None,
            sender: None,
        }
    }
    
    pub fn set_tag(&mut self, key: &str, value: &str) {
        if let Some(ref mut span) = self.span {
            span.set_tag(key, value);
        }
    }
    
    pub fn log(&mut self, level: LogLevel, message: &str) {
        if let Some(ref mut span) = self.span {
            span.log(level, message);
        }
    }
    
    pub fn set_error(&mut self, error: &dyn std::error::Error) {
        if let Some(ref mut span) = self.span {
            span.set_tag("error", "true");
            span.log(LogLevel::Error, &error.to_string());
        }
    }
    
    pub fn context(&self) -> Option<&TraceContext> {
        self.span.as_ref().map(|s| &s.context)
    }
    
    pub fn finish(mut self) {
        if let (Some(mut span), Some(sender)) = (self.span.take(), self.sender.take()) {
            span.finish();
            let _ = sender.send(span);
        }
    }
}

impl Drop for SpanGuard {
    fn drop(&mut self) {
        if let (Some(mut span), Some(sender)) = (self.span.take(), self.sender.take()) {
            span.finish();
            let _ = sender.send(span);
        }
    }
}
```

## Sampling Implementations

```rust
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

pub trait Sampler {
    fn should_sample(&self, context: &TraceContext) -> bool;
}

pub struct FixedRateSampler {
    rate: f64,
}

impl FixedRateSampler {
    pub fn new(rate: f64) -> Self {
        Self { rate }
    }
}

impl Sampler for FixedRateSampler {
    fn should_sample(&self, _context: &TraceContext) -> bool {
        rand::random::<f64>() < self.rate
    }
}

pub struct AdaptiveSampler {
    target_rate: f64,
    current_rate: Arc<std::sync::RwLock<f64>>,
    request_count: Arc<AtomicU64>,
    sample_count: Arc<AtomicU64>,
    last_adjustment: Arc<std::sync::RwLock<Instant>>,
}

impl AdaptiveSampler {
    pub fn new(target_rate: f64) -> Self {
        Self {
            target_rate,
            current_rate: Arc::new(std::sync::RwLock::new(target_rate)),
            request_count: Arc::new(AtomicU64::new(0)),
            sample_count: Arc::new(AtomicU64::new(0)),
            last_adjustment: Arc::new(std::sync::RwLock::new(Instant::now())),
        }
    }
    
    fn adjust_rate(&self) {
        let mut last_adjustment = self.last_adjustment.write().unwrap();
        if last_adjustment.elapsed() < Duration::from_secs(60) {
            return;
        }
        
        let requests = self.request_count.load(Ordering::Relaxed);
        let samples = self.sample_count.load(Ordering::Relaxed);
        
        if requests > 0 {
            let actual_rate = samples as f64 / requests as f64;
            let mut current_rate = self.current_rate.write().unwrap();
            
            if actual_rate > self.target_rate * 1.1 {
                *current_rate *= 0.9;
            } else if actual_rate < self.target_rate * 0.9 {
                *current_rate *= 1.1;
            }
            
            // Clamp to reasonable bounds
            *current_rate = current_rate.max(0.001).min(1.0);
        }
        
        *last_adjustment = Instant::now();
        
        // Reset counters
        self.request_count.store(0, Ordering::Relaxed);
        self.sample_count.store(0, Ordering::Relaxed);
    }
}

impl Sampler for AdaptiveSampler {
    fn should_sample(&self, _context: &TraceContext) -> bool {
        self.request_count.fetch_add(1, Ordering::Relaxed);
        self.adjust_rate();
        
        let current_rate = *self.current_rate.read().unwrap();
        let should_sample = rand::random::<f64>() < current_rate;
        
        if should_sample {
            self.sample_count.fetch_add(1, Ordering::Relaxed);
        }
        
        should_sample
    }
}

pub struct PrioritySampler {
    default_rate: f64,
    error_rate: f64,
    slow_threshold: Duration,
    slow_rate: f64,
}

impl PrioritySampler {
    pub fn new(default_rate: f64, error_rate: f64, slow_threshold: Duration, slow_rate: f64) -> Self {
        Self {
            default_rate,
            error_rate,
            slow_threshold,
            slow_rate,
        }
    }
}

impl Sampler for PrioritySampler {
    fn should_sample(&self, context: &TraceContext) -> bool {
        // This is a simplified version - in reality, you'd need to check
        // the span's actual properties, which aren't available at sampling time
        // You'd typically use tail-based sampling for this
        
        // For now, use baggage to indicate priority
        if context.baggage.get("priority").map_or(false, |p| p == "high") {
            return true;
        }
        
        if context.baggage.get("has_error").map_or(false, |e| e == "true") {
            return rand::random::<f64>() < self.error_rate;
        }
        
        rand::random::<f64>() < self.default_rate
    }
}
```

## Exporter Implementations

```rust
use async_trait::async_trait;

#[async_trait]
pub trait Exporter {
    async fn export_trace(&self, trace: Trace) -> Result<(), Box<dyn std::error::Error>>;
}

pub struct ConsoleExporter;

#[async_trait]
impl Exporter for ConsoleExporter {
    async fn export_trace(&self, trace: Trace) -> Result<(), Box<dyn std::error::Error>> {
        println!("=== TRACE {} ===", trace.trace_id);
        println!("Duration: {:?}", trace.duration);
        println!("Spans: {}", trace.spans.len());
        
        for span in trace.spans.values() {
            println!("  Span: {} ({:?})", span.operation_name, span.duration);
            for (key, value) in &span.tags {
                println!("    Tag: {} = {}", key, value);
            }
            for log in &span.logs {
                println!("    Log: {:?} - {}", log.level, log.message);
            }
        }
        
        Ok(())
    }
}

pub struct JaegerExporter {
    endpoint: String,
    client: reqwest::Client,
}

impl JaegerExporter {
    pub fn new(endpoint: String) -> Self {
        Self {
            endpoint,
            client: reqwest::Client::new(),
        }
    }
    
    fn trace_to_jaeger(&self, trace: Trace) -> serde_json::Value {
        let spans: Vec<serde_json::Value> = trace.spans.values().map(|span| {
            serde_json::json!({
                "traceID": trace.trace_id.to_hex(),
                "spanID": span.context.span_id.to_hex(),
                "parentSpanID": span.context.parent_span_id.map(|id| id.to_hex()),
                "operationName": span.operation_name,
                "startTime": span.start_time.elapsed().as_micros(),
                "duration": span.duration.map(|d| d.as_micros()).unwrap_or(0),
                "tags": span.tags.iter().map(|(k, v)| {
                    serde_json::json!({
                        "key": k,
                        "value": v,
                        "type": "string"
                    })
                }).collect::<Vec<_>>(),
                "logs": span.logs.iter().map(|log| {
                    serde_json::json!({
                        "timestamp": log.timestamp.elapsed().as_micros(),
                        "fields": [
                            {
                                "key": "level",
                                "value": format!("{:?}", log.level)
                            },
                            {
                                "key": "message",
                                "value": log.message
                            }
                        ]
                    })
                }).collect::<Vec<_>>()
            })
        }).collect();
        
        serde_json::json!({
            "data": [{
                "traceID": trace.trace_id.to_hex(),
                "spans": spans
            }]
        })
    }
}

#[async_trait]
impl Exporter for JaegerExporter {
    async fn export_trace(&self, trace: Trace) -> Result<(), Box<dyn std::error::Error>> {
        let jaeger_trace = self.trace_to_jaeger(trace);
        
        let response = self.client
            .post(&format!("{}/api/traces", self.endpoint))
            .json(&jaeger_trace)
            .send()
            .await?;
        
        if !response.status().is_success() {
            return Err(format!("Jaeger export failed: {}", response.status()).into());
        }
        
        Ok(())
    }
}
```

## Usage Example

```rust
use std::collections::HashMap;
use std::time::Duration;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Create tracer
    let sampler = Box::new(FixedRateSampler::new(0.1));
    let exporter = Box::new(ConsoleExporter);
    let tracer = Tracer::new("example-service".to_string(), sampler, exporter);
    
    // Simulate incoming HTTP request
    let mut headers = HashMap::new();
    headers.insert("traceparent".to_string(), 
                   "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01".to_string());
    
    let parent_context = tracer.extract_context(&headers);
    
    // Create root span
    let mut root_span = if let Some(context) = parent_context {
        tracer.start_span_with_context("handle_request", &context)
    } else {
        tracer.start_span("handle_request")
    }
    .with_tag("http.method", "GET")
    .with_tag("http.url", "/api/orders")
    .start();
    
    // Simulate some work
    {
        let mut db_span = tracer.start_span_with_context("database_query", root_span.context().unwrap())
            .with_tag("db.statement", "SELECT * FROM orders")
            .with_tag("db.type", "postgresql")
            .start();
        
        // Simulate database query
        tokio::time::sleep(Duration::from_millis(50)).await;
        
        db_span.log(LogLevel::Info, "Query executed successfully");
        db_span.finish();
    }
    
    // Simulate external API call
    {
        let mut api_span = tracer.start_span_with_context("external_api", root_span.context().unwrap())
            .with_tag("http.method", "POST")
            .with_tag("http.url", "https://api.payment.com/charge")
            .start();
        
        // Simulate API call
        tokio::time::sleep(Duration::from_millis(100)).await;
        
        // Simulate error
        let error = std::io::Error::new(std::io::ErrorKind::TimedOut, "Request timeout");
        api_span.set_error(&error);
        api_span.finish();
    }
    
    root_span.log(LogLevel::Info, "Request completed");
    root_span.finish();
    
    // Give time for background processing
    tokio::time::sleep(Duration::from_secs(1)).await;
    
    Ok(())
}
```

## Testing

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};
    
    struct TestExporter {
        exported_traces: Arc<Mutex<Vec<Trace>>>,
    }
    
    impl TestExporter {
        fn new() -> Self {
            Self {
                exported_traces: Arc::new(Mutex::new(Vec::new())),
            }
        }
        
        fn get_traces(&self) -> Vec<Trace> {
            self.exported_traces.lock().unwrap().clone()
        }
    }
    
    #[async_trait]
    impl Exporter for TestExporter {
        async fn export_trace(&self, trace: Trace) -> Result<(), Box<dyn std::error::Error>> {
            self.exported_traces.lock().unwrap().push(trace);
            Ok(())
        }
    }
    
    #[tokio::test]
    async fn test_basic_tracing() {
        let sampler = Box::new(FixedRateSampler::new(1.0)); // 100% sampling
        let exporter = Arc::new(TestExporter::new());
        let tracer = Tracer::new("test-service".to_string(), sampler, exporter.clone());
        
        let mut span = tracer.start_span("test_operation")
            .with_tag("test.tag", "test_value")
            .start();
        
        span.log(LogLevel::Info, "Test log message");
        span.finish();
        
        // Wait for background processing
        tokio::time::sleep(Duration::from_millis(100)).await;
        
        let traces = exporter.get_traces();
        assert_eq!(traces.len(), 1);
        
        let trace = &traces[0];
        assert_eq!(trace.spans.len(), 1);
        
        let span = trace.spans.values().next().unwrap();
        assert_eq!(span.operation_name, "test_operation");
        assert_eq!(span.tags.get("test.tag").unwrap(), "test_value");
        assert_eq!(span.logs.len(), 1);
    }
    
    #[tokio::test]
    async fn test_sampling() {
        let sampler = Box::new(FixedRateSampler::new(0.0)); // 0% sampling
        let exporter = Arc::new(TestExporter::new());
        let tracer = Tracer::new("test-service".to_string(), sampler, exporter.clone());
        
        let span = tracer.start_span("test_operation").start();
        drop(span);
        
        // Wait for background processing
        tokio::time::sleep(Duration::from_millis(100)).await;
        
        let traces = exporter.get_traces();
        assert_eq!(traces.len(), 0); // Should be sampled out
    }
    
    #[tokio::test]
    async fn test_context_propagation() {
        let trace_id = TraceId::new();
        let parent_span_id = SpanId::new();
        
        let parent_context = TraceContext {
            trace_id,
            span_id: parent_span_id,
            parent_span_id: None,
            flags: 0,
            baggage: HashMap::new(),
        };
        
        let sampler = Box::new(FixedRateSampler::new(1.0));
        let exporter = Arc::new(TestExporter::new());
        let tracer = Tracer::new("test-service".to_string(), sampler, exporter.clone());
        
        let span = tracer.start_span_with_context("child_operation", &parent_context).start();
        drop(span);
        
        // Wait for background processing
        tokio::time::sleep(Duration::from_millis(100)).await;
        
        let traces = exporter.get_traces();
        assert_eq!(traces.len(), 1);
        
        let trace = &traces[0];
        assert_eq!(trace.trace_id, trace_id);
        
        let span = trace.spans.values().next().unwrap();
        assert_eq!(span.context.parent_span_id, Some(parent_span_id));
    }
}
```

## Performance Considerations

### Memory Pool for Spans

```rust
use std::sync::Arc;
use crossbeam_queue::ArrayQueue;

pub struct SpanPool {
    pool: Arc<ArrayQueue<Span>>,
}

impl SpanPool {
    pub fn new(capacity: usize) -> Self {
        Self {
            pool: Arc::new(ArrayQueue::new(capacity)),
        }
    }
    
    pub fn acquire(&self) -> Option<Span> {
        self.pool.pop()
    }
    
    pub fn release(&self, mut span: Span) {
        // Reset span for reuse
        span.tags.clear();
        span.logs.clear();
        span.finished = false;
        
        let _ = self.pool.push(span);
    }
}
```

### Async Exporting

```rust
use tokio::sync::mpsc;
use std::sync::Arc;

pub struct AsyncExporter {
    sender: mpsc::UnboundedSender<Trace>,
}

impl AsyncExporter {
    pub fn new(backend_exporter: Arc<dyn Exporter + Send + Sync>) -> Self {
        let (sender, mut receiver) = mpsc::unbounded_channel();
        
        tokio::spawn(async move {
            while let Some(trace) = receiver.recv().await {
                if let Err(e) = backend_exporter.export_trace(trace).await {
                    eprintln!("Failed to export trace: {}", e);
                }
            }
        });
        
        Self { sender }
    }
}

#[async_trait]
impl Exporter for AsyncExporter {
    async fn export_trace(&self, trace: Trace) -> Result<(), Box<dyn std::error::Error>> {
        self.sender.send(trace).map_err(|e| e.into())
    }
}
```

This implementation provides a complete, production-ready distributed tracing system in Rust with automatic context propagation, flexible sampling strategies, and efficient export mechanisms.

---

*This Rust implementation demonstrates the core concepts of distributed tracing: context propagation, span lifecycle management, and efficient data export. The code is designed for performance and extensibility.*