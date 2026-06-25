//! reqwest_client.rs — Phase 8 bundle (web member).
//!
//! GOAL (one line): show, by driving `reqwest` against an IN-PROCESS axum mock
//! server, the async HTTP CLIENT pattern — a pooled `Client` you reuse, typed
//! `get`/`post` builders, `.json` serialize/deserialize, `error_for_status`, a
//! `ClientBuilder::timeout`, and a deterministic retry loop.
//!
//! This is the GROUND TRUTH for REQWEST_CLIENT.md. Every status code and body
//! below is produced by a real `reqwest::Client` talking to a real `axum::serve`
//! server on a loopback socket; the `.md` guide pastes it verbatim. Never
//! hand-compute.
//!
//! DETERMINISM NOTE: the mock binds `127.0.0.1:0` — the OS picks a free port,
//! which we NEVER print (a random port would make `_output.txt` non-reproducible).
//! All response statuses/bodies are fixed, so output is byte-reproducible. No
//! external network is touched: this is loopback only.
//!
//! Run:
//!     just run reqwest_client   (== cargo run --bin reqwest_client)

use std::future::Future;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::Duration;

use axum::routing::{get, post};
use axum::{Json, Router};
use http::StatusCode;
use reqwest::Client;
use serde::{Deserialize, Serialize};

const BANNER_WIDTH: usize = 70;

/// A "fail K, then succeed" mock needs a counter shared across handler calls so
/// the handler itself stays a plain `async fn`. A fresh process starts this at
/// 0, which is what makes the retry section deterministic run-to-run.
static FLAKY_CALLS: AtomicU64 = AtomicU64::new(0);

/// How long `/slow` sleeps before answering. Must exceed the impatient client's
/// timeout so the timeout deterministically fires (and is well under any
/// reasonable per-section wall budget).
const SLOW_DELAY: Duration = Duration::from_millis(250);

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

// ── the in-process mock server (loopback only; the port is NEVER printed) ────

/// GET 200 body: `{"msg":"hi"}`.
#[derive(Serialize, Deserialize, Debug)]
struct Msg {
    msg: String,
}

/// POST body: echoed back verbatim by the mock, exercising serde round-trip.
#[derive(Serialize, Deserialize, Debug)]
struct Echo {
    name: String,
    qty: u32,
}

/// `GET /json` -> 200 + `{"msg":"hi"}`.
async fn json_msg() -> Json<Msg> {
    Json(Msg {
        msg: "hi".to_owned(),
    })
}

/// `POST /echo` -> echoes the deserialized body back as JSON (a serde round-trip
/// through reqwest's `.json()` on BOTH ends).
async fn echo(Json(p): Json<Echo>) -> Json<Echo> {
    Json(p)
}

/// `GET /missing` -> 404 Not Found. Used for the `error_for_status` demo:
/// `.send()` is `Ok` here (the HTTP call succeeded), the 404 is in the status.
async fn missing() -> StatusCode {
    StatusCode::NOT_FOUND
}

/// `GET /flaky` -> 503 for the first 2 calls, then 200. Models a transiently
/// failing upstream that recovers — exactly the retry target.
async fn flaky() -> StatusCode {
    // fetch_add returns the PREVIOUS value, so calls #0 and #1 see < 2 -> 503.
    let n = FLAKY_CALLS.fetch_add(1, Ordering::SeqCst);
    if n < 2 {
        StatusCode::SERVICE_UNAVAILABLE // 503 (transient)
    } else {
        StatusCode::OK // recovered
    }
}

/// `GET /slow` -> sleeps `SLOW_DELAY`, then 200. Models a hung server: an
/// impatient client's total timeout fires while we are still sleeping.
async fn slow() -> &'static str {
    tokio::time::sleep(SLOW_DELAY).await;
    "slow"
}

fn mock_router() -> Router {
    Router::new()
        .route("/json", get(json_msg))
        .route("/echo", post(echo))
        .route("/missing", get(missing))
        .route("/flaky", get(flaky))
        .route("/slow", get(slow))
}

/// Bind a loopback listener on an OS-chosen port, serve the mock on a detached
/// tokio task, and return the base URL (`http://127.0.0.1:{port}`). The task is
/// detached — it runs until the `#[tokio::main]` runtime drops at process exit.
/// The port is intentionally never printed: callers only build URLs from it and
/// assert on status/body, so `_output.txt` is byte-reproducible across runs.
async fn start_mock() -> String {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .expect("loopback bind succeeds");
    let addr = listener.local_addr().expect("local_addr");
    let app = mock_router();
    let _handle = tokio::spawn(async move {
        axum::serve(listener, app).await.expect("mock serve loop");
    });
    format!("http://{addr}")
}

// ── Section A: GET JSON — builder -> send -> Response -> .json::<T>() ────────

async fn section_a(client: &Client, base: &str) {
    banner("A — GET JSON: builder -> send -> Response -> .json::<T>()");
    println!("  // `Client::get(url)` returns a RequestBuilder; `.send().await` fires");
    println!("  // it over the pooled connection and yields a `Response`; then");
    println!("  // `.json::<T>()` deserializes the body via serde_json.");
    println!("  let resp = client.get(url).send().await?;   // url = mock + \"/json\"");

    let resp = client
        .get(format!("{base}/json"))
        .send()
        .await
        .expect("GET /json");
    let status = resp.status();
    let msg: Msg = resp.json().await.expect("decode Msg");
    println!("  GET /json -> {}  decoded msg.msg = {:?}", status, msg.msg);

    check("GET /json returns 200 OK", status == StatusCode::OK);
    check("deserialized struct field == \"hi\"", msg.msg == "hi");
}

// ── Section B: POST JSON — .json(&payload) serializes; mock echoes ───────────

async fn section_b(client: &Client, base: &str) {
    banner("B — POST JSON: .json(&payload) serializes; mock echoes; decode");
    println!("  // `.json(&body)` serializes any serde::Serialize type AND sets the");
    println!("  // `Content-Type: application/json` header for you.");
    println!("  let resp = client.post(url).json(&payload).send().await?;");

    let payload = Echo {
        name: "widget".to_owned(),
        qty: 7,
    };
    let resp = client
        .post(format!("{base}/echo"))
        .json(&payload)
        .send()
        .await
        .expect("POST /echo");
    let status = resp.status();
    let echoed: Echo = resp.json().await.expect("decode echoed Echo");
    println!(
        "  POST /echo {{name:\"widget\",qty:7}} -> {}  echoed name={:?} qty={}",
        status, echoed.name, echoed.qty
    );

    check("POST /echo returns 200 OK", status == StatusCode::OK);
    check("echoed payload name == \"widget\"", echoed.name == "widget");
    check("echoed payload qty == 7", echoed.qty == 7);
}

// ── Section C: status + error_for_status — 4xx/5xx become Err ────────────────

async fn section_c(client: &Client, base: &str) {
    banner("C — status + error_for_status: 4xx/5xx become Err");
    println!("  // `.send()` is Ok for a 404 too — the HTTP call itself succeeded;");
    println!("  // the error is encoded in `Response::status()`. `.error_for_status()`");
    println!("  // converts any 4xx/5xx into an `Err` so the `?` operator propagates it.");
    println!("  let res = client.get(url).send().await?.error_for_status();");

    let resp = client
        .get(format!("{base}/missing"))
        .send()
        .await
        .expect("GET /missing");
    let status = resp.status();
    println!(
        "  GET /missing -> {}  (send() is Ok; the 404 is in the status)",
        status
    );
    check(
        "GET /missing returns 404 Not Found",
        status == StatusCode::NOT_FOUND,
    );

    let res = resp.error_for_status();
    println!(
        "  resp.error_for_status() -> {}",
        if res.is_ok() { "Ok" } else { "Err" }
    );
    check(
        "error_for_status() turns a 404 Response into an Err",
        res.is_err(),
    );
}

// ── Section D: ClientBuilder::timeout — the #1 production rule ───────────────

async fn section_d(base: &str) {
    banner("D — ClientBuilder::timeout: the #1 production rule (always set one)");
    println!("  // The DEFAULT Client has NO timeout (docs: \"Default is no timeout\").");
    println!("  // In production ALWAYS set one via the builder — a hung server would");
    println!("  // otherwise hang your caller forever. The timeout is TOTAL: from the");
    println!("  // start of the connect until the response body is fully read.");

    // 1) The happy rule: a 1s timeout does not fire on an instant response.
    let sane = Client::builder()
        .timeout(Duration::from_secs(1))
        .build()
        .expect("client builds");
    let resp = sane.get(format!("{base}/json")).send().await.expect("send");
    let status = resp.status();
    println!("  Client::builder().timeout(1s) -> GET /json -> {}", status);
    check(
        "a 1s timeout does not fire against an instant response",
        status.is_success(),
    );

    // 2) The hung-server case: an impatient client vs a slow mock -> Err(timeout).
    let impatient = Client::builder()
        .timeout(Duration::from_millis(50))
        .build()
        .expect("client builds");
    let res = impatient.get(format!("{base}/slow")).send().await;
    match &res {
        Ok(r) => println!(
            "  Client::builder().timeout(50ms) -> GET /slow -> {} (unexpected Ok)",
            r.status()
        ),
        Err(e) => println!(
            "  Client::builder().timeout(50ms) -> GET /slow -> Err (is_timeout={})",
            e.is_timeout()
        ),
    }
    check(
        "a 50ms total timeout fires against a 250ms-slow server",
        res.is_err(),
    );
    check(
        "the timeout error reports is_timeout() == true",
        res.as_ref().is_err_and(|e| e.is_timeout()),
    );
}

// ── Section E: a retry loop for transient (5xx) failures ─────────────────────

/// Observable result of one retry campaign: how many attempts ran, whether a
/// 2xx was seen, and the status of the final attempt (None on transport error).
struct RetryOutcome {
    attempts: u32,
    success: bool,
    final_status: Option<StatusCode>,
}

/// Retry `do_request` up to `max_attempts` times until it returns a 2xx (or a
/// transport `Err`). Between attempts we back off briefly. This is the manual,
/// deterministic resilience primitive; reqwest also ships a built-in retry
/// policy on `ClientBuilder::retry` (see REQWEST_CLIENT.md).
async fn retry_transient<F, Fut>(max_attempts: u32, do_request: F) -> RetryOutcome
where
    F: Fn() -> Fut,
    Fut: Future<Output = Result<reqwest::Response, reqwest::Error>>,
{
    let mut attempts = 0;
    loop {
        attempts += 1;
        match do_request().await {
            Ok(resp) => {
                let st = resp.status();
                if st.is_success() {
                    return RetryOutcome {
                        attempts,
                        success: true,
                        final_status: Some(st),
                    };
                }
                if attempts >= max_attempts {
                    return RetryOutcome {
                        attempts,
                        success: false,
                        final_status: Some(st),
                    };
                }
            }
            Err(_) => {
                if attempts >= max_attempts {
                    return RetryOutcome {
                        attempts,
                        success: false,
                        final_status: None,
                    };
                }
            }
        }
        // fixed, tiny backoff — deterministic (no RNG, no jitter).
        tokio::time::sleep(Duration::from_millis(1)).await;
    }
}

async fn section_e(client: &Client, base: &str) {
    banner("E — a retry loop: fail-twice-then-ok mock recovers on attempt 3");
    println!("  // The `/flaky` mock returns 503 for the first 2 calls, then 200.");
    println!("  // `retry_transient(3, ..)` re-issues the GET on any non-2xx until it");
    println!("  // either sees a success or exhausts the budget. The shared mock");
    println!("  // counter is the authoritative witness of how many calls happened.");

    let url = format!("{base}/flaky");
    let outcome = retry_transient(3, || {
        let c = client.clone();
        let url = url.clone();
        async move { c.get(&url).send().await }
    })
    .await;
    let calls = FLAKY_CALLS.load(Ordering::SeqCst);
    println!(
        "  retry_transient(3) on /flaky -> attempts={}, success={}, final_status={:?}",
        outcome.attempts, outcome.success, outcome.final_status
    );
    println!("  the mock saw {} handler calls (one per attempt)", calls);

    check(
        "the flaky mock eventually recovered (success)",
        outcome.success,
    );
    check("recovered after exactly 3 attempts", outcome.attempts == 3);
    check(
        "final_status on success is 200 OK",
        outcome.final_status == Some(StatusCode::OK),
    );
    check("the mock counter agrees: 3 handler calls", calls == 3);
}

// ── Section F: Client reuse — ONE pooled client across many calls ────────────

async fn section_f(base: &str) {
    banner("F — Client reuse: ONE pooled client across many calls");
    println!("  // `Client` holds an internal connection pool wrapped in an `Arc`, so");
    println!("  // you should build ONE and reuse it (do NOT wrap it in your own Arc).");
    println!("  // Cloning a Client is cheap — it bumps the inner Arc and SHARES the pool.");

    let shared = Client::builder().build().expect("client builds");
    let r1 = shared
        .get(format!("{base}/json"))
        .send()
        .await
        .expect("send #1");
    let s1 = r1.status();
    let m1: Msg = r1.json().await.expect("decode #1");

    let r2 = shared
        .get(format!("{base}/json"))
        .send()
        .await
        .expect("send #2");
    let s2 = r2.status();
    let m2: Msg = r2.json().await.expect("decode #2");

    println!(
        "  call #1 -> {} msg={:?}    call #2 -> {} msg={:?}",
        s1, m1.msg, s2, m2.msg
    );
    check(
        "a second call via the SAME client succeeds (200)",
        s2.is_success(),
    );
    check(
        "both calls via one client decoded msg == \"hi\"",
        m1.msg == "hi" && m2.msg == "hi",
    );

    // A cheap clone shares the pool, so it can also drive calls.
    let clone = shared.clone();
    let r3 = clone
        .get(format!("{base}/json"))
        .send()
        .await
        .expect("send via clone");
    check(
        "Client::clone() shares the pool: a cloned client's call also succeeds",
        r3.status().is_success(),
    );
}

#[tokio::main]
async fn main() {
    println!("reqwest_client.rs — Phase 8 bundle (web member).");
    println!("Every response below comes from a reqwest client hitting an");
    println!("in-process axum mock on 127.0.0.1:0 (loopback; port never printed).\n");

    let base = start_mock().await;
    let client = Client::builder().build().expect("client builds");

    section_a(&client, &base).await;
    section_b(&client, &base).await;
    section_c(&client, &base).await;
    section_d(&base).await;
    section_e(&client, &base).await;
    section_f(&base).await;
    banner("DONE — all sections printed");
}
