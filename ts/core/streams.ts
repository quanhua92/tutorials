// streams.ts — Phase 5 bundle.
//
// GOAL (one line): show, by printing every chunk, how the WEB STREAMS standard
// (ReadableStream/WritableStream/TransformStream) processes data CHUNK-BY-CHUNK
// with FIFO order, backpressure via desiredSize/high-water-mark, and pipe
// chaining — the cross-language analog of Go's io.Reader/Writer/io.Copy and
// Rust's Read/Write traits.
//
// This is the GROUND TRUTH for STREAMS.md. Every number, table, and worked
// example in the guide is printed by this file. Change it -> re-run -> re-paste.
// Never hand-compute.
//
// LINEAGE (why this bundle exists): JS historically had TWO stream models: the
// Node-only EventEmitter-based Stream (the 'data'/'end'/'error' API), and —
// since 2016 — the WHATWG WEB STREAMS standard (ReadableStream/WritableStream/
// TransformStream), born in browsers and later landed in Node as `node:stream/
// web`. Web streams won: they are PROMISE-BASED (read/write return promises),
// ASYNC-ITERABLE (`for await...of`), and backpressure-aware by design
// (desiredSize). Node now exposes them as GLOBALS (identical to `node:stream/
// web`), so the same code runs in a browser, Deno, Bun, and Node. This bundle
// pins the web-streams model end-to-end and contrasts it with the legacy Node
// stream API + the bridges between them.
//
// DETERMINISM NOTE (§4.2 rule 4, overridden for streams): stream chunk ORDER is
// deterministic (FIFO). This file COLLECTS chunks into an array, AWAITS the full
// drain, then prints — it never prints from inside a callback. No Math.random /
// Date.now. Every stream is closed/cancelled before its section returns so the
// program drains fully before main resolves.
//
// Run:
//     pnpm exec tsx streams.ts   (or: just run streams)

// In Node, the Web Streams classes are exposed BOTH as globals AND as an
// explicit module (`node:stream/web`). We import them from the module path: the
// `@types/node` GLOBAL typings are a legacy compat shim (they lack `.from()` and
// widen chunk types), whereas the `node:stream/web` module carries the full
// WHATWG typings. At runtime the two are the SAME object (see Section D's
// identity check). The same code also runs unchanged against the browser global.
import {
  ReadableStream,
  WritableStream,
  TransformStream,
  TextDecoderStream,
  TextEncoderStream,
} from "node:stream/web";
import { Readable } from "node:stream";

const BANNER_WIDTH = 70;
const banner = "=".repeat(BANNER_WIDTH);

// sectionBanner prints a clearly delimited section divider (the house style).
function sectionBanner(title: string): void {
  console.log(`\n${banner}\nSECTION ${title}\n${banner}`);
}

// check asserts an invariant and prints a uniform [check] ... OK line.
// On failure it throws (non-zero exit) so `just check` / `just sweep` catch it.
function check(description: string, ok: boolean): void {
  if (!ok) {
    throw new Error("INVARIANT VIOLATED: " + description);
  }
  console.log(`[check] ${description}: OK`);
}

// seqEquals compares two readonly arrays element-by-element (structural), so the
// check is independent of reference identity while still asserting FIFO order.
function seqEquals<T>(a: readonly T[], b: readonly T[]): boolean {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i] !== b[i]) return false;
  }
  return true;
}

// ============================================================================
// Section A — ReadableStream: enqueue/close, the reader.read() loop, and async
// iteration (for await...of) — plus ReadableStream.from().
// ============================================================================

async function sectionA(): Promise<void> {
  sectionBanner("A — ReadableStream: enqueue/close, reader.read(), for await...of");

  // A ReadableStream wraps an UNDERLYING SOURCE. In the constructor's `start`
  // we enqueue chunks into an internal queue via the controller and close().
  // `start` runs SYNCHRONOUSLY at construction (like a Promise executor).
  const syncSource: ReadableStream<string> = new ReadableStream<string>({
    start(controller) {
      controller.enqueue("a");
      controller.enqueue("b");
      controller.enqueue("c");
      controller.close();
    },
  });

  // --- Reader API: read() returns { value, done }; loop until done. ----------
  // This is the explicit pull model: the consumer asks for one chunk at a time.
  const reader = syncSource.getReader();
  const collected: string[] = [];
  let sawDone = false;
  while (true) {
    const result = await reader.read();
    if (result.done) {
      sawDone = true;
      break;
    }
    collected.push(result.value);
  }
  reader.releaseLock();
  console.log("reader.read() loop collected chunks:", JSON.stringify(collected));
  console.log("final read() result.done === true:", sawDone);
  check("reader collects FIFO order [a,b,c]", seqEquals(collected, ["a", "b", "c"]));
  check("read() eventually returns { done: true }", sawDone === true);

  // A locked stream cannot get a second reader until the lock is released
  // (or the reader is cancelled). This is the one-reader-at-a-time rule.
  const lockable: ReadableStream<string> = new ReadableStream<string>({
    start(c) {
      c.enqueue("x");
      c.close();
    },
  });
  check("locked === false before getReader()", lockable.locked === false);
  const lr = lockable.getReader();
  check("locked === true after getReader()", lockable.locked === true);
  await lr.read();
  lr.releaseLock();
  check("locked === false after releaseLock()", lockable.locked === false);

  // --- Async iteration: streams implement the async iterable protocol. -------
  // `for await...of` acquires a reader, pulls chunks until done, and releases the
  // lock automatically. Breaking out early cancels the stream by default.
  const iterSource: ReadableStream<string> = new ReadableStream<string>({
    start(controller) {
      controller.enqueue("a");
      controller.enqueue("b");
      controller.enqueue("c");
      controller.close();
    },
  });
  const iterated: string[] = [];
  for await (const chunk of iterSource) {
    iterated.push(chunk);
  }
  console.log("for await...of collected chunks:", JSON.stringify(iterated));
  check("for await...of collects FIFO [a,b,c]", seqEquals(iterated, ["a", "b", "c"]));

  // --- ReadableStream.from(): static factory from any (async) iterable. ------
  // Turns an Array/Set/Map/generator/async-iterator into a ReadableStream.
  const fromArr: ReadableStream<string> = ReadableStream.from<string>(["p", "q", "r"]);
  const fromGot: string[] = [];
  for await (const chunk of fromArr) {
    fromGot.push(chunk);
  }
  console.log("ReadableStream.from(['p','q','r']) chunks:", JSON.stringify(fromGot));
  check("ReadableStream.from preserves iterable order", seqEquals(fromGot, ["p", "q", "r"]));

  // > 🔗 ITERATORS_GENERATORS — `for await...of` IS the async-iterator protocol;
  //   a ReadableStream is just an async iterable whose .next() pulls a chunk.
}

// ============================================================================
// Section B — WritableStream: write/close, pipeTo, and BACKPRESSURE
// (desiredSize + the high-water mark).
// ============================================================================

async function sectionB(): Promise<void> {
  sectionBanner("B — WritableStream, pipeTo, and backpressure (desiredSize/HWM)");

  // A WritableStream wraps an UNDERLYING SINK. Its `write(chunk)` is called once
  // per chunk; the writer.write(chunk) PROMISE resolves once the sink has
  // accepted it. write() may be async (return a promise) to apply backpressure.
  const sinkReceived: string[] = [];
  const sink: WritableStream<string> = new WritableStream<string>({
    write(chunk) {
      sinkReceived.push(chunk);
    },
  });
  const writer: WritableStreamDefaultWriter<string> = sink.getWriter();
  await writer.write("x");
  await writer.write("y");
  await writer.write("z");
  await writer.close();
  console.log("WritableStream.write() received chunks:", JSON.stringify(sinkReceived));
  check("writable receives writes in FIFO order [x,y,z]", seqEquals(sinkReceived, ["x", "y", "z"]));

  // --- pipeTo(): the whole readable -> writable pipeline in one call. --------
  // pipeTo pulls from the readable, pushes to the writable, propagates
  // backpressure between them, and resolves when the readable closes AND the
  // writable's close() resolves. This is the JS analog of Go's io.Copy.
  const pipeSinkReceived: number[] = [];
  const pipeSource: ReadableStream<number> = new ReadableStream<number>({
    start(controller) {
      controller.enqueue(1);
      controller.enqueue(2);
      controller.enqueue(3);
      controller.close();
    },
  });
  const pipeSink: WritableStream<number> = new WritableStream<number>({
    write(chunk) {
      pipeSinkReceived.push(chunk);
    },
  });
  await pipeSource.pipeTo(pipeSink);
  console.log("pipeTo delivered chunks:", JSON.stringify(pipeSinkReceived));
  check("pipeTo round-trips readable -> writable [1,2,3]", seqEquals(pipeSinkReceived, [1, 2, 3]));

  // --- BACKPRESSURE: desiredSize and the high-water mark. --------------------
  // Each stream has an internal queue + a QUEUING STRATEGY (default:
  // CountQueuingStrategy, high-water mark 1). desiredSize is:
  //     desiredSize = highWaterMark - totalSizeOfChunksInQueue
  // When desiredSize <= 0 the producer is overflowing the consumer → BACKPRESSURE
  // (slow down). The 2nd constructor arg is the strategy (NOT a sink property).
  const desiredAt: Array<readonly [string, number | null]> = [];
  const readableHwm3: ReadableStream<string> = new ReadableStream<string>(
    {
      start(controller) {
        desiredAt.push(["before any enqueue (HWM 3)", controller.desiredSize]);
        controller.enqueue("a");
        desiredAt.push(["after enqueue 'a'", controller.desiredSize]);
        controller.enqueue("b");
        desiredAt.push(["after enqueue 'b'", controller.desiredSize]);
        controller.enqueue("c");
        desiredAt.push(["after enqueue 'c' (desiredSize hits 0)", controller.desiredSize]);
        controller.close();
      },
    },
    new CountQueuingStrategy({ highWaterMark: 3 }),
  );
  // Drain so the queue fully flushes before we read desiredSize observations.
  const drain1: string[] = [];
  for await (const chunk of readableHwm3) {
    drain1.push(chunk);
  }
  console.log("ReadableStream desiredSize vs internal queue (highWaterMark = 3):");
  for (const [label, size] of desiredAt) {
    console.log(`  ${label.padEnd(44)} -> desiredSize = ${size}`);
  }
  check("desiredSize starts at HWM (3)", desiredAt[0]![1] === 3);
  check("desiredSize decreases by 1 per enqueued chunk", desiredAt[1]![1] === 2);
  check("desiredSize hits 0 at the high-water mark (backpressure)", desiredAt[3]![1] === 0);

  // On the WRITER side, writer.write() returns a promise that resolves once the
  // sink drains enough to be "ready" again. Awaiting it IS respecting
  // backpressure; writer.ready is the same signal without writing.
  const bpSink: WritableStream<string> = new WritableStream<string>(
    { write() {} },
    new CountQueuingStrategy({ highWaterMark: 2 }),
  );
  const bpWriter: WritableStreamDefaultWriter<string> = bpSink.getWriter();
  console.log("  writer.desiredSize at open (HWM 2):", bpWriter.desiredSize);
  check("writer.desiredSize opens at its HWM (2)", bpWriter.desiredSize === 2);
  await bpWriter.close();
  check("writer.desiredSize === 0 after close()", bpWriter.desiredSize === 0);
}

// ============================================================================
// Section C — TransformStream + pipeThrough: transform each chunk mid-pipe.
// ============================================================================

async function sectionC(): Promise<void> {
  sectionBanner("C — TransformStream + pipeThrough (transform each chunk)");

  // A TransformStream is a readable+writable PAIR: write into .writable, the
  // `transform(chunk, controller)` runs per chunk, and you read transformed
  // chunks from .readable. pipeThrough wires readable -> transform.writable and
  // hands you transform.readable — a chainable, backpressure-correct pipeline.
  const upper: TransformStream<string, string> = new TransformStream<string, string>({
    transform(chunk, controller) {
      controller.enqueue(chunk.toUpperCase());
    },
  });

  const tSource: ReadableStream<string> = new ReadableStream<string>({
    start(controller) {
      controller.enqueue("foo");
      controller.enqueue("bar");
      controller.enqueue("baz");
      controller.close();
    },
  });

  const tSinkReceived: string[] = [];
  const tSink: WritableStream<string> = new WritableStream<string>({
    write(chunk) {
      tSinkReceived.push(chunk);
    },
  });

  // src.pipeThrough(upper) -> TransformStream's readable (uppercase chunks)
  //          .pipeTo(sink) -> terminal sink. Order is preserved FIFO.
  await tSource.pipeThrough(upper).pipeTo(tSink);
  console.log("pipeThrough(uppercase) delivered chunks:", JSON.stringify(tSinkReceived));
  check("pipeThrough transforms each chunk [FOO,BAR,BAZ]", seqEquals(tSinkReceived, ["FOO", "BAR", "BAZ"]));

  // A practical composed chain: two NEW transforms (a TransformStream is
  // single-use — once piped through, its writable is locked/closed, so reuse
  // would deliver nothing). Here we uppercase, then bracket each chunk.
  const upper2: TransformStream<string, string> = new TransformStream<string, string>({
    transform(chunk, controller) {
      controller.enqueue(chunk.toUpperCase());
    },
  });
  const tagger: TransformStream<string, string> = new TransformStream<string, string>({
    transform(chunk, controller) {
      controller.enqueue(`[${chunk}]`);
    },
  });
  const chainSrc: ReadableStream<string> = new ReadableStream<string>({
    start(controller) {
      controller.enqueue("one");
      controller.enqueue("two");
      controller.close();
    },
  });
  const chainSinkReceived: string[] = [];
  const chainSink: WritableStream<string> = new WritableStream<string>({
    write(chunk) {
      chainSinkReceived.push(chunk);
    },
  });
  await chainSrc.pipeThrough(upper2).pipeThrough(tagger).pipeTo(chainSink);
  console.log("composed pipeThrough (upper -> tagger) chunks:", JSON.stringify(chainSinkReceived));
  check("composed transform chain [one]->[ONE], [two]->[TWO]", seqEquals(chainSinkReceived, ["[ONE]", "[TWO]"]));
}

// ============================================================================
// Section D — Node web streams (node:stream/web), legacy Node streams, and the
// bridges between them (Readable.from / Readable.fromWeb / Readable.toWeb).
// ============================================================================

async function sectionD(): Promise<void> {
  sectionBanner("D — Node web streams, legacy Node streams, and bridges");

  // `node:stream/web` re-exports the EXACT SAME global classes (identity-equal),
  // so web-streams code written once runs unchanged in browsers and Node. (We
  // access the global via a typed cast because @types/node's global ReadableStream
  // value is a legacy compat shim, not the constructor.)
  const globalRS = (globalThis as { ReadableStream: unknown }).ReadableStream;
  console.log("node:stream/web.ReadableStream === globalThis.ReadableStream:", ReadableStream === globalRS);
  check("node:stream/web re-exports the SAME global ReadableStream (identity)", ReadableStream === globalRS);

  // --- The LEGACY Node stream API: EventEmitter-based ('data'/'end'/'error'). -
  // Pre-web-streams Node model: a stream.Readable EMITS events. This is the
  // older, callback/event API that web streams supersedes. Readable.from()
  // turns any (async) iterable into such a Node Readable.
  const legacy: Readable = Readable.from(["A", "B", "C"]);
  const legacyReceived: string[] = [];
  await new Promise<void>((resolve, reject) => {
    legacy.on("data", (chunk: Buffer | string) => {
      legacyReceived.push(typeof chunk === "string" ? chunk : chunk.toString("utf8"));
    });
    legacy.on("end", resolve);
    legacy.on("error", reject);
  });
  console.log("legacy Node stream 'data'/'end' chunks:", JSON.stringify(legacyReceived));
  check("legacy Node stream emits 'data' then 'end' [A,B,C]", seqEquals(legacyReceived, ["A", "B", "C"]));

  // --- Bridge 1: async iterable -> Node Readable (Readable.from). -------------
  // Readable.from accepts an async generator; chunks flow as Node stream data.
  async function* gen(): AsyncGenerator<string> {
    yield "p";
    yield "q";
  }
  const fromGen: Readable = Readable.from(gen());
  const fromGenReceived: string[] = [];
  for await (const chunk of fromGen) {
    fromGenReceived.push(typeof chunk === "string" ? chunk : (chunk as Buffer).toString("utf8"));
  }
  console.log("Readable.from(asyncGenerator) chunks:", JSON.stringify(fromGenReceived));
  check("Readable.from(asyncGenerator) yields [p,q]", seqEquals(fromGenReceived, ["p", "q"]));

  // --- Bridge 2: web ReadableStream <-> Node Readable (fromWeb / toWeb). ------
  // Node's stream API is fully interoperable with web streams via these adapters.
  const webRs: ReadableStream<string> = new ReadableStream<string>({
    start(controller) {
      controller.enqueue("m");
      controller.enqueue("n");
      controller.close();
    },
  });
  // fromWeb: web ReadableStream -> Node Readable. PITFALL: Node coalesces
  // consecutive STRING chunks into a SINGLE Buffer ("m"+"n" -> "mn"), because
  // Node Readables model string data as a contiguous byte stream, not chunked
  // values. (Byte/Uint8Array chunks DO preserve boundaries.) We decode and show
  // the coalesced result — this is the real, deterministic Node behavior.
  const nodeFromWeb: Readable = Readable.fromWeb(webRs);
  const fromWebReceived: string[] = [];
  for await (const chunk of nodeFromWeb) {
    fromWebReceived.push(typeof chunk === "string" ? chunk : (chunk as Buffer).toString("utf8"));
  }
  console.log("Readable.fromWeb(web ReadableStream) chunks:", JSON.stringify(fromWebReceived));
  check("Readable.fromWeb coalesces string chunks into one Buffer ('m'+'n' -> 'mn')", seqEquals(fromWebReceived, ["mn"]));

  // toWeb: Node Readable -> web ReadableStream. We convert a Node Readable to a
  // web stream and drain it via for await...of. (Writable.toWeb mirrors this for
  // Node Writable -> web WritableStream.)
  const nodeReadable: Readable = Readable.from(["S", "T"]);
  const webFromNode = Readable.toWeb(nodeReadable) as unknown as ReadableStream<Uint8Array | string>;
  const toWebReceived: string[] = [];
  for await (const chunk of webFromNode) {
    toWebReceived.push(typeof chunk === "string" ? chunk : new TextDecoder().decode(chunk));
  }
  console.log("Readable.toWeb(nodeReadable) chunks:", JSON.stringify(toWebReceived));
  check("Readable.toWeb bridges Node->web ['S','T']", seqEquals(toWebReceived, ["S", "T"]));
}

// ============================================================================
// Section E — Encoding streams (TextEncoderStream/TextDecoderStream) and
// cancellation (cancel(reason) / AbortSignal).
// ============================================================================

async function sectionE(): Promise<void> {
  sectionBanner("E — Encoding streams (TextEncoder/DecoderStream) + cancellation");

  // Chunks are either STRINGs or byte chunks (Uint8Array). TextDecoderStream is
  // a TransformStream whose writable accepts bytes and whose readable emits
  // string: pipe bytes in, get decoded strings out. (TextEncoderStream is the
  // inverse: string in -> bytes out.) We assert the input type of the decoder
  // (its declared writable is the wider BufferSource; narrowing to Uint8Array
  // matches the byte chunks we actually produce).
  const bytes: Uint8Array = new TextEncoder().encode("Hello");
  const byteSource: ReadableStream<Uint8Array> = new ReadableStream<Uint8Array>({
    start(controller) {
      controller.enqueue(bytes);
      controller.close();
    },
  });
  const decoder = new TextDecoderStream() as unknown as TransformStream<Uint8Array, string>;
  const decodedSink: string[] = [];
  const decodedWritable: WritableStream<string> = new WritableStream<string>({
    write(chunk) {
      decodedSink.push(chunk);
    },
  });
  await byteSource.pipeThrough(decoder).pipeTo(decodedWritable);
  console.log("TextDecoderStream decoded bytes 'Hello' ->:", JSON.stringify(decodedSink));
  check("TextDecoderStream decodes Uint8Array chunks to strings ['Hello']", seqEquals(decodedSink, ["Hello"]));

  // TextEncoderStream: string in -> bytes out. Round-trip encode then decode to
  // prove bytes are carried faithfully through the chain.
  const encSink: Uint8Array[] = [];
  const encWritable: WritableStream<Uint8Array> = new WritableStream<Uint8Array>({
    write(chunk) {
      encSink.push(chunk);
    },
  });
  const strSource: ReadableStream<string> = new ReadableStream<string>({
    start(controller) {
      controller.enqueue("World");
      controller.close();
    },
  });
  await strSource.pipeThrough(new TextEncoderStream()).pipeTo(encWritable);
  const redecoded = encSink.map((b) => new TextDecoder().decode(b));
  console.log("TextEncoderStream encoded 'World' -> bytes -> re-decoded:", JSON.stringify(redecoded));
  check("TextEncoderStream encodes string to Uint8Array (round-trips to 'World')", seqEquals(redecoded, ["World"]));

  // --- Cancellation: cancel(reason) and AbortSignal. -------------------------
  // A consumer can abandon a stream: readable.cancel(reason) invokes the source's
  // `cancel(reason)` hook and the stream settles to a closed/done state. After a
  // cancel, reads complete with { done: true }. pipeTo/pipeThrough accept an
  // AbortSignal to cancel mid-flight from an outside caller.
  const cancelReasons: unknown[] = [];
  const cancellable: ReadableStream<string> = new ReadableStream<string>({
    start(controller) {
      controller.enqueue("first");
      // NOTE: do NOT enqueue/close further — we cancel before draining.
    },
    cancel(reason) {
      cancelReasons.push(reason);
    },
  });
  await cancellable.cancel("user aborted");
  const postCancel = await cancellable.getReader().read();
  console.log("cancel() hook received reason:", JSON.stringify(cancelReasons));
  console.log("read() after cancel():", JSON.stringify({ done: postCancel.done }));
  check("cancel(reason) forwards the reason to the source hook", seqEquals(cancelReasons, ["user aborted"]));
  check("read() after cancel() resolves with { done: true }", postCancel.done === true);

  // pipeTo with an AbortController: aborting the signal cancels the pipe. The
  // pipeTo promise rejects with an AbortError; both ends are torn down.
  const abortSink: string[] = [];
  const abortSource: ReadableStream<string> = new ReadableStream<string>({
    start(controller) {
      controller.enqueue("keep");
      controller.enqueue("drop1");
      controller.enqueue("drop2");
      controller.close();
    },
  });
  const abortWritable: WritableStream<string> = new WritableStream<string>({
    write(chunk) {
      abortSink.push(chunk);
    },
  });
  const ac = new AbortController();
  const pipePromise = abortSource.pipeTo(abortWritable, { signal: ac.signal });
  ac.abort(new Error("aborted by controller"));
  let abortedWith = "";
  try {
    await pipePromise;
  } catch (err) {
    abortedWith = err instanceof Error ? err.message : String(err);
  }
  console.log("pipeTo aborted via AbortSignal:", JSON.stringify(abortedWith));
  check("pipeTo({signal}) rejects with the abort reason on AbortController.abort()", abortedWith === "aborted by controller");
}

// ============================================================================
// main
// ============================================================================

async function main(): Promise<void> {
  console.log("streams.ts — Phase 5 bundle (Web Streams standard).");
  console.log("Every chunk below is collected from a real stream by this file;");
  console.log("the .md guide pastes it verbatim. Nothing is hand-computed.");
  console.log("");
  console.log("Reminder: streams process data CHUNK-BY-CHUNK (not all in memory).");
  console.log("Chunk ORDER is FIFO-deterministic; we collect, drain, then print.");
  await sectionA();
  await sectionB();
  await sectionC();
  await sectionD();
  await sectionE();
  sectionBanner("DONE — all sections printed, all streams drained");
}

await main();
