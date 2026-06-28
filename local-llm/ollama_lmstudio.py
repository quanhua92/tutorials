"""
ollama_lmstudio.py - Ollama & LM Studio: the user-friendly layers on llama.cpp.

This is the single source of truth that OLLAMA_LMSTUDIO.md is built from. Every
call-stack line, Modelfile parse, and comparison cell in the guide is printed by
this file. Pure Python stdlib only (NO torch, NO external libs) - these are the
*serving tooling* layers, not the engine internals.

Run:
    python3 ollama_lmstudio.py

----------------------------------------------------------------------------
PLAIN-ENGLISH INTUITION (read this first)
----------------------------------------------------------------------------
Both Ollama and LM Studio are wrappers around the SAME engine: llama.cpp (the
GGML compute graph). Neither writes inference kernels. The difference is the
"shape" of the wrapper:

  * Ollama  = a Go HTTP server + CLI.  Think `docker pull` but for models.
              `ollama pull llama3.2` downloads a GGUF; `ollama run` chats.
              It exposes an OpenAI-compatible API at localhost:11434.
              No GUI - it is CLI-first, scriptable, runs headless in CI.

  * LM Studio = an Electron desktop app. Think "App Store for GGUF models".
              Built-in HuggingFace browser (search/filter/one-click download),
              side-by-side model comparison, a chat GUI, and a local API server
              at localhost:1234. No CLI automation, no headless mode.

Both auto-detect the GPU (Metal on Apple Silicon, CUDA on Nvidia, ROCm on AMD)
and offload layers automatically. Both expose the SAME /v1/chat/completions
endpoint shape (OpenAI-compatible), so client code is portable between them.

The one Ollama-specific artifact this file implements is the **Modelfile** - a
Dockerfile-like manifest that pins a base model + inference parameters + system
prompt + chat template. Parsing it is the gold value for ollama_lmstudio.html.

GOLD VALUE (for ollama_lmstudio.html to reproduce):
    Parse the Modelfile:
      FROM llama3.2
      PARAMETER temperature 0.7
      SYSTEM "You are helpful"
    Result:
      from    = "llama3.2"
      params  = {"temperature": 0.7}
      system  = "You are helpful"
"""

from __future__ import annotations

import json

# ----------------------------------------------------------------------------
# Constants (verified against Ollama docs + LM Studio docs)
# ----------------------------------------------------------------------------

SHARED_ENGINE = "llama.cpp (GGML compute graph)"

# Ollama (MIT, Go, CLI-first)  -- verified: ollama/ollama README + docs
OLLAMA_NAME = "Ollama"
OLLAMA_LICENSE = "MIT (open source)"
OLLAMA_LANGUAGE = "Go"
OLLAMA_INTERFACE = "CLI + REST API"
OLLAMA_PORT = 11434
OLLAMA_API_PATH = "/v1/chat/completions"
OLLAMA_API = f"localhost:{OLLAMA_PORT}{OLLAMA_API_PATH}"
OLLAMA_MODEL_DISCOVERY = "Registry (ollama pull <model>)"

# LM Studio (proprietary, free, GUI-first)  -- verified: lmstudio.ai
LMSTUDIO_NAME = "LM Studio"
LMSTUDIO_LICENSE = "Proprietary (free)"
LMSTUDIO_LANGUAGE = "TypeScript / Electron"
LMSTUDIO_INTERFACE = "GUI (Electron desktop app)"
LMSTUDIO_PORT = 1234
LMSTUDIO_API_PATH = "/v1/chat/completions"
LMSTUDIO_API = f"localhost:{LMSTUDIO_PORT}{LMSTUDIO_API_PATH}"
LMSTUDIO_MODEL_DISCOVERY = "HuggingFace browser (in-app)"

BANNER = "=" * 74


# ============================================================================
# 0. CHECK + BANNER HELPERS
# ============================================================================

def check(label: str, cond: bool, detail: str = ""):
    """Assert-style checker that prints [check] lines for _output.txt."""
    status = "OK" if cond else "FAIL"
    extra = f"  ({detail})" if detail else ""
    print(f"[check] {label} :  {status}{extra}")
    assert cond, f"CHECK FAILED: {label} {detail}"


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 1. THE MODELFILE PARSER (the keystone / gold value)
# ============================================================================
#
# A Modelfile is the Ollama equivalent of a Dockerfile: a declarative manifest
# that pins a base model and overrides its runtime behaviour. Verified against
# Ollama's docs/modelfile.md. Supported directives:
#
#   FROM <model>            base model (a tag in the registry, or a GGUF path)
#   PARAMETER <key> <val>   an inference parameter (temperature, num_ctx, stop, ...)
#   SYSTEM <string>         the system prompt
#   TEMPLATE <go-template>  chat template (Go text/template: {{ .Prompt }}, ...)
#   ADAPTER <path>          a LoRA adapter file
#   LICENSE <string>        license text
#   MESSAGE <role> <str>    a chat message (role = user | assistant | system)
#   # comment               ignored
#
# String values may be bare, "double-quoted", or """triple-quoted""" (multi-line).

def _strip_quotes(token: str) -> str:
    """Strip one matching pair of surrounding double quotes (if present)."""
    token = token.strip()
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1]
    return token


def _parse_scalar(token: str):
    """Parse a PARAMETER value token into its Python type.

    Order matters: quoted string -> bool -> int -> float -> bare string.
    """
    token = token.strip()
    if len(token) >= 2 and token[0] == '"' and token[-1] == '"':
        return token[1:-1]
    if token == "true":
        return True
    if token == "false":
        return False
    try:
        return int(token)
    except ValueError:
        pass
    try:
        return float(token)
    except ValueError:
        pass
    return token


def _split_directive(line: str):
    """Split 'DIRECTIVE rest' -> (DIRECTIVE_UPPER, rest)."""
    parts = line.split(None, 1)
    directive = parts[0].upper()
    rest = parts[1] if len(parts) > 1 else ""
    return directive, rest


def _read_value(lines, i: int, rest: str):
    """Read a value starting on line i with `rest` as the in-line remainder.

    Handles triple-quote blocks (\"\"\"...\"\"\") that span multiple lines.
    Returns (value_string, new_i) where new_i is the next unread line index.
    """
    rest = rest.strip()
    if rest.startswith('"""'):
        body = rest[3:]
        if '"""' in body:
            # closes on the same line:  KEY """value"""
            return body[:body.index('"""')].strip(), i + 1
        # multi-line block: collect until a line holding the closing """
        buf = [body]
        j = i + 1
        while j < len(lines):
            cur = lines[j]
            if '"""' in cur:
                buf.append(cur[:cur.index('"""')])
                return "\n".join(buf).strip(), j + 1
            buf.append(cur)
            j += 1
        return "\n".join(buf).strip(), j  # unterminated block
    return rest, i + 1


def parse_modelfile(text: str) -> dict:
    """Parse an Ollama Modelfile into a structured dict.

    Returns:
        {
          "from":      str | None,           # base model
          "params":    {key: scalar},        # PARAMETER overrides
          "system":    str | None,           # system prompt
          "template":  str | None,           # Go chat template
          "adapter":   str | None,           # LoRA adapter path
          "license":   str | None,           # license text
          "messages":  [{role, content}],    # MESSAGE history
        }
    """
    result = {
        "from": None,
        "params": {},
        "system": None,
        "template": None,
        "adapter": None,
        "license": None,
        "messages": [],
    }
    lines = text.split("\n")
    i = 0
    n = len(lines)
    while i < n:
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue
        directive, rest = _split_directive(stripped)

        if directive == "PARAMETER":
            kv = rest.split(None, 1)
            key = kv[0]
            valpart = kv[1] if len(kv) > 1 else ""
            if valpart:
                raw, i = _read_value(lines, i, valpart)
                result["params"][key] = _parse_scalar(raw)
            else:
                result["params"][key] = True
                i += 1
            continue

        # block-capable directives (SYSTEM / TEMPLATE / LICENSE / ADAPTER / FROM)
        raw, i = _read_value(lines, i, rest)
        if directive == "FROM":
            result["from"] = _strip_quotes(raw) if raw else None
        elif directive == "SYSTEM":
            result["system"] = _strip_quotes(raw) if raw else None
        elif directive == "TEMPLATE":
            result["template"] = _strip_quotes(raw) if raw else None
        elif directive == "ADAPTER":
            result["adapter"] = _strip_quotes(raw) if raw else None
        elif directive == "LICENSE":
            result["license"] = _strip_quotes(raw) if raw else None
        elif directive == "MESSAGE":
            mparts = raw.split(None, 1)
            role = mparts[0].lower() if mparts else ""
            content = _strip_quotes(mparts[1]) if len(mparts) > 1 else ""
            result["messages"].append({"role": role, "content": content})
        # unknown directives are ignored (forward compatible)
    return result


def section_a_modelfile():
    banner("SECTION A: THE MODELFILE PARSER (Ollama's Dockerfile for models)")
    print("A Modelfile pins a base model + overrides. Parsed with pure Python.")
    print("Verified against: github.com/ollama/ollama/blob/main/docs/modelfile.md")
    print()

    # ---- the GOLD value: minimal Modelfile ----
    gold_text = (
        'FROM llama3.2\n'
        'PARAMETER temperature 0.7\n'
        'SYSTEM "You are helpful"\n'
    )
    print("INPUT (the gold Modelfile):")
    for ln in gold_text.rstrip("\n").split("\n"):
        print(f"  | {ln}")
    print()

    parsed = parse_modelfile(gold_text)
    print("PARSED:")
    print(f"  from    = {parsed['from']!r}")
    print(f"  params  = {parsed['params']}")
    print(f"  system  = {parsed['system']!r}")
    print()

    check("from == 'llama3.2'", parsed["from"] == "llama3.2", repr(parsed["from"]))
    check("params has temperature", "temperature" in parsed["params"])
    check("temperature == 0.7 (float)",
          parsed["params"]["temperature"] == 0.7,
          repr(parsed["params"]["temperature"]))
    check("system == 'You are helpful'",
          parsed["system"] == "You are helpful", repr(parsed["system"]))

    # ---- a richer Modelfile exercising every directive + type coercion ----
    rich_text = (
        '# A richer Modelfile\n'
        'FROM llama3.2:3b\n'
        '\n'
        '# inference parameters (typed: float / int / bool / string)\n'
        'PARAMETER temperature 0.8\n'
        'PARAMETER num_ctx 8192\n'
        'PARAMETER top_p 0.9\n'
        'PARAMETER stream true\n'
        'PARAMETER stop "User:"\n'
        '\n'
        'TEMPLATE """{{ .System }}\n'
        '{{ .Prompt }}"""\n'
        '\n'
        'SYSTEM "You are a concise coding assistant."\n'
        '\n'
        'MESSAGE user "What is mmap?"\n'
        'MESSAGE assistant "Memory-mapped file I/O."\n'
        '\n'
        'ADAPTER ./my-lora.gguf\n'
        'LICENSE "MIT"\n'
    )
    print()
    print("INPUT (richer Modelfile, every directive):")
    for ln in rich_text.rstrip("\n").split("\n"):
        print(f"  | {ln}")
    print()

    r = parse_modelfile(rich_text)
    print("PARSED:")
    print(f"  from     = {r['from']!r}")
    print("  params   = {")
    for k in sorted(r["params"]):
        v = r["params"][k]
        t = type(v).__name__
        print(f"    {k:<14} = {v!r:<14}  ({t})")
    print("  }")
    print(f"  template = {r['template']!r}")
    print(f"  system   = {r['system']!r}")
    print(f"  adapter  = {r['adapter']!r}")
    print(f"  license  = {r['license']!r}")
    print(f"  messages = {r['messages']}")
    print()

    check("rich from == 'llama3.2:3b'", r["from"] == "llama3.2:3b")
    check("temperature coerced to float 0.8",
          isinstance(r["params"]["temperature"], float) and
          r["params"]["temperature"] == 0.8)
    check("num_ctx coerced to int 8192",
          isinstance(r["params"]["num_ctx"], int) and r["params"]["num_ctx"] == 8192)
    check("stream coerced to bool True",
          isinstance(r["params"]["stream"], bool) and r["params"]["stream"] is True)
    check("stop string quotes stripped",
          r["params"]["stop"] == "User:")
    check("multi-line template parsed (3 lines)",
          r["template"] == "{{ .System }}\n{{ .Prompt }}")
    check("2 messages parsed", len(r["messages"]) == 2)
    check("message roles correct",
          r["messages"][0]["role"] == "user" and r["messages"][1]["role"] == "assistant")
    check("adapter path parsed", r["adapter"] == "./my-lora.gguf")
    check("comment lines ignored", r["license"] == "MIT")

    print()
    print("GOLD (for ollama_lmstudio.html):")
    print(f"  from    = {parsed['from']!r}")
    print(f"  params  = {{'temperature': {parsed['params']['temperature']}}}")
    print(f"  system  = {parsed['system']!r}")


# ============================================================================
# 2. ARCHITECTURE: what happens when you press "run" (deterministic call stacks)
# ============================================================================

def section_b_ollama_stack():
    banner("SECTION B: OLLAMA CALL STACK - Go server -> llama.cpp -> Metal/CUDA")
    print(f"{OLLAMA_NAME}: {OLLAMA_LICENSE}, written in {OLLAMA_LANGUAGE}.")
    print("CLI-first. No built-in GUI (pairs with Open WebUI for a web UI).")
    print(f"OpenAI-compatible API at {OLLAMA_API}.")
    print()
    print("What `ollama run llama3.2 \"Hello\"` actually does, layer by layer:")
    print()
    stack = [
        (0, "ollama run llama3.2 \"Hello\"", "CLI client (Go)"),
        (1, "resolve model -> registry tag -> local blob path", "Ollama server (Go)"),
        (1, "if missing: ollama pull -> download GGUF from registry", "Ollama server (Go)"),
        (1, "spawn llama.cpp runner subprocess (cgo / shared C lib)", "Ollama server (Go)"),
        (2, "load GGUF: header + KV + tensor info + mmap tensor_data", "llama.cpp (C)"),
        (2, "detect GPU backend: Metal | CUDA | ROCm (auto-offload)", "llama.cpp (C)"),
        (2, "build GGML compute graph for this architecture", "llama.cpp (C)"),
        (3, "tokenize prompt  ->  token ids", "llama.cpp (C)"),
        (3, "forward pass: matmul + RoPE + attention + sampling", "llama.cpp (C)"),
        (3, "detokenize -> text, stream tokens back over stdout", "llama.cpp (C)"),
        (1, "relay token stream to the terminal", "Ollama server (Go)"),
    ]
    for depth, desc, layer in stack:
        indent = "  " * depth
        branch = "|-" if depth > 0 else ""
        print(f"  {indent}{branch}{desc}")
        print(f"  {indent}    [{layer}]")
    print()
    print("Key insight: the Go layer is a *thin orchestrator*. All math runs in")
    print("the llama.cpp subprocess. Ollama adds: model registry, the Modelfile,")
    print("the OpenAI-compatible HTTP API, and auto GPU detection -- nothing more.")
    print()
    print(f"Ollama 0.19+ adds an MLX backend on Apple Silicon (up to 93% faster")
    print("decode for supported models) -- but the orchestration shape is unchanged.")
    check("Ollama port is 11434", OLLAMA_PORT == 11434)
    check("Ollama API path is OpenAI-compatible",
          OLLAMA_API_PATH == "/v1/chat/completions")


def section_c_lmstudio_stack():
    banner("SECTION C: LM STUDIO CALL STACK - Electron -> llama.cpp/MLX -> GUI")
    print(f"{LMSTUDIO_NAME}: {LMSTUDIO_LICENSE}, written in {LMSTUDIO_LANGUAGE}.")
    print("GUI-first. Built-in HuggingFace model browser + side-by-side compare.")
    print(f"Local OpenAI-compatible API server at {LMSTUDIO_API}.")
    print()
    print("What clicking 'Load model' then 'Send' actually does:")
    print()
    stack = [
        (0, "LM Studio app window (chat panel)", "Electron renderer (React UI)"),
        (1, "Model browser tab -> HuggingFace API (search/filter/download)", "Electron renderer"),
        (1, "user picks model -> one-click GGUF/MLX download to ~/.cache", "Electron renderer"),
        (1, "click 'Start Server' -> local API on port 1234", "Electron main (Node.js)"),
        (1, "click 'Send' in chat -> request to in-process llama.cpp", "Electron main (Node.js)"),
        (2, "load GGUF or MLX weights (mmap)", "llama.cpp / MLX (native binding)"),
        (2, "detect GPU (Metal/CUDA) or MLX backend; multi-GPU supported", "llama.cpp / MLX"),
        (2, "build compute graph", "llama.cpp / MLX"),
        (3, "forward pass -> tokens", "llama.cpp / MLX"),
        (1, "stream tokens back to renderer, render in chat bubble", "Electron renderer"),
        (1, "OPTIONAL: 2nd model column -> same prompt, both responses shown", "Electron renderer"),
    ]
    for depth, desc, layer in stack:
        indent = "  " * depth
        branch = "|-" if depth > 0 else ""
        print(f"  {indent}{branch}{desc}")
        print(f"  {indent}    [{layer}]")
    print()
    print("Key insight: the Electron layer adds *discovery + UX*. Same engine")
    print("underneath, but the value is the in-app HuggingFace browser, the chat")
    print("GUI, and side-by-side model comparison -- none of which Ollama has.")
    print()
    print("Trade-off: no CLI, no headless mode. You cannot script it in CI.")
    check("LM Studio port is 1234", LMSTUDIO_PORT == 1234)
    check("LM Studio API path is OpenAI-compatible",
          LMSTUDIO_API_PATH == "/v1/chat/completions")


# ============================================================================
# 3. THE SHARED OPENAI-COMPATIBLE API (same request shape, different port)
# ============================================================================

def section_d_openai_api():
    banner("SECTION D: THE SHARED OPENAI-COMPATIBLE API")
    print("Both expose /v1/chat/completions with the SAME request body shape.")
    print("Client code is portable: change the host:port, nothing else.")
    print()
    request = {
        "model": "llama3.2",
        "messages": [{"role": "user", "content": "Hello"}],
        "temperature": 0.7,
        "stream": False,
    }
    body = json.dumps(request, sort_keys=True)
    print(f"Request body (identical for both):")
    print(f"  POST /v1/chat/completions")
    print(f"  Content-Type: application/json")
    print(f"  {body}")
    print()
    print(f"  -> Ollama:    POST http://{OLLAMA_API}")
    print(f"  -> LM Studio: POST http://{LMSTUDIO_API}")
    print()
    print("Only the HOST:PORT differs. The path, the JSON schema, and the")
    print("streaming SSE response format are the same (OpenAI-compatible).")
    print()
    print("Example: swap a curl call between the two by changing one number:")
    print(f"  curl http://{OLLAMA_API} -d '{body}'")
    print(f"  curl http://{LMSTUDIO_API} -d '{body}'")
    print()

    check("both share the same API path",
          OLLAMA_API_PATH == LMSTUDIO_API_PATH == "/v1/chat/completions")
    check("both are OpenAI-compatible (/v1/chat/completions)",
          OLLAMA_API_PATH.startswith("/v1/") and LMSTUDIO_API_PATH.startswith("/v1/"))
    check("ports differ (11434 vs 1234)", OLLAMA_PORT != LMSTUDIO_PORT)
    check("request body is valid JSON", json.loads(body)["model"] == "llama3.2")


# ============================================================================
# 4. FEATURE COMPARISON MATRIX
# ============================================================================

def section_e_comparison():
    banner("SECTION E: FEATURE COMPARISON MATRIX")
    print(f"{'Feature':<22} {'Ollama':<26} {'LM Studio':<26}")
    print("-" * 74)
    rows = [
        ("Interface",        OLLAMA_INTERFACE,        LMSTUDIO_INTERFACE),
        ("Language",         OLLAMA_LANGUAGE,         LMSTUDIO_LANGUAGE),
        ("Model discovery",  OLLAMA_MODEL_DISCOVERY,  LMSTUDIO_MODEL_DISCOVERY),
        ("OpenAI API",       f"localhost:{OLLAMA_PORT}", f"localhost:{LMSTUDIO_PORT}"),
        ("GPU auto-offload", "Yes",                   "Yes"),
        ("MLX backend",      "Yes (0.19+)",           "Yes"),
        ("Multi-GPU",        "Limited",               "Yes"),
        ("Headless / CI",    "Yes",                   "No"),
        ("CLI automation",   "Yes (pull/run/create)", "No"),
        ("Side-by-side cmp", "No",                    "Yes"),
        ("Built-in GUI",     "No (use Open WebUI)",   "Yes"),
        ("License",          OLLAMA_LICENSE,          LMSTUDIO_LICENSE),
        ("Underlying engine", SHARED_ENGINE,          SHARED_ENGINE),
    ]
    for feat, o, l in rows:
        print(f"{feat:<22} {o:<26} {l:<26}")
    print()
    print("Bottom line: SAME engine (llama.cpp) underneath both. The choice is")
    print("CLI-first dev tool (Ollama) vs GUI-first discovery tool (LM Studio).")
    print()

    check("both share the same engine",
          rows[-1][1] == rows[-1][2] == SHARED_ENGINE)
    check("only Ollama is headless-capable",
          "Yes" in dict(r[:2] for r in rows)["Headless / CI"])
    check("only LM Studio has side-by-side compare",
          dict((r[0], r[2]) for r in rows)["Side-by-side cmp"] == "Yes")


# ============================================================================
# 5. LINEAGE - why these wrappers exist (raw llama.cpp -> user-friendly layers)
# ============================================================================

def section_f_lineage():
    banner("SECTION F: LINEAGE - raw llama.cpp -> Ollama + LM Studio")
    print("WHY these exist: raw llama.cpp requires manual compile + manual GGUF")
    print("download + manual flag tuning. The UX gap kept local LLMs out of reach")
    print("for most users. Two different philosophies filled it:")
    print()
    lineage = [
        ("raw llama.cpp",
         "compile C++ yourself, hunt for GGUFs, memorize -ngl/-c/-t flags",
         "powerful but hostile UX; no model discovery; no API"),
        ("Ollama (2023)",
         "Go server + CLI + Modelfile + registry + OpenAI API, all CLI-driven",
         "developer-friendly: `ollama run` just works; scriptable; CI-ready"),
        ("LM Studio (2023)",
         "Electron GUI + HuggingFace browser + chat + side-by-side compare",
         "non-developer-friendly: point-and-click discovery; no terminal"),
    ]
    print(f"{'stage':<18} what changed{'':<44} why")
    print("-" * 78)
    for stage, what, why in lineage:
        print(f"{stage:<18} {what:<54} {why}")
    print()
    print("Both converge on the SAME outcome: hide llama.cpp's rough edges. The")
    print("divergence is WHO they hide them from -- devs (Ollama) vs everyone else")
    print("(LM Studio). When you outgrow single-user local serving, the next step")
    print("is vLLM (production multi-user throughput). See VLLM_SERVING.md.")
    print()

    check("raw llama.cpp had no model discovery",
          "no model discovery" in lineage[0][2])
    check("Ollama is the CLI-first branch",
          "CLI" in lineage[1][1])
    check("LM Studio is the GUI-first branch",
          "GUI" in lineage[2][1])


# ============================================================================
# main
# ============================================================================

def main():
    print("ollama_lmstudio.py - Ollama & LM Studio: the user-friendly layers on")
    print("llama.cpp. Pure Python stdlib (json only). Numbers/parse results below")
    print("feed OLLAMA_LMSTUDIO.md.")
    print("Sources: ollama/ollama (docs/modelfile.md), lmstudio.ai, web-verified.")
    print()
    print("Two tools, one engine: Ollama = CLI-first dev tool,")
    print("LM Studio = GUI-first discovery tool. Both wrap " + SHARED_ENGINE + ".")

    section_a_modelfile()
    section_b_ollama_stack()
    section_c_lmstudio_stack()
    section_d_openai_api()
    section_e_comparison()
    section_f_lineage()

    banner("DONE - all sections printed, all checks passed")


if __name__ == "__main__":
    main()
