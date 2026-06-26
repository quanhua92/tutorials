"""
vault_secrets.py - Reference model of HashiCorp Vault secret management: KV
(static) secrets, dynamic (database) secrets with TTL, the transit encryption
engine, vault-agent-injector sidecar injection, and the lease lifecycle.

This is the single source of truth that VAULT_SECRETS.md is built from. Every
ciphertext, issued credential, injected file, and lease-TTL value in the guide
is printed by this file. If you change something here, re-run and re-paste the
output.

Run:
    python vault_secrets.py

============================================================================
THE INTUITION (read this first) - the bank vault vs the safe under the desk
============================================================================
An app needs SECRETS (a DB password, an API key). The naive move is to dump
them in an env var or bake them into the image - a "safe under the desk". If
the laptop/server is compromised, every secret it ever held is gone, forever,
and you have no idea who read what.

Vault is a BANK VAULT for secrets:

  * STATIC secrets (KV)  : you PUT a secret once (vault kv put secret/db ...),
                           Vault stores it ENCRYPTED. Many apps read the same
                           value. Rotating it = you change it in one place.
  * DYNAMIC secrets      : you ask Vault for a DB credential; it CREATES a
                           fresh DB user on demand with a 1h TTL. When the TTL
                           expires, Vault REVOKES (drops) the user itself. No
                           shared long-lived password to leak.
  * TRANSIT (enc-as-svc) : you ask Vault "encrypt this blob" / "decrypt this
                           blob". Vault holds the KEY; your app only ever sees
                           ciphertext. The data is NEVER stored in Vault.
  * INJECTION           : the vault-agent-injector mutates your Pod to add a
                           sidecar that renders secrets to a shared volume as
                           FILES. Your app reads a file - it needs NO Vault SDK.

THE GOLD QUESTION this bundle answers: after injection, does the app's file
hold exactly the right value, AND does the dynamic lease have the right TTL?
Both are deterministic, and vault_secrets.html recomputes them in JS.

============================================================================
PLAIN-ENGLISH GLOSSARY
============================================================================
  KV store        key-value secret engine (KV v2: versioned). Static - you write
                  the value; readers get that same value until you change it.
  dynamic secret  a credential Vault GENERATES on read (DB user, AWS IAM, SSH
                  cert). Has a lease + TTL; auto-revoked on expiry.
  transit engine  encryption-as-a-service: Vault holds the key; you call
                  encrypt/decrypt. Data is NEVER stored (stateless crypto API).
  lease           the handle Vault gives you for a dynamic secret (or a token).
                  Has lease_id, lease_duration (TTL), renewable.
  TTL             time-to-live. When it elapses, the secret is revoked.
  renewal         extend the lease (up to max_ttl). Like renewing a library book.
  revocation      destroy the secret NOW (e.g. drop the DB user) before TTL.
  secret engine   a Vault "plugin" mounted at a path: kv/, database/, transit/.
  vault-agent     the sidecar that fetches secrets + renders templates to files.
  injector        vault-agent-injector: a mutating admission webhook that adds
                  the vault-agent sidecar + emptyDir based on Pod annotations.
  CSI driver      secrets-store CSI driver: another injection path - mounts
                  secrets as a volume without a sidecar or a K8s Secret.
  auth method     how a caller proves identity to Vault: kubernetes, approle,
                  aws, jwt. Returns a token; the token then reads secrets.
  policy          a grant of what paths a token may read/write.
  envelope seal   Vault's master key is split into key shares (Shamir); a quorum
                  of shares must unseal it before it can serve requests.

Reference docs: developer.hashicorp.com/vault - "KV Secrets", "Database Secrets",
"Transit Secrets Engine", "Vault Agent Injector", "Leases, Renewals and Revocation".
============================================================================

NOTE ON THE MODEL: real Vault encrypts at rest with AES-256-GCM and the transit
engine uses AES-256-GCM with a random nonce (non-deterministic). This file uses
a DETERMINISTIC reversible transform (XOR over a derived key) so ciphertexts are
reproducible and checkable - clearly labelled "SIMULATED". The API SHAPE and the
injection/TTL pipeline are what matter pedagogically, not the cipher strength.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

BANNER = "=" * 72

# SIMULATED master key (real Vault: AES-256-GCM, split via Shamir's secret sharing)
_MASTER = hashlib.sha256(b"vault-tutorial").digest()


def _derive_key(name: str) -> bytes:
    """Derive a deterministic 32-byte key for a transit key NAME (SIMULATED).
    Real Vault stores a random AES-256 key per transit key, versioned."""
    return hashlib.sha256(_MASTER + name.encode()).digest()


def _xor(data: bytes, key: bytes) -> bytes:
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


# ============================================================================
# 1. THE VAULT  (KV v2, database engine, transit engine, leases + clock)
# ============================================================================

@dataclass
class Lease:
    """The handle Vault returns for a dynamic secret or token.
    expiry / max_expiry are ABSOLUTE timestamps in the Vault clock; `ttl` is the
    granted duration AT ISSUE (the lease_duration field). On renew, expiry is
    moved forward (bounded by max_expiry) - it is NOT recomputed as
    creation_time + ttl, because the renewal counts from NOW."""
    id: str
    type: str                     # "database" | "token"
    data: Dict[str, str]          # the secret payload (e.g. username/password)
    creation_time: int
    ttl: int                      # granted duration at issue (s) -> lease_duration
    max_ttl: int                  # hard cap (s)
    expiry: int = 0               # absolute; 0 -> set in __post_init__
    max_expiry: int = 0           # absolute; 0 -> set in __post_init__
    renewable: bool = True
    revoked: bool = False
    destroy_sql: str = ""         # run on revoke/expire (DROP USER ...)

    def __post_init__(self):
        if self.expiry == 0:
            self.expiry = self.creation_time + self.ttl
        if self.max_expiry == 0:
            self.max_expiry = self.creation_time + self.max_ttl

    def remaining(self, now: int) -> int:
        return max(0, self.expiry - now)


@dataclass
class Vault:
    kv_mounts: Dict[str, Dict[str, object]] = field(default_factory=dict)
    # mount -> {current_version, versions: {v: data}}
    db_config: Dict[str, dict] = field(default_factory=dict)
    db_roles: Dict[str, dict] = field(default_factory=dict)
    transit_keys: Dict[str, bytes] = field(default_factory=dict)
    leases: Dict[str, Lease] = field(default_factory=dict)
    clock: int = 0
    _seq: int = 0

    # ---- clock ----
    def tick(self, dt: int) -> List[str]:
        """Advance the clock by dt seconds; auto-revoke any expired lease.
        Returns the list of lease_ids auto-revoked this tick."""
        self.clock += dt
        expired: List[str] = []
        for lid, lease in list(self.leases.items()):
            if not lease.revoked and self.clock >= lease.expiry:
                self._revoke(lid, reason="expired")
                expired.append(lid)
        return expired

    # ---- KV v2 ----
    def kv_put(self, path: str, **data) -> int:
        """vault kv put secret/db password=x  ->  creates a new version.
        KV v2 stores at <mount>/data/<rest> and metadata at <mount>/metadata/<rest>."""
        mount = path.split("/")[0]
        store = self.kv_mounts.setdefault(mount, {"current_version": 0, "versions": {}})
        v = int(store["current_version"]) + 1                  # type: ignore[operator]
        store["versions"][v] = dict(data)                       # type: ignore[index]
        store["current_version"] = v                            # type: ignore[assignment]
        return v

    def kv_get(self, path: str) -> Tuple[int, Dict[str, str]]:
        """vault kv get secret/db  ->  (version, data). Plaintext returned to
        the caller; etcd/storage holds it SIMULATED-encrypted at rest."""
        mount = path.split("/")[0]
        store = self.kv_mounts[mount]
        v = int(store["current_version"])                       # type: ignore[arg-type]
        return v, dict(store["versions"][v])                    # type: ignore[index]

    def kv_at_rest(self, path: str) -> Dict[str, str]:
        """SIMULATED etcd/storage representation: each value XOR-encrypted with
        the master key, base64-encoded. (Real Vault: AES-256-GCM at rest.)"""
        v, data = self.kv_get(path)
        return {k: base64.b64encode(_xor(val.encode(), _MASTER)).decode()
                for k, val in data.items()}

    # ---- database (dynamic) engine ----
    def db_configure(self, name: str, connection_url: str, plugin: str):
        self.db_config[name] = {"connection_url": connection_url, "plugin": plugin}

    def db_role(self, name: str, db_name: str, default_ttl: int, max_ttl: int,
                creation: str, destruction: str):
        self.db_roles[name] = {"db_name": db_name, "default_ttl": default_ttl,
                               "max_ttl": max_ttl, "creation": creation,
                               "destruction": destruction}

    def db_creds(self, role_name: str) -> Lease:
        """vault read database/creds/<role>  ->  ISSUES a fresh DB user.
        The creation_statements actually CREATE the user in the DB; the lease
        records the destruction_statements to run on revoke/expire."""
        role = self.db_roles[role_name]
        self._seq += 1
        nonce = f"{self._seq:04x}"
        username = f"v-{role_name}-{nonce}"
        password = hashlib.sha256(_MASTER + nonce.encode()).hexdigest()[:20]
        lease_id = f"database/creds/{role_name}/{nonce}"
        lease = Lease(
            id=lease_id, type="database",
            data={"username": username, "password": password},
            creation_time=self.clock, ttl=role["default_ttl"],
            max_ttl=role["max_ttl"], destroy_sql=role["destruction"],
        )
        self.leases[lease_id] = lease
        # (in reality) the DB plugin runs role["creation"] -> CREATE USER now
        return lease

    # ---- transit engine (encryption as a service) ----
    def transit_create_key(self, name: str):
        self.transit_keys[name] = _derive_key(name)            # SIMULATED

    def transit_encrypt(self, name: str, plaintext: str) -> str:
        """vault write transit/encrypt/<key> plaintext=<b64>  ->  ciphertext.
        Returns 'vault:v1:<b64>'. Data is NEVER stored; Vault only holds the key.
        (SIMULATED: XOR over derived key, fixed nonce. Real: AES-256-GCM, random
        nonce -> encrypt is non-deterministic.)"""
        key = self.transit_keys.get(name) or _derive_key(name)
        ct = _xor(plaintext.encode(), key)
        return "vault:v1:" + base64.b64encode(ct).decode()

    def transit_decrypt(self, name: str, ciphertext: str) -> str:
        assert ciphertext.startswith("vault:v1:"), "bad ciphertext prefix"
        key = self.transit_keys.get(name) or _derive_key(name)
        ct = base64.b64decode(ciphertext[len("vault:v1:"):])
        return _xor(ct, key).decode()

    # ---- lease management ----
    def lease_renew(self, lease_id: str, increment: Optional[int] = None) -> Lease:
        """vault lease renew <id> [-increment=N]  ->  extends the lease.
        New expiry = min(clock + increment, max_expiry); bounded by max_expiry."""
        lease = self.leases[lease_id]
        assert not lease.revoked, "cannot renew a revoked lease"
        inc = increment if increment is not None else lease.ttl
        lease.expiry = min(self.clock + inc, lease.max_expiry)
        return lease

    def lease_revoke(self, lease_id: str):
        """vault lease revoke <id>  ->  DESTROY NOW (run destruction statements)."""
        self._revoke(lease_id, reason="revoked")

    def _revoke(self, lease_id: str, reason: str):
        lease = self.leases[lease_id]
        if lease.revoked:
            return
        lease.revoked = True
        lease.revoked_reason = reason          # type: ignore[attr-defined]
        # (in reality) the DB plugin runs lease.destroy_sql -> DROP USER now


# ============================================================================
# 2. VAULT-AGENT INJECTION  (mutating webhook + sidecar + shared volume)
# ============================================================================

_VAULT_TPL_RE = __import__("re").compile(r"\{\{\s*\.Data\.data\.([A-Za-z0-9_]+)\s*\}\}")


def render_vault_template(tmpl: str, data: Dict[str, str]) -> str:
    """Render the subset of consul-template the injector uses:
    {{ .Data.data.KEY }} -> the KV value. (Real consul-template also supports
    {{ with secret "..." }}...{{ end }} and more functions.)"""
    return _VAULT_TPL_RE.sub(lambda m: data[m.group(1)], tmpl)


@dataclass
class Pod:
    """A Pod annotated for vault-agent-injector. The mutating webhook reads the
    annotations and the vault-agent sidecar renders templates to `shared_volume`
    (an emptyDir mounted at /vault/secrets). The app container reads FILES."""
    name: str
    annotations: Dict[str, str] = field(default_factory=dict)
    shared_volume: Dict[str, str] = field(default_factory=dict)   # path -> content


def inject(pod: Pod, vault: Vault) -> Pod:
    """Mutating webhook + sidecar: for each vault.hashicorp.com/agent-inject-*
    annotation, fetch the secret and render the template to a file under
    /vault/secrets/. The app reads the file - it needs NO Vault SDK."""
    for key, val in pod.annotations.items():
        prefix = "vault.hashicorp.com/agent-inject-secret-"
        if not key.startswith(prefix):
            continue
        file_name = key[len(prefix):]                          # e.g. db-password
        secret_path = val                                       # e.g. secret/db
        tmpl_key = "vault.hashicorp.com/agent-inject-template-" + file_name
        tmpl = pod.annotations.get(
            tmpl_key, '{{ .Data.data.password }}')             # default: just the value
        _, data = vault.kv_get(secret_path)
        content = render_vault_template(tmpl, data)
        pod.shared_volume[f"/vault/secrets/{file_name}"] = content
    return pod


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def indent(s: str, prefix: str = "  ") -> str:
    return "\n".join(prefix + ln for ln in s.splitlines())


def show_kv(title: str, d: Dict[str, str], width: int = 26):
    print(f"  {title}:")
    for k, v in d.items():
        print(f"    {k:<{width}} {v!r}")


# ============================================================================
# 4. SECTIONS
# ============================================================================

def section_a_kv():
    banner("SECTION A: KV store - static secrets, encrypted at rest, plaintext on read")
    v = Vault()
    v.kv_mounts["secret"] = {"current_version": 0, "versions": {}}
    print("vault kv put secret/db username=admin password=s3cr3t-db")
    v1 = v.kv_put("secret/db", username="admin", password="s3cr3t-db")
    print("vault kv put secret/db password=rotated-2026       # rotate -> v2")
    v2 = v.kv_put("secret/db", username="admin", password="rotated-2026")
    print(f"  created versions: v1={v1}, v2={v2} (KV v2 keeps history)\n")

    ver, data = v.kv_get("secret/db")
    show_kv(f"vault kv get secret/db  (current = v{ver}, PLAINTEXT)", data)
    rest = v.kv_at_rest("secret/db")
    print("\n  SIMULATED storage (what etcd holds, XOR-encrypted + base64):")
    for k, c in rest.items():
        print(f"    {k:<12} {c}")
    print("\n  => callers get PLAINTEXT; the store holds ciphertext. Rotation = a")
    print("     new version; old versions are retained (KV v2) until destroyed.\n")

    print("KV v2 path layout:  data    at secret/data/db")
    print("                     metadata at secret/metadata/db   (versions, deletion)")
    assert data["password"] == "rotated-2026"
    assert rest["password"] != "rotated-2026"               # not plaintext at rest
    print("[check] read returns plaintext 'rotated-2026', store != plaintext: OK")
    return v


def section_b_dynamic():
    banner("SECTION B: dynamic secrets - DB user issued on demand, 1h TTL, auto-revoke")
    v = Vault()
    v.db_configure("pg-prod", "postgresql://{{username}}:{{password}}@db:5432/app",
                   "postgresql-database-plugin")
    v.db_role("app-role", db_name="pg-prod", default_ttl=3600, max_ttl=86400,
              creation='CREATE USER "{{name}}" WITH PASSWORD \'{{password}}\'; '
                       'GRANT SELECT ON app.* TO "{{name}}";',
              destruction='DROP USER IF EXISTS "{{name}}";')
    print("vault write database/config/pg-prod connection_url=...")
    print("vault write database/roles/app-role db_name=pg-prod default_ttl=1h max_ttl=24h\n")

    lease = v.db_creds("app-role")
    print("vault read database/creds/app-role  ->  ISSUES a fresh DB user:")
    print(f"  lease_id        {lease.id}")
    print(f"  lease_duration  {lease.ttl}s ({lease.ttl // 60}m)")
    print(f"  renewable       {lease.renewable}")
    show_kv("data", lease.data)
    print("\n  creation_statements (run by the DB plugin):")
    print(indent(v.db_roles['app-role']['creation'], "    "))
    print("\n  destruction_statements (run on revoke/expire):")
    print(indent(v.db_roles['app-role']['destruction'], "    "))

    print("\n  => the app logs in with a UNIQUE, short-lived user. No shared DB")
    print("     password to leak; Vault itself drops the user when the TTL ends.")
    assert lease.data["username"].startswith("v-app-role-")
    assert lease.ttl == 3600 and lease.max_ttl == 86400
    assert not lease.revoked
    print("\n[check] username 'v-app-role-...', ttl=3600s, not yet revoked: OK")
    return v, lease


def section_c_transit():
    banner("SECTION C: transit - encryption as a service (Vault holds the key)")
    v = Vault()
    v.transit_create_key("payments")
    print("vault write -f transit/keys/payments   # create the key (Vault holds it)\n")

    plaintext = "order-42"
    ct = v.transit_encrypt("payments", plaintext)
    print(f'vault write transit/encrypt/payments plaintext=<b64 of "{plaintext}">')
    print(f"  -> ciphertext   {ct}")
    rt = v.transit_decrypt("payments", ct)
    print(f'vault write transit/decrypt/payments ciphertext={ct}')
    print(f"  -> plaintext    {rt!r}")

    print("\n  => Vault NEVER stores the data - it is a stateless crypto API. The")
    print("     app only ever handles ciphertext; the key never leaves Vault. Great")
    print("     for encrypting fields in your own DB without apps seeing the key.")
    assert rt == plaintext
    assert ct.startswith("vault:v1:")
    assert ct != plaintext
    # gold: pin the deterministic ciphertext for the .html
    print(f"\n[check] decrypt(encrypt('{plaintext}')) == '{plaintext}': OK")
    print(f"GOLD ciphertext for vault_secrets.html: transit_encrypt('payments', "
          f"'order-42') = {ct!r}")
    # expose the SIMULATED key bytes (32) so the .html can reproduce it
    kb = list(_derive_key("payments"))
    print(f"GOLD key bytes (SIMULATED, 32 ints): {kb}")
    return v, ct, kb


def section_d_injection(v_kv: Vault):
    banner("SECTION D: injection - vault-agent sidecar writes secrets to a FILE")
    print("The vault-agent-injector is a mutating webhook. Annotate the Pod and a")
    print("sidecar (vault-agent) renders the secret to a shared emptyDir. The app")
    print("reads a FILE - it needs NO Vault SDK.\n")
    pod = Pod("api", annotations={
        "vault.hashicorp.com/agent-inject": "true",
        "vault.hashicorp.com/role": "app",
        "vault.hashicorp.com/agent-inject-secret-db-password": "secret/db",
        "vault.hashicorp.com/agent-inject-template-db-password":
            'DATABASE_PASSWORD="{{ .Data.data.password }}"',
    })
    print("Pod annotations (what the webhook reads):")
    for k, val in pod.annotations.items():
        print(f"  {k}:")
        print(f"    {val}")
    print("\nmutating webhook adds:  init-container vault-agent + sidecar vault-agent")
    print("                        + emptyDir mounted at /vault/secrets/\n")

    inject(pod, v_kv)
    show_kv("files the app sees (rendered by the sidecar)", pod.shared_volume, 38)

    expected = 'DATABASE_PASSWORD="rotated-2026"'
    assert pod.shared_volume["/vault/secrets/db-password"] == expected
    print("\n  => the app does `open('/vault/secrets/db-password').read()` and parses")
    print("     the env line. Sidecar re-renders on rotation; no app code change.")
    print(f"\n[check] /vault/secrets/db-password == {expected!r}: OK")
    return pod


def section_e_lease_gold():
    banner("SECTION E: lease lifecycle + GOLD (renew, revoke, auto-expire, inject)")
    v = Vault()
    v.db_configure("pg-prod", "postgresql://...", "postgresql-database-plugin")
    v.db_role("app-role", db_name="pg-prod", default_ttl=3600, max_ttl=86400,
              creation='CREATE USER "{{name}}";', destruction='DROP USER "{{name}}";')
    lease = v.db_creds("app-role")
    print(f"issued lease {lease.id}:  ttl={lease.ttl}s, max_ttl={lease.max_ttl}s, "
          f"creation_time={lease.creation_time}, expiry={lease.expiry}\n")
    print(f"  {'t(s)':>6}  {'event':<30} {'remaining':>9}  {'revoked'}")
    print(f"  {'-'*6}  {'-'*30} {'-'*9}  {'-'*7}")

    steps: List[Tuple[int, str, Optional[str], Optional[int]]] = [
        # (tick, label, lease_op, renew_increment)
        (0,    "issue (t=0)",                 None, None),
        (1800, "halfway",                     None, None),
        (0,    "renew +3600",                 "renew", 3600),
        (2700, "still valid after renew",     None, None),
        (1000, "expiry reached -> auto-revoke", None, None),
    ]
    timeline = []
    for dt, label, op, inc in steps:
        expired = v.tick(dt) if dt else []
        if op == "renew":
            v.lease_renew(lease.id, inc)
        elif op == "revoke":
            v.lease_revoke(lease.id)
        rem = lease.remaining(v.clock)
        note = ""
        if op == "renew":
            note = f"(expiry -> min(clock+3600, max_expiry) = {lease.expiry})"
        elif expired:
            note = "(clock >= expiry -> DROP USER)"
        print(f"  {v.clock:>6}  {label:<30} {rem:>9}  {str(lease.revoked):<7} {note}")
        timeline.append((v.clock, label, rem, lease.revoked))

    # explicit revoke demo on a FRESH lease: revoke() drops the user EARLY
    v3 = Vault()
    v3.db_configure("pg2", "postgresql://...", "postgresql-database-plugin")
    v3.db_role("r2", db_name="pg2", default_ttl=3600, max_ttl=86400,
               creation='CREATE USER "{{name}}";', destruction='DROP USER "{{name}}";')
    l3 = v3.db_creds("r2")
    v3.tick(120)
    v3.lease_revoke(l3.id)           # revoke NOW, before expiry
    assert l3.revoked

    print("\nREADING THE LIFECYCLE:")
    print("  - t=0      issued, ttl=3600s (1h), expiry=3600.")
    print("  - t=1800   remaining=1800 (half used).")
    print("  - t=1800   renew +3600 -> expiry=min(1800+3600, max_expiry=86400)=5400;")
    print("              remaining is now 3600 again (renewal counts from NOW).")
    print("  - t=4500   remaining=900 (5400-4500).")
    print("  - t=5500   clock >= expiry -> the DB user is AUTO-DROPPED.")
    print("  - revoke() does the SAME DROP USER immediately, on demand (demo at")
    print("    t=120 on a fresh lease: revoked=True well before its TTL).\n")

    # rebuild a clean lease for the gold assertions
    v2 = Vault()
    v2.db_configure("pg", "postgresql://...", "postgresql-database-plugin")
    v2.db_role("r", db_name="pg", default_ttl=3600, max_ttl=86400,
               creation='CREATE USER "{{name}}";', destruction='DROP USER "{{name}}";')
    l2 = v2.db_creds("r")
    v2.tick(1800)
    rem_1800 = l2.remaining(v2.clock)
    pod = Pod("api", annotations={
        "vault.hashicorp.com/agent-inject-secret-db-password": "secret/db",
        "vault.hashicorp.com/agent-inject-template-db-password":
            'DATABASE_PASSWORD="{{ .Data.data.password }}"',
    })
    v2.kv_mounts["secret"] = {"current_version": 0, "versions": {}}
    v2.kv_put("secret/db", password="rotated-2026")
    inject(pod, v2)

    ok_inject = pod.shared_volume["/vault/secrets/db-password"] == 'DATABASE_PASSWORD="rotated-2026"'
    ok_ttl = l2.ttl == 3600 and l2.max_ttl == 86400 and l2.renewable
    ok_rem = rem_1800 == 1800
    ok_all = ok_inject and ok_ttl and ok_rem
    print(f"[check] injected file == 'DATABASE_PASSWORD=\"rotated-2026\"': {ok_inject}")
    print(f"[check] lease ttl=3600, max_ttl=86400, renewable:             {ok_ttl}")
    print(f"[check] remaining at t=1800 == 1800:                          {ok_rem}")
    print(f"[check] GOLD: injection correct + proper TTL: "
          f"{'OK' if ok_all else 'FAIL'}")
    assert ok_all, "GOLD: injection/TTL mismatch"

    print("\nGOLD scalars for vault_secrets.html:")
    print("  injected file       = 'DATABASE_PASSWORD=\"rotated-2026\"'")
    print("  lease ttl / max_ttl = 3600 / 86400")
    print("  remaining at t=1800 = 1800")
    return pod, l2, rem_1800


# ============================================================================
# main
# ============================================================================

def main():
    print("vault_secrets.py - reference model. All output feeds VAULT_SECRETS.md.")
    v_kv = section_a_kv()
    section_b_dynamic()
    section_c_transit()
    section_d_injection(v_kv)
    section_e_lease_gold()
    banner("DONE - all sections printed; all [check]s asserted")


if __name__ == "__main__":
    main()
