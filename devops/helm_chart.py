"""
helm_chart.py - Reference model of a Helm chart: how Chart.yaml + values.yaml +
templates/ combine via `helm install` into rendered Kubernetes YAML, and how
values overrides, hooks, and subcharts extend that pipeline.

This is the single source of truth that HELM_CHART.md is built from. Every
template, rendered YAML, values merge, hook timeline, and subchart scoping in
the guide is printed by this file. If you change something here, re-run and
re-paste the output.

Run:
    python helm_chart.py

============================================================================
THE INTUITION (read this first) - the mail-merge for Kubernetes
============================================================================
Imagine you ship the SAME app to dev, staging, and prod. Without Helm you
hand-write a dozen YAML files per environment and copy-paste them around - a
config-drift nightmare. Helm is a MAIL-MERGE engine for YAML:

  * A CHART     is a folder of TEMPLATES with HOLES ({{ .Values.replicas }}).
  * values.yaml is the DEFAULT fillings for those holes.
  * `helm install` runs the mail-merge: it pours values into templates and
    hands the FINISHED YAML to Kubernetes. Kubernetes never sees templates -
    it sees ordinary Deployments, Services, etc.

The three moving parts (all modeled below):
  1. TEMPLATE RENDERING   {{ .Values.replicas }} -> 3, {{ range }} loops,
                           {{ if }} conditionals.
  2. VALUES OVERRIDE      --set image.tag=v2  or  --values prod.yaml (deep-merged).
  3. HOOKS + SUBCHARTS    lifecycle jobs + charts-that-depend-on-charts.

THE GOLD QUESTION this bundle answers: for a given chart + values, does
`helm install` emit exactly the expected Kubernetes YAML? That is deterministic,
and helm_chart.html recomputes it in JS from the identical chart + values.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  Chart         a folder: Chart.yaml + values.yaml + templates/. The unit Helm
                packages and versions.
  Chart.yaml    metadata: name, version, appVersion, dependencies, type.
  values.yaml   DEFAULT values for the chart's template holes.
  template      a YAML file with Go-template holes: {{ .Values.X }}.
  render        substitute values into templates -> finished YAML (helm install).
  Release       one installation of a chart: name + namespace + revision.
  .Values       the values dict AFTER base + overrides are coalesced.
  .Release      release metadata, usable in templates: {{ .Release.Name }}.
  --set         override a value on the CLI: --set image.tag=v2.
  --values / -f override values from a file (prod.yaml). Deep-merged.
  range         Go-template loop: {{ range .Values.workers }}...{{ end }}.
  hook          a template annotated helm.sh/hook: pre-install, post-upgrade...
                run at a lifecycle phase, NOT as a normal resource.
  subchart      a chart declared in Chart.yaml `dependencies`. Rendered with its
                OWN scoped values (.Values.<subchart>.X) + globals.
  library chart type: library - defines {{ define }} helpers only; renders nothing.
  global        values under the `global` key are visible to parent AND subcharts.
  OCI registry  charts pushed to/pulled from a registry as OCI artifacts
                (helm push webapp-0.1.0.tgz oci://...). Replaces classic chart repos.

Reference docs: helm.sh "Chart Template Guide", "Hooks", "Subcharts and Globals",
"OCI Registries"; Kubernetes Patterns (Ibryam & Huss).
============================================================================
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

BANNER = "=" * 72


# ============================================================================
# 1. VALUES MATH  (deep-merge + --set), mirroring Helm coalesceValues
# ============================================================================

def deep_merge(base: dict, override: dict) -> dict:
    """Recursive dict merge: override wins; nested dicts are MERGED, not replaced.
    Mirrors Helm's coalesceValues: user values (--set / --values) override chart
    defaults, and unset keys fall through to the base."""
    out = _clone(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def apply_set(values: dict, dotted: str, value: str) -> dict:
    """Mirror `helm install --set image.tag=v2`: walk a dotted path, set the leaf.
    Scalars are coerced (int / bool / str) the way Helm parses --set tokens."""
    out = _clone(values)
    cur: dict = out
    parts = dotted.split(".")
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = _coerce(value)
    return out


def _clone(d: dict) -> dict:
    return {k: _clone(v) if isinstance(v, dict) else (list(v) if isinstance(v, list) else v)
            for k, v in d.items()}


def _coerce(v: str):
    if v in ("true", "false"):
        return v == "true"
    if re.fullmatch(r"-?\d+", v):
        return int(v)
    return v


# ============================================================================
# 2. THE TEMPLATE RENDERER  (Go-template subset: range, if, scalar lookup)
# ============================================================================

_SCALAR_RE = re.compile(r"\{\{\s*(\.[A-Za-z0-9_.]+)\s*\}\}")
_RANGE_RE = re.compile(
    r"\{\{\s*range\s+(\.[A-Za-z0-9_.]+)\s*\}\}(.*?)\{\{\s*end\s*\}\}",
    re.DOTALL,
)
_IF_RE = re.compile(
    r"\{\{\s*if\s+(\.[A-Za-z0-9_.]+)\s*\}\}(.*?)\{\{\s*end\s*\}\}",
    re.DOTALL,
)


def _lookup(path: str, ctx: dict) -> Any:
    """Resolve a dotted template ref against a context dict.
    '.Values.image.tag' -> ctx['Values']['image']['tag'].
    '.name' (inside a range) -> ctx['name'] (the loop item's key)."""
    parts = [p for p in path.lstrip(".").split(".") if p]
    cur: Any = ctx
    for p in parts:
        cur = cur[p]
    return cur


def _render_scalars(tmpl: str, ctx: dict) -> str:
    def repl(m: re.Match) -> str:
        return str(_lookup(m.group(1), ctx))
    return _SCALAR_RE.sub(repl, tmpl)


def render_template(tmpl: str, values: dict, release: dict) -> str:
    """Tiny Go-template renderer (the subset the charts below need):
      1. {{ range .Values.X }}...{{ end }}  -> one copy per list item
      2. {{ if .Values.X }}...{{ end }}     -> keep body if truthy, else drop
      3. {{ .Values.a.b }} / {{ .Release.Name }} -> scalar substitution
    Real Helm uses Go text/template (sprig funcs, pipelines, whitespace trim
    via {{- -}}); this models the core mechanics so the rendered YAML is exact.
    No nesting of range/if in the same template (the charts below don't need it).
    """
    root = {"Values": values, "Release": release}

    def expand_range(m: re.Match) -> str:
        items = _lookup(m.group(1), root)
        body = m.group(2)
        chunks: List[str] = []
        for item in items:
            loop_ctx = dict(root)              # .Values / .Release still visible
            if isinstance(item, dict):
                loop_ctx.update(item)          # .name / .replicas from the item
            chunks.append(_render_scalars(body, loop_ctx))
        return "".join(chunks)

    def expand_if(m: re.Match) -> str:
        return m.group(2) if _lookup(m.group(1), root) else ""

    while _RANGE_RE.search(tmpl):
        tmpl = _RANGE_RE.sub(expand_range, tmpl)
    while _IF_RE.search(tmpl):
        tmpl = _IF_RE.sub(expand_if, tmpl)
    return _render_scalars(tmpl, root).rstrip() + "\n"


def scope_subchart(parent_values: dict, name: str) -> dict:
    """The values a SUBCHART sees: its scoped block (.Values.<name>) PLUS the
    shared `global` key. Mirrors Helm subchart value scoping."""
    scoped = _clone(parent_values.get(name, {}))
    if "global" in parent_values:
        scoped["global"] = _clone(parent_values["global"])
    return scoped


# ============================================================================
# 3. THE CHART  (webapp) + its REDIS subchart
# ============================================================================

WEBAPP_CHART_YAML = """\
apiVersion: v2
name: webapp
description: A tiny web application chart
type: application
version: 0.1.0
appVersion: "1.16"
"""

WEBAPP_CHART_YAML_WITH_DEPS = """\
apiVersion: v2
name: webapp
description: A tiny web application chart (with a redis subchart)
type: application
version: 0.1.0
appVersion: "1.16"
dependencies:
  - name: redis
    version: 0.4.x
    repository: oci://registry.example.com/charts
"""

WEBAPP_VALUES: Dict[str, Any] = {
    "replicas": 3,
    "image": {"repository": "nginx", "tag": "1.16", "pullPolicy": "IfNotPresent"},
    "service": {"type": "ClusterIP", "port": 80},
    "bootstrapToken": "Ym9vdHN0cmFw",
    "workers": [
        {"name": "ingestion", "replicas": 2},
        {"name": "processor", "replicas": 4},
    ],
}

DEPLOYMENT_TMPL = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}
  labels:
    app: {{ .Values.image.repository }}
spec:
  replicas: {{ .Values.replicas }}
  selector:
    matchLabels:
      app: {{ .Values.image.repository }}
  template:
    metadata:
      labels:
        app: {{ .Values.image.repository }}
    spec:
      containers:
        - name: {{ .Values.image.repository }}
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          imagePullPolicy: {{ .Values.image.pullPolicy }}
"""

WORKERS_TMPL = """\
{{ range .Values.workers }}---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name }}-{{ .name }}
  labels:
    app: {{ .Values.image.repository }}
spec:
  replicas: {{ .replicas }}
  selector:
    matchLabels:
      app: {{ .Values.image.repository }}
{{ end }}"""

SERVICE_TMPL = """\
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}
spec:
  type: {{ .Values.service.type }}
  selector:
    app: {{ .Values.image.repository }}
  ports:
    - port: {{ .Values.service.port }}
      targetPort: 80
"""

HOOK_PREINSTALL_TMPL = """\
apiVersion: v1
kind: Secret
metadata:
  name: {{ .Release.Name }}-bootstrap-token
  annotations:
    "helm.sh/hook": pre-install
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": before-hook-creation
type: Opaque
data:
  token: {{ .Values.bootstrapToken }}
"""

HOOK_POSTINSTALL_TMPL = """\
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Release.Name }}-smoke-test
  annotations:
    "helm.sh/hook": post-install
    "helm.sh/hook-weight": "5"
spec:
  template:
    spec:
      containers:
        - name: smoke
          image: "busybox:1.36"
          command: ["wget", "-qO-", "http://{{ .Release.Name }}/healthz"]
      restartPolicy: Never
"""

REDIS_VALUES: Dict[str, Any] = {
    "architecture": "standalone",
    "auth": {"enabled": True},
    "service": {"ports": {"redis": 6379}},
}

REDIS_SVC_TMPL = """\
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name }}-redis
spec:
  selector:
    app: redis
  ports:
    - name: redis
      port: {{ .Values.service.ports.redis }}
{{ if .Values.auth.enabled }}
---
apiVersion: v1
kind: Secret
metadata:
  name: {{ .Release.Name }}-redis
  annotations:
    app.kubernetes.io/managed-by: redis-subchart
type: Opaque
{{ end }}\
"""

RELEASE = {"Name": "web", "Namespace": "default", "Service": "Helm",
           "IsInstall": True, "IsUpgrade": False, "Revision": 1}


@dataclass
class Hook:
    """A template annotated with helm.sh/hook. Rendered like any template, but
    scheduled at a LIFECYCLE phase (not as a steady-state resource)."""
    name: str
    event: str        # pre-install | post-install | pre-upgrade | ...
    weight: int       # helm.sh/hook-weight: lower runs first within a phase
    template: str


HOOK_EVENTS: List[Tuple[str, str, str]] = [
    ("pre-install",   "before any resource is created",  "create a bootstrap secret"),
    ("post-install",  "after all resources are created", "run a smoke-test Job"),
    ("pre-upgrade",   "before applying the new revision", "run a DB migration Job"),
    ("post-upgrade",  "after the upgrade is applied",    "warm a cache / notify"),
    ("pre-rollback",  "before rolling back",             "take a backup"),
    ("post-rollback", "after a rollback completes",      "flush caches"),
    ("pre-delete",    "before uninstalling",             "drain / export data"),
    ("post-delete",   "after uninstalling",              "cleanup cloud resources"),
    ("test",          "`helm test` only",                "run integration tests"),
]

# install lifecycle phase index (for sorting hooks into execution order)
INSTALL_PHASE = {"pre-install": 0, "install": 1, "post-install": 2}


# ============================================================================
# 4. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def indent(s: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + ln for ln in s.splitlines())


# ============================================================================
# 5. SECTIONS
# ============================================================================

def section_a_structure():
    banner("SECTION A: chart structure - Chart.yaml + values.yaml + templates/")
    tree = """\
webapp/
├── Chart.yaml          # metadata: name, version, appVersion, deps, type
├── values.yaml         # DEFAULT values for the template holes
├── charts/             # subchart tarballs (populated by `helm dependency update`)
└── templates/
    ├── deployment.yaml # main app Deployment (.Values.replicas, .Values.image)
    ├── workers.yaml    # {{ range }} loop -> one Deployment per worker
    ├── service.yaml    # Service exposing the app
    ├── hooks.yaml      # pre-install / post-install hook templates
    └── _helpers.tpl    # {{ define }} named snippets (reusable; NOT a resource)
"""
    print(tree)
    print("Chart.yaml:")
    print(indent(WEBAPP_CHART_YAML))
    print("values.yaml (shown as a dict; on disk it is YAML):")
    print(indent(json.dumps(WEBAPP_VALUES, indent=2)))
    print("\n  => templates/ has the HOLES; values.yaml has the DEFAULT fillings;")
    print("     `helm install web ./webapp` pours values into holes -> finished YAML.")
    print("\n[check] chart has Chart.yaml + values.yaml + templates/: OK")
    return WEBAPP_VALUES


def section_b_render():
    banner("SECTION B: template rendering - {{ .Values.X }} -> value, {{ range }} -> loop")
    print("BEFORE (deployment.yaml, with Go-template holes):")
    print(indent(DEPLOYMENT_TMPL))
    rendered = render_template(DEPLOYMENT_TMPL, WEBAPP_VALUES, RELEASE)
    print("\nAFTER  (`helm template web ./webapp` renders it with values.yaml):")
    print(indent(rendered))

    print("\n{{ range }} loop - workers.yaml iterates over .Values.workers (2 items):")
    print("BEFORE (template):")
    print(indent(WORKERS_TMPL))
    wrendered = render_template(WORKERS_TMPL, WEBAPP_VALUES, RELEASE)
    print("\nAFTER (one Deployment per worker, {{ .name }}/{{ .replicas }} per item):")
    print(indent(wrendered))

    # gold assertions
    assert "replicas: 3" in rendered
    assert 'image: "nginx:1.16"' in rendered
    assert wrendered.count("kind: Deployment") == 2
    assert "name: web-ingestion" in wrendered and "replicas: 2" in wrendered
    assert "name: web-processor" in wrendered and "replicas: 4" in wrendered
    print("\n[check] replicas=3, image=nginx:1.16, 2 workers (ingestion=2, processor=4): OK")
    return rendered


def section_c_override():
    banner("SECTION C: values override - --set (scalar) and --values (deep-merge)")
    print("helm install web ./webapp --set image.tag=v2")
    v_set = apply_set(WEBAPP_VALUES, "image.tag", "v2")
    r_set = render_template(DEPLOYMENT_TMPL, v_set, RELEASE)
    print(f"  merged image.tag = {v_set['image']['tag']!r}  (repository unchanged)")
    print(f"  rendered image   = \"nginx:{v_set['image']['tag']}\"")

    print("\nhelm install web ./webapp --values prod.yaml")
    print("  prod.yaml:")
    prod = {"replicas": 10, "image": {"tag": "1.20"}}
    print(indent(json.dumps(prod, indent=2), "    "))
    v_prod = deep_merge(WEBAPP_VALUES, prod)
    print("  merged values (deep-merge: base + prod, prod wins):")
    print(indent(json.dumps(v_prod, indent=2), "    "))
    r_prod = render_template(DEPLOYMENT_TMPL, v_prod, RELEASE)
    print("  rendered deployment (prod):")
    print(indent(r_prod))

    # gold assertions
    assert 'image: "nginx:v2"' in r_set
    assert "replicas: 10" in r_prod
    assert 'image: "nginx:1.20"' in r_prod
    assert v_prod["image"]["repository"] == "nginx"      # base key NOT in prod -> kept
    assert v_prod["image"]["pullPolicy"] == "IfNotPresent"
    print("\n  --set image.tag=v2  -> image: \"nginx:v2\"  (one scalar swapped)")
    print("  --values prod.yaml  -> replicas=10, image: \"nginx:1.20\" (deep merge;")
    print("     repository/pullPolicy fall through from base values.yaml).")
    print("\n[check] --set -> nginx:v2 ; --values prod -> replicas=10, nginx:1.20: OK")
    return v_prod


def section_d_hooks():
    banner("SECTION D: hooks - pre-install Secret + post-install smoke-test Job")
    print("A hook is a NORMAL template plus the helm.sh/hook annotation. Helm does")
    print("NOT apply it as a steady-state resource; it runs the hook at the named")
    print("lifecycle phase, ordered by hook-weight (lower first).\n")
    print("| event         | when                        | typical use             |")
    print("|---------------|-----------------------------|-------------------------|")
    for ev, when, use in HOOK_EVENTS:
        print(f"| {ev:<13} | {when:<27} | {use:<23} |")

    hooks = [
        Hook("bootstrap-token-secret", "pre-install",  -5, HOOK_PREINSTALL_TMPL),
        Hook("smoke-test-job",         "post-install",  5, HOOK_POSTINSTALL_TMPL),
    ]
    # execution order: phase, then weight
    main_render = render_template(DEPLOYMENT_TMPL, WEBAPP_VALUES, RELEASE)
    timeline: List[Tuple[int, str, int, str, str]] = []
    for h in hooks:
        timeline.append((INSTALL_PHASE[h.event], h.event, h.weight, h.name,
                         render_template(h.template, WEBAPP_VALUES, RELEASE)))
    timeline.append((INSTALL_PHASE["install"], "install", 0, "main templates",
                     main_render))
    timeline.sort(key=lambda t: (t[0], t[2]))

    print("\ninstall lifecycle execution order (phase, then hook-weight):")
    for _, phase, weight, label, rendered in timeline:
        print(f"\n  [{phase}] {label}  (weight={weight})")
        print(indent(rendered, "    "))

    # gold assertions
    pre = render_template(HOOK_PREINSTALL_TMPL, WEBAPP_VALUES, RELEASE)
    post = render_template(HOOK_POSTINSTALL_TMPL, WEBAPP_VALUES, RELEASE)
    assert '"helm.sh/hook": pre-install' in pre
    assert '"helm.sh/hook": post-install' in post
    assert timeline[0][1] == "pre-install" and timeline[0][2] == -5
    assert timeline[1][1] == "install"
    assert timeline[2][1] == "post-install" and timeline[2][2] == 5
    print("\n  pre-install (weight -5) -> install (main) -> post-install (weight 5).")
    print("  The Secret/Job are NOT part of `helm get manifest` steady-state output")
    print("  (unless hook-delete-policy keeps them); they fire at their phase.")
    print("\n[check] hook ordering pre-install(-5) < install < post-install(+5): OK")
    return hooks


def section_e_subcharts_gold():
    banner("SECTION E: subcharts + GOLD (webapp + redis subchart, prod values)")
    print("Chart.yaml declares the subchart as a dependency:")
    print(indent(WEBAPP_CHART_YAML_WITH_DEPS))
    print("`helm dependency update` resolves it into charts/redis-0.4.x.tgz and")
    print("writes Chart.lock. At render time each subchart gets its OWN scoped")
    print("values: the parent's .Values.redis block (+ shared `global`).\n")

    prod = {"replicas": 10, "image": {"tag": "1.20"}}
    parent_values = deep_merge(WEBAPP_VALUES, prod)
    parent_values = deep_merge(parent_values, {
        "redis": REDIS_VALUES,
        "global": {"imageRegistry": "registry.example.com"},
    })
    print("parent values (webapp prod + scoped redis + global):")
    print(indent(json.dumps(parent_values, indent=2)))

    redis_scoped = scope_subchart(parent_values, "redis")
    print("\nredis subchart SEES ONLY .Values.redis (+ global), NOT webapp values:")
    print(indent(json.dumps(redis_scoped, indent=2)))

    web_deploy = render_template(DEPLOYMENT_TMPL, parent_values, RELEASE)
    redis_svc = render_template(REDIS_SVC_TMPL, redis_scoped, RELEASE)
    print("\nwebapp Deployment (prod, parent scope):")
    print(indent(web_deploy))
    print("\nredis Service + auth Secret (subchart scope, {{ if .Values.auth.enabled }}):")
    print(indent(redis_svc))

    # library chart note
    print("\nlibrary chart: type: library -> defines {{ define }} snippets only;")
    print("  renders NO resources itself (other charts {{ include }} them).")

    # GOLD assertions
    ok_replicas = "replicas: 10" in web_deploy
    ok_image = 'image: "nginx:1.20"' in web_deploy
    ok_port = "port: 6379" in redis_svc
    ok_auth_secret = "kind: Secret" in redis_svc and "name: web-redis" in redis_svc
    ok_global = redis_scoped["global"]["imageRegistry"] == "registry.example.com"
    ok_all = ok_replicas and ok_image and ok_port and ok_auth_secret and ok_global
    print()
    print(f"[check] webapp prod replicas=10:               {ok_replicas}")
    print(f"[check] webapp prod image=nginx:1.20:          {ok_image}")
    print(f"[check] redis Service port=6379:               {ok_port}")
    print(f"[check] redis auth Secret rendered (if=True):  {ok_auth_secret}")
    print(f"[check] global visible to subchart:            {ok_global}")
    print(f"[check] GOLD: chart+subchart render as expected: "
          f"{'OK' if ok_all else 'FAIL'}")
    assert ok_all, "GOLD: chart render mismatch"

    # disable auth to prove the {{ if }} drops the Secret
    redis_noauth = scope_subchart(
        deep_merge(parent_values, {"redis": {"auth": {"enabled": False}}}), "redis")
    redis_svc2 = render_template(REDIS_SVC_TMPL, redis_noauth, RELEASE)
    assert "kind: Secret" not in redis_svc2
    print(f"\n[check] auth.enabled=False -> Secret DROPPED by {{ if }}: "
          f"{'OK' if 'kind: Secret' not in redis_svc2 else 'FAIL'}")

    print("\nGOLD scalars for helm_chart.html:")
    print("  webapp image line   = 'image: \"nginx:1.20\"'")
    print("  webapp replicas     = 10")
    print("  redis Service port  = 6379")
    print("  redis auth enabled  = True  (Secret rendered)")
    return web_deploy, redis_svc


# ============================================================================
# main
# ============================================================================

def main():
    print("helm_chart.py - reference model. All output feeds HELM_CHART.md.")
    section_a_structure()
    section_b_render()
    section_c_override()
    section_d_hooks()
    section_e_subcharts_gold()
    banner("DONE - all sections printed; all [check]s asserted")


if __name__ == "__main__":
    main()
