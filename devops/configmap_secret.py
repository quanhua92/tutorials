"""
configmap_secret.py - Reference model of Kubernetes configuration injection:
ConfigMap (non-sensitive) and Secret (sensitive, base64-encoded), mounted as
environment variables vs volumes, and how each reacts to a live config change.

This is the single source of truth that CONFIGMAP_SECRET.md is built from. Every
base64 value, runtime snapshot, and reload timeline in the guide is printed by
this file. If you change something here, re-run and re-paste the output.

Run:
    python configmap_secret.py

============================================================================
THE INTUITION (read this first) - the two desks and the two delivery methods
============================================================================
An app needs CONFIGURATION (a DB host, an API key, a TLS cert). In Kubernetes
that config lives OUTSIDE the image, in one of two objects:

  * ConfigMap : for NON-SENSITIVE data (DB_HOST=10.0.0.5, LOG_LEVEL=info).
                 Stored in plain text in etcd.
  * Secret    : for SENSITIVE data (passwords, tokens, TLS keys). Stored
                 BASE64-ENCODED in etcd (encoding, NOT encryption - enable
                 encryption-at-rest separately). Types: Opaque (generic),
                 kubernetes.io/dockerconfigjson (registry creds),
                 kubernetes.io/tls (cert+key).

The kubelet can deliver either object to a container by ONE of two methods:

  * ENV VAR   : `envFrom` / `env.valueFrom` injects each key as a process
                environment variable. SNAPSHOT at container start - it is
                IMMUTABLE for the life of the process. A config change needs a
                pod restart to be seen here.
  * VOLUME    : mount the object as files under a path (e.g. /etc/config). The
                kubelet PERIODICALLY REFRESHES the mounted files (default ~60s),
                so a config change shows up WITHOUT a restart (hot reload).

THE GOLD QUESTION this bundle answers: after injecting a ConfigMap + Secret, do
the container's runtime ENV and FILES hold exactly the expected values? And
after a live update, is the ENV stale while the FILES are fresh? Those answers
are deterministic and recomputed by configmap_secret.html.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  ConfigMap       non-sensitive config object (key/value or key/file).
  Secret          sensitive config object; values are base64-ENCODED in etcd.
  Opaque          the generic Secret type (arbitrary key/value).
  docker-registry a Secret of type kubernetes.io/dockerconfigjson - used by the
                  image puller to authenticate to a private registry.
  TLS             a Secret of type kubernetes.io/tls - holds tls.crt + tls.key.
  env var         config injected as a process env var - IMMUTABLE after start.
  volume mount    config injected as files under a path - REFRESHED periodically.
  tmpfs           an in-RAM filesystem. Secrets mounted as volumes land on a
                  tmpfs, so they are NEVER written to the node's disk.
  hot reload      a config change reaching a running container (volumes only).
  12-factor app   "store config in the environment" - config lives outside code.
  ExternalSecret  a CRD (external-secrets-operator) that syncs a secret from an
                  external store (Vault, AWS Secrets Manager) INTO a K8s Secret.
  CSI driver      secrets-store.csi.k8s.io - mounts secrets from Vault/AWS/...
                  directly as a volume WITHOUT creating a K8s Secret object.

Reference docs: kubernetes.io "ConfigMaps", "Secrets", "Configure a Pod to Use
a ConfigMap/Secret", external-secrets.io.
============================================================================
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

BANNER = "=" * 72


# ============================================================================
# 1. THE MODEL  (ConfigMap / Secret / Pod + injection resolvers)
# ============================================================================

@dataclass
class ConfigMap:
    """A non-sensitive config object. `data` holds plain key->string values."""
    name: str
    data: Dict[str, str] = field(default_factory=dict)

    def create_from_literal(self, key: str, value: str) -> "ConfigMap":
        self.data[key] = value
        return self

    def create_from_file(self, filename: str, content: str) -> "ConfigMap":
        # `kubectl create configmap x --from-file=app.yaml` keys on the filename
        self.data[filename] = content
        return self


@dataclass
class Secret:
    """A sensitive config object. `data` holds PLAINTEXT values; they are
    base64-encoded only when serialized to etcd (`.encoded()`)."""
    name: str
    type: str = "Opaque"                       # Opaque | docker-registry | TLS
    data: Dict[str, str] = field(default_factory=dict)

    def create_from_literal(self, key: str, value: str) -> "Secret":
        self.data[key] = value
        return self

    def encoded(self) -> Dict[str, str]:
        """How the Secret is actually stored in etcd / shown by `kubectl get
        secret -o yaml`: each value base64-encoded."""
        return {k: base64.b64encode(v.encode()).decode() for k, v in self.data.items()}


@dataclass
class Pod:
    name: str
    env_refs: List[Tuple[str, str, str, str]] = field(default_factory=list)
    # (env_name, source_kind "cm"|"secret", source_name, key)
    vol_mounts: List[Tuple[str, str, str, str, Dict[str, str] | None]] = field(default_factory=list)
    # (vol_name, source_kind, source_name, mount_path, items_map_or_None)
    start_version: Dict[str, int] = field(default_factory=dict)
    # source_name -> configmap "version" snapshot at container start (for env)

    def add_env(self, env_name, kind, source, key):
        self.env_refs.append((env_name, kind, source, key))
        return self

    def add_volume(self, vol_name, kind, source, mount_path, items=None):
        self.vol_mounts.append((vol_name, kind, source, mount_path, items))
        return self


def resolve_env(pod: Pod, configmaps: Dict[str, ConfigMap],
                secrets: Dict[str, Secret]) -> Dict[str, str]:
    """Snapshot of process env vars at CONTAINER START. Secrets injected as env
    are DECODED to plaintext (base64 is only the on-disk/etcd representation)."""
    env: Dict[str, str] = {}
    for env_name, kind, source, key in pod.env_refs:
        if kind == "cm":
            env[env_name] = configmaps[source].data[key]
        elif kind == "secret":
            env[env_name] = secrets[source].data[key]   # decoded plaintext
    return env


def resolve_volume(mount, configmaps, secrets) -> Dict[str, str]:
    """Files the container sees at the mount path. Returns path -> content.
    Secret files contain DECODED plaintext (not base64)."""
    vol_name, kind, source, mount_path, items = mount
    files: Dict[str, str] = {}
    if kind == "cm":
        data = configmaps[source].data
    else:
        data = secrets[source].data                 # decoded plaintext
    keys = items if items is not None else {k: k for k in data}
    for key, rel in keys.items():
        path = rel if rel.startswith("/") else f"{mount_path}/{rel}"
        files[path] = data[key]
    return files


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def show_kv(title: str, d: Dict[str, str]):
    print(f"  {title}:")
    if not d:
        print("    (empty)")
    for k, v in d.items():
        shown = v if len(v) <= 60 else v[:57] + "..."
        print(f"    {k} = {shown!r}")


# ============================================================================
# 3. SECTIONS
# ============================================================================

def section_a_configmap():
    banner("SECTION A: ConfigMap - create from literal/file, mount two ways")
    cm = (ConfigMap("app-config")
          .create_from_literal("DB_HOST", "10.0.0.5")
          .create_from_literal("LOG_LEVEL", "info")
          .create_from_file("app.yaml",
                            "listen: 8080\ndb: postgres\n"))
    print("kubectl create configmap app-config \\")
    print("  --from-literal=DB_HOST=10.0.0.5 \\")
    print("  --from-literal=LOG_LEVEL=info \\")
    print("  --from-file=app.yaml\n")
    show_kv("ConfigMap app-config data", cm.data)

    configmaps = {"app-config": cm}
    pod = (Pod("web")
           .add_env("DB_HOST", "cm", "app-config", "DB_HOST")     # env var
           .add_env("LOG_LEVEL", "cm", "app-config", "LOG_LEVEL")
           .add_volume("cfg", "cm", "app-config", "/etc/config"))  # volume

    env = resolve_env(pod, configmaps, {})
    files = {}
    for m in pod.vol_mounts:
        files.update(resolve_volume(m, configmaps, {}))
    print("\nMETHOD 1 - env var (valueFrom.configMapKeyRef):")
    show_kv("process env", env)
    print("\nMETHOD 2 - volume mount (each key becomes a FILE):")
    show_kv("mounted files", files)
    print("\n  => DB_HOST reaches the app as an ENV VAR; app.yaml reaches it as")
    print("     a FILE at /etc/config/app.yaml. Same ConfigMap, two delivery paths.")
    # gold assertions
    assert env["DB_HOST"] == "10.0.0.5"
    assert files["/etc/config/app.yaml"].startswith("listen: 8080")
    print("\n[check] env DB_HOST == '10.0.0.5' AND /etc/config/app.yaml present: OK")
    return cm, configmaps, env, files


def section_b_secret():
    banner("SECTION B: Secret - base64 in etcd, decoded in the container, tmpfs")
    sec = (Secret("db-creds", type="Opaque")
           .create_from_literal("username", "admin")
           .create_from_literal("password", "s3cr3t!"))
    print(f"Secret type: {sec.type}")
    print("\n  Stored in etcd / `kubectl get secret db-creds -o yaml` (base64):")
    for k, v in sec.encoded().items():
        print(f"    {k}: {v}")
    print("\n  Decode check (base64.b64decode):")
    for k, v in sec.encoded().items():
        print(f"    {k}: {base64.b64decode(v).decode()!r}   <- plaintext seen by app")

    print("\nSecret TYPES:")
    print("| type                              | holds                       | used for            |")
    print("|-----------------------------------|-----------------------------|---------------------|")
    print("| Opaque                            | arbitrary key/value         | generic secrets     |")
    print("| kubernetes.io/dockerconfigjson    | .dockerconfigjson (b64)     | private registry    |")
    print("| kubernetes.io/tls                  | tls.crt + tls.key (b64)     | Ingress TLS         |")

    secrets = {"db-creds": sec}
    pod = (Pod("web")
           .add_env("DB_PASSWORD", "secret", "db-creds", "password")
           .add_volume("secret-vol", "secret", "db-creds", "/etc/secret"))
    env = resolve_env(pod, {}, secrets)
    files = resolve_volume(pod.vol_mounts[0], {}, secrets)
    print("\nDelivered to the container (DECODED - never base64 inside the pod):")
    show_kv("env var DB_PASSWORD", env)
    show_kv("mounted secret files", files)
    print("\n  => Secret volumes are mounted on a TMPFS (in RAM): the plaintext is")
    print("     NEVER written to the node disk. base64 is transport/storage only.")
    # gold: env secret is decoded plaintext, not base64
    assert env["DB_PASSWORD"] == "s3cr3t!"
    assert "s3cr3t!" not in sec.encoded()["password"]   # stored form is b64
    b64_password = sec.encoded()["password"]
    print(f"\n[check] env DB_PASSWORD == 's3cr3t!' (decoded), stored b64 = "
          f"'{b64_password}': OK")
    return sec, b64_password


def section_c_hot_reload():
    banner("SECTION C: hot reload - env is IMMUTABLE, volume REFRESHES (~60s)")
    print("A ConfigMap is updated at t=30. Compare how env vs volume react:\n")
    print("  ENV VAR : snapshot at container START. The process keeps the OLD")
    print("            value until the pod is RESTARTED. (config change => restart)")
    print("  VOLUME  : the kubelet periodically RE-SYNCS mounted files (default")
    print("            ~60s). A change lands WITHOUT a restart (hot reload).\n")

    initial = {"FEATURE_FLAG": "off", "THROTTLE": "100"}
    updated = {"FEATURE_FLAG": "on", "THROTTLE": "100"}
    refresh_period = 60
    update_t = 30

    # The volume reflects the NEW data only once a refresh tick passes update_t.
    # next refresh tick >= update_t:
    cross = ((update_t + refresh_period - 1) // refresh_period) * refresh_period
    print(f"  ConfigMap v1 (start): {initial}")
    print(f"  ConfigMap v2 (t={update_t}): {updated}")
    print(f"  volume refresh period: {refresh_period}s  => volume sees v2 at t={cross}\n")
    print(f"  {'t(s)':>5}  {'env (pinned)':<22} {'volume (live)':<22} event")
    print(f"  {'----':>5}  {'-'*22} {'-'*22} -----")
    timeline = []
    for t in [0, 10, 20, 29, 30, 40, 50, 59, 60, 70, 90]:
        env_ff = initial["FEATURE_FLAG"]
        vol_ff = updated["FEATURE_FLAG"] if t >= cross else initial["FEATURE_FLAG"]
        event = ""
        if t == update_t:
            event = "ConfigMap updated -> v2"
        if t == cross:
            event = "volume refreshed -> v2"
        timeline.append((t, env_ff, vol_ff, event))
        print(f"  {t:>5}  env.FEATURE_FLAG={env_ff:<6} "
              f"file.FEATURE_FLAG={vol_ff:<6} {event}")
    print()
    print("READING THE TIMELINE:")
    print("  - env.FEATURE_FLAG is 'off' FOREVER (snapshot at t=0). Needs a restart")
    print("    to become 'on'.")
    print(f"  - file.FEATURE_FLAG flips 'off'->'on' at t={cross} (next kubelet sync")
    print(f"    after the t={update_t} update). No restart needed.\n")
    # gold checks
    assert all(r[1] == "off" for r in timeline), "env must stay pinned"
    assert timeline[-1][2] == "on", "volume must refresh to v2"
    assert cross == 60, "cross tick must be 60 for period 60, update 30"
    print(f"[check] env pinned 'off' for all t, volume flips at t={cross}: OK")
    print(f"GOLD for the .html: env stays 'off'; volume flips to 'on' at t={cross}.")
    return initial, updated, refresh_period, update_t, cross


def section_d_external_secrets():
    banner("SECTION D: external secrets - Vault (CSI) vs AWS SM (external-secrets)")
    print("Two ways to feed a secret from an EXTERNAL store (Vault, AWS Secrets")
    print("Manager, GCP SM) WITHOUT pre-storing it as a K8s Secret by hand:\n")

    print("PATH 1 - Secrets Store CSI Driver (secrets-store.csi.k8s.io):")
    print("  Vault/AWS/... --[CSI provider]--> mounted as FILES in the pod.")
    print("  No K8s Secret object is created. Good for short-lived, rotated creds.\n")
    # model: a CSI mount materializes files from the external store
    vault_data = {"db-password": "vault-rotated-token-xyz"}
    csi_files = {"/mnt/secrets-store/db-password": vault_data["db-password"]}
    show_kv("CSI volume (from Vault)", csi_files)

    print("\nPATH 2 - External Secrets Operator (external-secrets.io):")
    print("  AWS SM --[ExternalSecret CRD]--> creates/refreshes a K8s Secret -->")
    print("  consumed normally (env or volume). A K8s Secret object IS created.\n")
    aws_sm_value = "prod-api-key-abc123"
    # the operator syncs AWS SM -> a K8s Secret
    synced_secret = Secret("api-key-synced").create_from_literal(
        "API_KEY", aws_sm_value)
    print(f"  ExternalSecret reads AWS SM key 'prod/api-key' = {aws_sm_value!r}")
    print(f"  -> writes K8s Secret {synced_secret.name} (encoded): "
          f"{synced_secret.encoded()['API_KEY']}")
    print("  -> pod consumes it as a normal Secret (env/volume), DECODED in pod.")
    show_kv("synced K8s Secret decoded", synced_secret.data)

    print("\n  CSI Driver     : secret NEVER becomes a K8s Secret (mount-only).")
    print("  ExternalSecret : a K8s Secret IS materialized (then env/volume).")
    print("  Both support ROTATION: CSI re-reads on remount; ExternalSecret")
    print("  re-syncs on a `refreshInterval` and updates the K8s Secret (volumes")
    print("  see the new value; env still needs a restart).")
    assert synced_secret.data["API_KEY"] == aws_sm_value
    assert csi_files["/mnt/secrets-store/db-password"] == vault_data["db-password"]
    print("\n[check] CSI mount + ExternalSecret sync produce correct values: OK")
    return csi_files, synced_secret


def section_e_twelve_factor_gold():
    banner("SECTION E: 12-factor + GOLD (config injection => correct runtime)")
    print("12-factor principle III: 'Store config in the environment.' Config that")
    print("varies between deploys (DB host, log level, feature flags) must NOT live")
    print("in the image/code - it lives in ConfigMaps/Secrets and is injected.\n")

    print("ANTI-PATTERN (config baked into code):")
    print("   DB_HOST = '10.0.0.5'   # <- hardcoded; same for prod/staging. BAD.\n")
    print("12-FACTOR (config injected at runtime):")
    print("   DB_HOST = os.environ['DB_HOST']   # <- from a ConfigMap via env var.\n")

    # ---- GOLD: full injection pipeline produces exact runtime values ----
    cm = (ConfigMap("app-config")
          .create_from_literal("DB_HOST", "10.0.0.5")
          .create_from_literal("LOG_LEVEL", "info"))
    sec = (Secret("db-creds")
           .create_from_literal("password", "s3cr3t!"))
    configmaps = {"app-config": cm}
    secrets = {"db-creds": sec}
    pod = (Pod("web")
           .add_env("DB_HOST", "cm", "app-config", "DB_HOST")
           .add_env("LOG_LEVEL", "cm", "app-config", "LOG_LEVEL")
           .add_env("DB_PASSWORD", "secret", "db-creds", "password")
           .add_volume("cfg", "cm", "app-config", "/etc/config")
           .add_volume("sec", "secret", "db-creds", "/etc/secret"))
    env = resolve_env(pod, configmaps, secrets)
    files = {}
    for m in pod.vol_mounts:
        files.update(resolve_volume(m, configmaps, secrets))

    expected_env = {"DB_HOST": "10.0.0.5", "LOG_LEVEL": "info",
                    "DB_PASSWORD": "s3cr3t!"}
    expected_files = {
        "/etc/config/DB_HOST": "10.0.0.5",
        "/etc/config/LOG_LEVEL": "info",
        "/etc/secret/password": "s3cr3t!",
    }
    show_kv("runtime env", env)
    show_kv("runtime files", files)

    ok_env = env == expected_env
    ok_files = files == expected_files
    ok_secret_decoded = env["DB_PASSWORD"] == "s3cr3t!"  # not base64
    ok_all = ok_env and ok_files and ok_secret_decoded
    print()
    print(f"[check] env == expected:        {ok_env}")
    print(f"[check] files == expected:      {ok_files}")
    print(f"[check] secret DECODED in env:  {ok_secret_decoded}")
    print(f"[check] GOLD: config injection => correct runtime values: "
          f"{'OK' if ok_all else 'FAIL'}")
    assert ok_all, "GOLD: runtime config injection mismatch"
    print("\nGOLD scalar for the .html: env['DB_HOST']='10.0.0.5', "
          "env['DB_PASSWORD']='s3cr3t!' (decoded), file "
          "'/etc/secret/password'='s3cr3t!'.")
    return env, files


# ============================================================================
# main
# ============================================================================

def main():
    print("configmap_secret.py - reference model. All output feeds "
          "CONFIGMAP_SECRET.md.")
    section_a_configmap()
    section_b_secret()
    section_c_hot_reload()
    section_d_external_secrets()
    section_e_twelve_factor_gold()
    banner("DONE - all sections printed; all [check]s asserted")


if __name__ == "__main__":
    main()
