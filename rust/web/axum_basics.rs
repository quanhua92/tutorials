//! axum_basics.rs — Phase 8 bundle (web member).
//!
//! GOAL (one line): show, by driving a `Router` IN-PROCESS via
//! `tower::ServiceExt::oneshot`, how axum turns typed async handler functions
//! and extractors into an HTTP service — declarative routing by method, shared
//! `State`, `Json`/`Path`/`Query` extraction, the `IntoResponse` trait, and
//! `Result`-based error handling — with NO socket and NO random port.
//!
//! This is the GROUND TRUTH for AXUM_BASICS.md. Every status code and body
//! below is produced by a real axum `Router` exercised end-to-end in-process;
//! the `.md` guide pastes it verbatim. Never hand-compute.
//!
//! DETERMINISM NOTE: every handler is driven IN-PROCESS via
//! `tower::ServiceExt::oneshot` — there is no `TcpListener`, no socket, and no
//! port. Requests are awaited SEQUENTIALLY, so the asserted status codes /
//! bodies are byte-reproducible. No server URL is ever printed (a random port
//! would make `_output.txt` non-reproducible).
//!
//! Run:
//!     just run axum_basics   (== cargo run --bin axum_basics)

use std::sync::Arc;
use std::sync::atomic::{AtomicU64, Ordering};

use axum::body::{Body, to_bytes};
use axum::extract::{Path, Query, State};
use axum::http::{Method, Request, StatusCode, header::CONTENT_TYPE};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde::Deserialize;
use tower::ServiceExt;

const BANNER_WIDTH: usize = 70;

fn banner(title: &str) {
    let bar = "=".repeat(BANNER_WIDTH);
    println!("\n{bar}\nSECTION {title}\n{bar}");
}

/// Assert an invariant and print a uniform `[check] ...: OK` line.
/// Panics on failure (non-zero exit) so `just check` / `just sweep` catch it.
fn check(desc: &str, ok: bool) {
    if !ok {
        panic!("INVARIANT VIOLATED: {desc}");
    }
    println!("[check] {desc}: OK");
}

/// The fully-buffered result of an in-process request: status line, the
/// `Content-Type` header if present, and the body decoded as UTF-8.
struct Fired {
    status: StatusCode,
    content_type: Option<String>,
    body: String,
}

/// Buffer a `Response` body to a `String`. The body is an async stream that can
/// be consumed once; `to_bytes` reads it fully up to `limit` bytes. `usize::MAX`
/// is fine here because these are tiny, trusted test bodies.
async fn body_text(response: Response) -> String {
    let bytes = to_bytes(response.into_body(), usize::MAX)
        .await
        .expect("in-process body should buffer");
    String::from_utf8(bytes.to_vec()).expect("test bodies are UTF-8")
}

/// Drive a `Router` with one synthetic request, IN-PROCESS — no socket. This is
/// the whole testing trick: a finished `Router<()>` is a `Service<Request>`, so
/// `oneshot` runs the full routing + extraction + handler pipeline and hands
/// back a real `Response`. We then assert on its status / headers / body.
async fn fire(app: Router, req: Request<Body>) -> Fired {
    let response = app.oneshot(req).await.expect("in-process call succeeds");
    let status = response.status();
    let content_type = response
        .headers()
        .get(CONTENT_TYPE)
        .map(|v| v.to_str().unwrap_or("").to_owned());
    let body = body_text(response).await;
    Fired {
        status,
        content_type,
        body,
    }
}

/// Build a bare GET request to `uri` (method defaults to GET).
fn get_req(uri: &str) -> Request<Body> {
    Request::builder()
        .uri(uri)
        .body(Body::empty())
        .expect("static request builds")
}

/// Build a POST request to `uri` with a JSON body and the matching header.
fn post_json(uri: &str, json: &str) -> Request<Body> {
    Request::builder()
        .method(Method::POST)
        .uri(uri)
        .header(CONTENT_TYPE, "application/json")
        .body(Body::from(json.to_owned()))
        .expect("static request builds")
}

// ── Section A: a Router + a GET handler returning &'static str ───────────────

/// The simplest handler: no extractors, returns a `&'static str`. Any type that
/// implements `IntoResponse` can be returned; `&'static str` becomes a `200 OK`
/// with `Content-Type: text/plain; charset=utf-8`.
async fn root() -> &'static str {
    "hello, axum"
}

async fn section_a() {
    banner("A — Router + a GET handler returning &'static str");
    println!("  // `Router::new().route(\"/\", get(handler))` maps GET / to the");
    println!("  // handler fn. `get` returns a `MethodRouter` that only answers GET.");
    println!("  // We drive it IN-PROCESS with `oneshot`: no socket, no port.");
    println!("  let app: Router = Router::new().route(\"/\", get(root));");

    let app: Router = Router::new().route("/", get(root));
    let out = fire(app, get_req("/")).await;

    println!("  GET /  -> {}  body = {:?}", out.status, out.body);
    check("GET / returns 200 OK", out.status == StatusCode::OK);
    check("GET / body contains \"hello\"", out.body.contains("hello"));
    check(
        "&'static str handler sets Content-Type: text/plain; charset=utf-8",
        out.content_type.as_deref() == Some("text/plain; charset=utf-8"),
    );
}

// ── Section B: method routing — GET and POST on the SAME path ───────────────

async fn echo_get() -> &'static str {
    "echo: GET"
}

async fn echo_post() -> &'static str {
    "echo: POST"
}

async fn section_b() {
    banner("B — method routing: GET and POST on the SAME path");
    println!("  // `get(h).post(h2)` builds a `MethodRouter` that dispatches by the");
    println!("  // HTTP method. Same path, two handlers — declarative, type-checked.");
    println!("  let app = Router::new().route(\"/echo\", get(echo_get).post(echo_post));");

    let app: Router = Router::new().route("/echo", get(echo_get).post(echo_post));

    let out_get = fire(app.clone(), get_req("/echo")).await;
    let out_post = fire(
        app,
        Request::builder()
            .method(Method::POST)
            .uri("/echo")
            .body(Body::empty())
            .expect("static request builds"),
    )
    .await;

    println!(
        "  GET  /echo -> {}  body = {:?}",
        out_get.status, out_get.body
    );
    println!(
        "  POST /echo -> {}  body = {:?}",
        out_post.status, out_post.body
    );
    check("GET /echo returns 200 + the GET handler's body", {
        out_get.status == StatusCode::OK && out_get.body == "echo: GET"
    });
    check("POST /echo returns 200 + the POST handler's body", {
        out_post.status == StatusCode::OK && out_post.body == "echo: POST"
    });
}

// ── Section C: extractors — Path + Query + Json, derived from the request ────

/// `Query<T>`: deserializes the query string with serde. `FromRequestParts`, so
/// it can appear anywhere before the body-consuming extractor.
#[derive(Deserialize)]
struct Filter {
    q: String,
}

/// `Json<T>`: consumes the body and deserializes it as JSON. `FromRequest`, so
/// it MUST be the LAST extractor argument (a body is a stream read once).
#[derive(Deserialize)]
struct NewItem {
    name: String,
}

/// Three extractors in one signature — axum derives each from the request, in
/// left-to-right order: `Path` from the URL, `Query` from the query string,
/// `Json` from the body. The handler just receives typed values.
async fn create_item(
    Path(id): Path<u32>,
    Query(Filter { q }): Query<Filter>,
    Json(NewItem { name }): Json<NewItem>,
) -> String {
    // All three came from different parts of one request, now typed Rust.
    format!("id={id}, q={q}, name={name}")
}

async fn section_c() {
    banner("C — extractors: Path + Query + Json, derived from the request");
    println!("  // `Path<T>` from the URL, `Query<T>` from the query string,");
    println!("  // `Json<T>` from the body — all typed, all serde-deserialized.");
    println!("  // axum 0.8 path capture syntax is {{id}} (not :id).");
    println!("  let app = Router::new().route(\"/items/{{id}}\", post(create_item));");

    let app: Router = Router::new().route("/items/{id}", post(create_item));
    let out = fire(app, post_json("/items/7?q=widget", r#"{"name":"axum"}"#)).await;

    println!("  POST /items/7?q=widget  {{\"name\":\"axum\"}}");
    println!("    -> {}  body = {:?}", out.status, out.body);
    check(
        "POST with Path+Query+Json returns 200",
        out.status == StatusCode::OK,
    );
    check("Path(id) parsed 7 from the URL", out.body.contains("id=7"));
    check("Query(q) parsed 'widget' from the query string", {
        out.body.contains("q=widget")
    });
    check(
        "Json(NewItem) parsed 'axum' from the body",
        out.body.contains("name=axum"),
    );
}

// ── Section D: State — shared application state via .with_state(..) ─────────

/// Application state. Must be `Clone` — axum hands every request a fresh clone.
/// Wrapping the mutable cell in `Arc` means every clone SHARES the same counter,
/// so increments made in one request are visible to the next.
#[derive(Clone)]
struct AppState {
    counter: Arc<AtomicU64>,
}

/// A mutating handler. `State<S>` is an extractor: it pulls the cloned state out
/// of the request. We bump the shared atomic and return `204 No Content`.
async fn increment(State(state): State<AppState>) -> StatusCode {
    let prev = state.counter.fetch_add(1, Ordering::SeqCst);
    println!("    [increment] counter: {prev} -> {}", prev + 1);
    StatusCode::NO_CONTENT // 204
}

/// A reading handler. Same shared `Arc`, so it sees prior increments.
async fn current(State(state): State<AppState>) -> String {
    state.counter.load(Ordering::SeqCst).to_string()
}

async fn section_d() {
    banner("D — State: a shared counter threaded via .with_state(..)");
    println!("  // `.with_state(s)` finalizes the Router, cloning `s` into each");
    println!("  // request. `Arc<AtomicU64>` makes the counter shared across clones.");
    println!("  // We fire requests on `app.clone()` — oneshot takes the Router by");
    println!("  // value, but cloning a Router clones the Arc'd state (cheap), so");
    println!("  // increments ACCUMULATE across the cloned routers.");

    let shared = AppState {
        counter: Arc::new(AtomicU64::new(0)),
    };
    let app: Router = Router::new()
        .route("/count", get(current).post(increment))
        .with_state(shared);

    let before = fire(app.clone(), get_req("/count")).await;
    println!(
        "  GET  /count (start)         -> {}  body = {:?}",
        before.status, before.body
    );
    check("counter starts at 0", before.body == "0");

    let incr1 = fire(
        app.clone(),
        Request::builder()
            .method(Method::POST)
            .uri("/count")
            .body(Body::empty())
            .expect("static request builds"),
    )
    .await;
    let incr2 = fire(
        app.clone(),
        Request::builder()
            .method(Method::POST)
            .uri("/count")
            .body(Body::empty())
            .expect("static request builds"),
    )
    .await;
    println!("  POST /count (increment #1)  -> {}", incr1.status);
    println!("  POST /count (increment #2)  -> {}", incr2.status);

    let after = fire(app, get_req("/count")).await;
    println!(
        "  GET  /count (after 2 POSTs) -> {}  body = {:?}",
        after.status, after.body
    );
    check(
        "POST increments return 204 No Content",
        incr1.status == StatusCode::NO_CONTENT,
    );
    check(
        "two POSTs share one Arc'd counter",
        incr2.status == StatusCode::NO_CONTENT,
    );
    check(
        "after two increments the counter reads 2",
        after.body == "2",
    );
}

// ── Section E: IntoResponse variants — a (StatusCode, Json<T>) tuple ────────

/// A serializable response body.
#[derive(serde::Serialize)]
struct Health {
    ok: bool,
}

/// Returning a TUPLE composes a response: `StatusCode` sets the status, the
/// middle items merge headers/parts, and the last item is the body. Here
/// `(StatusCode::OK, Json(..))` yields 200 + `application/json`.
async fn health() -> impl IntoResponse {
    (StatusCode::OK, Json(Health { ok: true }))
}

async fn section_e() {
    banner("E — IntoResponse variants: a (StatusCode, Json<T>) tuple");
    println!("  // `impl IntoResponse` is the handler return contract. axum impls it");
    println!("  // for String, &'static str, StatusCode, Json<T>, HeaderMap, and");
    println!("  // for tuples like (StatusCode, Json<T>) up to 16 parts. Returning a");
    println!("  // tuple composes status + headers + body in one expression.");
    println!("  let app = Router::new().route(\"/health\", get(health));");

    let app: Router = Router::new().route("/health", get(health));
    let out = fire(app, get_req("/health")).await;

    println!(
        "  GET /health -> {}  ctype = {:?}",
        out.status, out.content_type
    );
    println!("               body = {:?}", out.body);
    check("tuple response carries the explicit 200 status", {
        out.status == StatusCode::OK
    });
    check("Json<T> sets Content-Type: application/json", {
        out.content_type.as_deref() == Some("application/json")
    });
    check("Json(Health) serialized the struct to {\"ok\":true}", {
        out.body == "{\"ok\":true}"
    });
}

// ── Section F: error handling — a Result<impl IntoResponse, E> handler ──────

/// A request DTO with an optional field. serde maps a missing field to `None`.
#[derive(Deserialize)]
struct Greet {
    name: Option<String>,
}

/// A handler that returns a `Result`. axum impls `IntoResponse` for
/// `Result<T, E>` when BOTH T and E are `IntoResponse`: `Ok` -> the success
/// response, `Err` -> the error response (here a `(StatusCode, String)`).
/// This is the idiomatic way to surface validation/business errors per-handler.
async fn greet(Json(p): Json<Greet>) -> Result<String, (StatusCode, String)> {
    match p.name {
        Some(n) if !n.is_empty() => Ok(format!("hello, {n}")),
        _ => Err((
            StatusCode::BAD_REQUEST,
            "missing or empty 'name'".to_owned(),
        )),
    }
}

async fn section_f() {
    banner("F — error handling: a Result<Ok, Err> handler");
    println!("  // `Result<T, E>` is IntoResponse when both arms are IntoResponse.");
    println!("  // The Ok arm returns 200 + the String; the Err arm returns the");
    println!("  // (StatusCode::BAD_REQUEST, message) tuple -> a 400 response.");
    println!("  let app = Router::new().route(\"/greet\", post(greet));");

    let app: Router = Router::new().route("/greet", post(greet));

    let ok = fire(app.clone(), post_json("/greet", r#"{"name":"rust"}"#)).await;
    println!(
        "  POST /greet {{\"name\":\"rust\"}} -> {}  body = {:?}",
        ok.status, ok.body
    );

    let err = fire(app, post_json("/greet", "{}")).await;
    println!(
        "  POST /greet {{}}              -> {}  body = {:?}",
        err.status, err.body
    );

    check("Result::Ok arm returns 200 + greeting", {
        ok.status == StatusCode::OK && ok.body == "hello, rust"
    });
    check("Result::Err arm returns 400 Bad Request", {
        err.status == StatusCode::BAD_REQUEST
    });
    check("Err arm body carries the error message", {
        err.body.contains("missing or empty")
    });
}

#[tokio::main]
async fn main() {
    println!("axum_basics.rs — Phase 8 bundle (web member).");
    println!("Every response below is produced by a Router driven IN-PROCESS.\n");
    section_a().await;
    section_b().await;
    section_c().await;
    section_d().await;
    section_e().await;
    section_f().await;
    banner("DONE — all sections printed");
}
