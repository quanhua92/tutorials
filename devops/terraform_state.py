"""
terraform_state.py - Reference simulation of Terraform state, plan, apply,
state locking, and drift.

This is the single source of truth that TERRAFORM_STATE.md is built from.
Every number, JSON blob, and plan/apply/drift scenario in the guide is printed
by this file. If you change something here, re-run and re-paste the output.

Run:
    python3 terraform_state.py      (pure stdlib; no dependencies)

============================================================================
THE INTUITION (read this first) -- the contractor's master ledger
============================================================================
Imagine a building contractor who keeps a MASTER LEDGER (the state file,
terraform.tfstate). The ledger records, for every wall, door, and pipe that
has actually been BUILT, its real-world identifier and its exact specs.

Your BLUEPRINT (the *.tf config files) says what you WANT the building to be.

  * terraform plan  = hold the blueprint next to the ledger and compute the
                      DIFF: what must be created, updated, replaced, destroyed.
  * terraform apply = carry out that diff against the real building, then
                      REWRITE the ledger so it matches the new reality.

The ledger (state) is the SOURCE OF TRUTH for what EXISTS. A plan is never a
raw "config vs cloud" read; it is "config vs state" -- preceded by a REFRESH
that re-reads the cloud into the ledger first. That refresh is exactly how
DRIFT (out-of-band changes) surfaces on a normal `plan`.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  tfstate           : the master ledger. A JSON file recording every resource
                      Terraform manages, with its real cloud ID + attributes.
  address           : a resource's key, "type.name" e.g. aws_instance.web. This
                      is how Terraform matches a config block to a state entry.
  plan              : the diff between desired config and current state. Labels
                      each resource create / update / replace / destroy / no-op.
  create            : in config but NOT in state -> build it.
  destroy           : in state but NOT in config -> tear it down.
  update (in-place) : in both; some attribute changed that the cloud can alter
                      without rebuilding (e.g. instance_type, tags).
  replace           : in both; an attribute that CANNOT change in-place changed
                      (e.g. AMI of an EC2) -> destroy old + create new.
  apply             : execute the plan against the cloud, then rewrite tfstate.
                      Every apply bumps the "serial" counter by 1.
  serial            : integer in tfstate, +1 per write. Two writers both at
                      serial N would clobber; the state LOCK prevents that.
  refresh           : before planning, Terraform re-reads each resource's
                      current cloud attributes into state (in memory). This is
                      how drift is detected on a normal `plan`.
  drift             : the real cloud resource no longer matches tfstate because
                      someone changed it out-of-band (console, CLI, another IaC).
  backend           : where tfstate is stored. local file (one machine) or
                      remote (S3 + DynamoDB lock, Terraform Cloud) for teams.
  state lock        : a short-lived mutex (a DynamoDB row / .lock.info) held
                      during plan/apply so two runs cannot corrupt the state.
  import            : bring an EXISTING cloud resource (made outside Terraform)
                      into state, so Terraform will manage it from now on.

KEY FACTS (all asserted in code below):
  * plan = diff(config, state). The cloud is read via the refresh that precedes
    the diff.
  * Changing instance_type on aws_instance = in-place UPDATE. Changing AMI =
    REPLACE (the provider has ForceNew on ami).
  * apply always rewrites state and increments serial.
  * A state lock (DynamoDB) blocks concurrent applies; the second waits.
  * Drift is invisible to a stale state; refresh makes `plan` show it.

Sources: Terraform docs -- State, Backends & Locking, Import, Command: plan,
Command: apply, "Import existing infrastructure" guide
(developer.hashicorp.com/terraform). AWS provider schema: ami=ForceNew,
instance_type=in-place.
"""

from __future__ import annotations

import copy
import json

BANNER = "=" * 72

# ============================================================================
# 0. THE MODEL -- deterministic. config = desired (HCL), state = the ledger.
#    Per resource type, a set of attributes whose change forces REPLACEMENT
#    (ForceNew). Everything else that changes is an in-place UPDATE.
# ============================================================================

FORCES_REPLACE: dict[str, set[str]] = {
    "aws_instance": {"ami"},          # new AMI => new EC2 instance
    "aws_s3_bucket": {"bucket"},      # new bucket name => new bucket
}

# Base configuration (main.tf v1): the infra we start from.
CONFIG_V1 = [
    {"address": "aws_instance.web", "type": "aws_instance", "name": "web",
     "attributes": {"ami": "ami-aaa", "instance_type": "t3.micro",
                    "tags": {"Name": "web"}}},
    {"address": "aws_s3_bucket.data", "type": "aws_s3_bucket", "name": "data",
     "attributes": {"bucket": "data-prod", "tags": {}}},
    {"address": "aws_s3_bucket.logs", "type": "aws_s3_bucket", "name": "logs",
     "attributes": {"bucket": "logs-prod", "tags": {}}},
]

# Configuration v2: a change set exercising all four plan actions.
#   aws_instance.web   AMI ami-aaa -> ami-bbb    -> REPLACE (ForceNew on ami)
#   aws_instance.api   NEW                        -> CREATE
#   aws_s3_bucket.data tags  {}    -> {Env:prod} -> UPDATE (in-place)
#   aws_s3_bucket.logs REMOVED from config        -> DESTROY
CONFIG_V2 = [
    {"address": "aws_instance.web", "type": "aws_instance", "name": "web",
     "attributes": {"ami": "ami-bbb", "instance_type": "t3.micro",
                    "tags": {"Name": "web"}}},
    {"address": "aws_instance.api", "type": "aws_instance", "name": "api",
     "attributes": {"ami": "ami-ccc", "instance_type": "t3.micro",
                    "tags": {"Name": "api"}}},
    {"address": "aws_s3_bucket.data", "type": "aws_s3_bucket", "name": "data",
     "attributes": {"bucket": "data-prod", "tags": {"Env": "prod"}}},
]


# ============================================================================
# 1. STATE + DIFF + APPLY + REFRESH  (the code TERRAFORM_STATE.md walks through)
# ============================================================================

def addr_of(resource: dict) -> str:
    """A resource's address = 'type.name'. The key that matches config to state."""
    return f'{resource["type"]}.{resource["name"]}'


def make_tfstate(config: list, serial: int = 1) -> dict:
    """Build a realistic terraform.tfstate v4 blob from a config list."""
    return {
        "version": 4,
        "terraform_version": "1.6.0",
        "serial": serial,
        "lineage": "f3c2a1b0-1111-2222-3333-444455556666",
        "outputs": {},
        "resources": [
            {
                "mode": "managed",
                "type": rc["type"],
                "name": rc["name"],
                "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
                "instances": [
                    {"schema_version": 0,
                     "attributes": copy.deepcopy(rc["attributes"])}
                ],
            }
            for rc in config
        ],
    }


def diff_plan(config: list, state_resources: list) -> list:
    """plan = diff(config, state). Returns a list of actions, one per changed
    resource (unchanged resources produce no action = no-op, omitted).

    Classification rules:
      create  : address in config, NOT in state
      destroy : address in state,  NOT in config
      update  : in both, some attribute changed, NONE of the changed attrs
                forces replacement
      replace : in both, some attribute changed, AND at least one changed attr
                is in FORCES_REPLACE for that type
    """
    cfg = {rc["address"]: rc for rc in config}
    st = {addr_of(r): r for r in state_resources}
    actions = []
    # config-driven actions (create / update / replace), in address order
    for address in sorted(cfg):
        rc = cfg[address]
        if address not in st:
            actions.append({"address": address, "type": rc["type"],
                            "action": "create",
                            "reason": "present in config, absent in state"})
            continue
        st_attrs = st[address]["instances"][0]["attributes"]
        changed = {}
        for k, v in rc["attributes"].items():
            if st_attrs.get(k) != v:
                changed[k] = {"old": st_attrs.get(k), "new": v}
        if not changed:
            continue
        forces = FORCES_REPLACE.get(rc["type"], set())
        action = "replace" if any(k in forces for k in changed) else "update"
        actions.append({"address": address, "type": rc["type"],
                        "action": action, "changed": changed})
    # destroy actions, in address order
    for address in sorted(st):
        if address not in cfg:
            actions.append({"address": address, "type": st[address]["type"],
                            "action": "destroy",
                            "reason": "present in state, absent in config"})
    return actions


def apply_plan(tfstate: dict, config: list, actions: list) -> dict:
    """Execute the plan: mutate resources to match config, bump serial.
    Returns a NEW tfstate (the input is not mutated)."""
    new = copy.deepcopy(tfstate)
    new["serial"] += 1
    res = new["resources"]
    cfg = {rc["address"]: rc for rc in config}

    def remove(address):
        res[:] = [r for r in res if addr_of(r) != address]

    def add(rc):
        res.append({
            "mode": "managed", "type": rc["type"], "name": rc["name"],
            "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
            "instances": [{"schema_version": 0,
                           "attributes": copy.deepcopy(rc["attributes"])}],
        })

    for a in actions:
        address = a["address"]
        act = a["action"]
        if act in ("destroy", "replace"):
            remove(address)
        if act in ("create", "replace"):
            add(cfg[address])
        if act == "update":
            for r in res:
                if addr_of(r) == address:
                    for k, ch in a["changed"].items():
                        r["instances"][0]["attributes"][k] = ch["new"]
    return new


def refresh_state(state_resources: list, real: dict) -> list:
    """refresh = re-read each resource's current CLOUD attributes into state
    (in memory). `real` maps address -> current cloud attributes. Returns a new
    resource list reflecting reality."""
    out = copy.deepcopy(state_resources)
    for r in out:
        a = addr_of(r)
        if a in real:
            r["instances"][0]["attributes"] = copy.deepcopy(real[a])
    return out


# ============================================================================
# 2. STATE BACKEND + LOCK  (S3 + DynamoDB)
# ============================================================================

class S3DynamoDBBackend:
    """Models an S3 backend (holds tfstate) + a DynamoDB lock table.

    acquire_lock(run_id) returns False (blocked) if another run holds the lock.
    apply() enforces that a lock MUST be held, then rewrites state + bumps
    serial, exactly as Terraform does under the hood."""

    def __init__(self, tfstate: dict):
        self.tfstate = tfstate
        self.lock_held_by = None   # the DynamoDB lock item: {LockID: run_id}

    def acquire_lock(self, run_id: str) -> bool:
        if self.lock_held_by is not None:
            return False           # blocked: another apply holds the lock
        self.lock_held_by = run_id
        return True

    def release_lock(self, run_id: str):
        assert self.lock_held_by == run_id, "cannot release a lock you do not own"
        self.lock_held_by = None

    def write_state(self, run_id: str, tfstate: dict):
        assert self.lock_held_by == run_id, "must hold the lock to write state"
        self.tfstate = tfstate


# ============================================================================
# 3. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def show_resource_json(resource: dict) -> str:
    """Pretty-print one tfstate resource entry (realistic v4 shape)."""
    return json.dumps(resource, indent=2)


# ============================================================================
# 4. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: State structure -- the tfstate ledger for an EC2 + an S3 bucket
# ----------------------------------------------------------------------------

def section_state_structure():
    banner("SECTION A: State structure -- the terraform.tfstate ledger")
    print("tfstate is a JSON file. The 'resources' array has one entry per")
    print("managed resource. Each entry pins type, name, provider, and an")
    print("'instances' array holding the real cloud attributes + ID.\n")
    state = make_tfstate(CONFIG_V1, serial=1)
    print("After applying CONFIG_V1, tfstate contains 3 resources. Here are the")
    print("first two (an EC2 instance and an S3 bucket):\n")
    for r in state["resources"][:2]:
        print(show_resource_json(r))
        print()
    print("KEY POINTS:")
    print("  * The address 'aws_instance.web' is the join key between a config")
    print("    block 'resource \"aws_instance\" \"web\"' and this state entry.")
    print("  * 'attributes' holds the REAL values the provider read back from")
    print("    the cloud (id, instance_type, ami, tags). This is the ledger.")
    print("  * 'serial' (shown next) increments on every state WRITE.")
    print(f"\ntop-level keys: {list(state.keys())}")
    print(f"resource addresses in state: "
          f"{[addr_of(r) for r in state['resources']]}")
    return state


# ----------------------------------------------------------------------------
# SECTION B: Plan -- the diff (GOLD: 4 actions, one of each kind)
# ----------------------------------------------------------------------------

def section_plan(state: dict):
    banner("SECTION B: Plan -- diff(CONFIG_V2, state)  (GOLD: 4 actions)")
    print("CONFIG_V2 differs from CONFIG_V1 in four ways, designed to exercise")
    print("every plan action:\n")
    print("  aws_instance.web   ami  ami-aaa -> ami-bbb     (ForceNew => REPLACE)")
    print("  aws_instance.api   brand new                  => CREATE")
    print("  aws_s3_bucket.data tags {} -> {Env:prod}      => UPDATE (in-place)")
    print("  aws_s3_bucket.logs removed from config        => DESTROY\n")
    actions = diff_plan(CONFIG_V2, state["resources"])
    print(f"terraform plan  ->  {len(actions)} action(s):\n")
    for a in actions:
        line = f"  # {a['action'].upper():<7} {a['address']}"
        if a["action"] == "create":
            line += f"   ({a['reason']})"
        elif a["action"] == "destroy":
            line += f"   ({a['reason']})"
        elif a["action"] == "replace":
            ch = ", ".join(f"{k}: {v['old']} -> {v['new']}"
                           for k, v in a["changed"].items())
            line += f"   ({ch}  [forces new resource])"
        elif a["action"] == "update":
            ch = ", ".join(f"{k}: {v['old']} -> {v['new']}"
                           for k, v in a["changed"].items())
            line += f"   ({ch}  [in-place])"
        print(line)
    print()
    by_action = {}
    for a in actions:
        by_action.setdefault(a["action"], []).append(a["address"])
    print("Grouped by action:")
    for act in ("create", "update", "replace", "destroy"):
        addrs = by_action.get(act, [])
        print(f"  {act:<7} -> {addrs}")
    # GOLD: exactly one of each, with the expected addresses
    expected = {
        "create": ["aws_instance.api"],
        "update": ["aws_s3_bucket.data"],
        "replace": ["aws_instance.web"],
        "destroy": ["aws_s3_bucket.logs"],
    }
    print()
    print("GOLD (pinned for terraform_state.html):")
    for act in ("create", "update", "replace", "destroy"):
        print(f"  {act:<7} -> {expected[act]}")
    ok = all(by_action.get(act, []) == expected[act] for act in expected)
    print(f"[check] plan classifies create/update/replace/destroy correctly?  "
          f"{'OK' if ok else 'FAIL'}")
    return actions


# ----------------------------------------------------------------------------
# SECTION C: Apply -- execute the plan, rewrite state, serial += 1
# ----------------------------------------------------------------------------

def section_apply(state: dict, actions: list):
    banner("SECTION C: Apply -- execute the plan, rewrite tfstate (serial += 1)")
    print("apply carries out each action against the cloud, then rewrites")
    print("tfstate so the ledger matches reality. Every apply bumps 'serial'.\n")
    print(f"serial BEFORE apply = {state['serial']}")
    new = apply_plan(state, CONFIG_V2, actions)
    print(f"serial AFTER  apply = {new['serial']}   (+1)\n")
    before = sorted(addr_of(r) for r in state["resources"])
    after = sorted(addr_of(r) for r in new["resources"])
    print(f"addresses BEFORE: {before}")
    print(f"addresses AFTER : {after}\n")
    print("What happened:")
    print("  * aws_instance.api    CREATED  -> now in state")
    print("  * aws_s3_bucket.logs  DESTROYED -> gone from state")
    print("  * aws_instance.web    REPLACED -> ami now ami-bbb (old entry removed,")
    print("                                       new entry added; new cloud id)")
    print("  * aws_s3_bucket.data  UPDATED  -> tags now {Env: prod}\n")
    # show the two resources whose attributes changed
    for r in new["resources"]:
        a = addr_of(r)
        if a in ("aws_instance.web", "aws_s3_bucket.data"):
            print(f"{a}:")
            print(f"  {json.dumps(r['instances'][0]['attributes'])}")
    # GOLD: re-running plan now yields a no-op (config == state)
    noop = diff_plan(CONFIG_V2, new["resources"])
    print()
    print(f"Re-planning CONFIG_V2 against the NEW state: {len(noop)} action(s)")
    print("  -> config now matches state => idempotent. A second apply is a no-op.")
    print(f"[check] apply made config and state converge (no-op re-plan)?  "
          f"{'OK' if len(noop) == 0 else 'FAIL'}")
    return new


# ----------------------------------------------------------------------------
# SECTION D: State backend + lock (S3 + DynamoDB)
# ----------------------------------------------------------------------------

def section_backend(state: dict):
    banner("SECTION D: Backend -- S3 stores tfstate, DynamoDB locks it")
    print("For teams, tfstate lives in a shared BACKEND: an S3 bucket holds the")
    print("file; a DynamoDB table provides a LOCK so two concurrent applies")
    print("cannot both rewrite (and clobber) the state.\n")
    print("Lock lifecycle (one DynamoDB row, keyed by LockID, per apply):")
    print("  1. apply starts   -> acquire_lock(run_id). If held -> BLOCKED (wait).")
    print("  2. apply runs      -> mutates cloud + builds new tfstate in memory.")
    print("  3. apply finishes  -> write_state (only allowed while lock held).")
    print("  4.                 -> release_lock. The waiting run may now proceed.\n")
    backend = S3DynamoDBBackend(copy.deepcopy(state))
    print("Simulation: engineers Alice and Bob both run `apply` at once.\n")
    ok_alice = backend.acquire_lock("run-alice")
    ok_bob = backend.acquire_lock("run-bob")
    print(f"  Alice acquires lock: {ok_alice}   -> lock_held_by = {backend.lock_held_by!r}")
    print(f"  Bob   acquires lock: {ok_bob}   -> BLOCKED (must wait; state unsafe")
    print("                                   to write without the lock)\n")
    # Alice writes + releases
    bumped = copy.deepcopy(backend.tfstate)
    bumped["serial"] += 1
    backend.write_state("run-alice", bumped)
    print(f"  Alice writes state (serial {state['serial']} -> {bumped['serial']}), "
          "then releases the lock.")
    backend.release_lock("run-alice")
    # Bob retries
    ok_bob2 = backend.acquire_lock("run-bob")
    print(f"  Bob retries:        {ok_bob2}   -> lock_held_by = {backend.lock_held_by!r}")
    print("     Bob now reads serial = " + str(backend.tfstate["serial"]) +
          " (Alice's write), NOT the stale value. No clobber.\n")
    print("WITHOUT the lock: both would read serial=N, both write serial=N+1, and")
    print("Alice's apply would silently vanish (lost update). The DynamoDB lock")
    print("is what makes shared state safe for teams.\n")
    ok = ok_alice and (not ok_bob) and ok_bob2
    print(f"[check] lock blocked the 2nd apply until the 1st released?  "
          f"{'OK' if ok else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION E: Drift -- manual cloud change -> refresh makes plan see it
# ----------------------------------------------------------------------------

def section_drift(state: dict):
    banner("SECTION E: Drift -- out-of-band change surfaces via refresh")
    print("Someone edits the EC2 instance_type in the AWS CONSOLE: t3.micro ->")
    print("t3.large. Neither the config nor tfstate know about it yet.\n")
    real = {"aws_instance.web": {"ami": "ami-aaa", "instance_type": "t3.large",
                                 "tags": {"Name": "web"}}}
    print("  config (main.tf)  : instance_type = t3.micro   (desired)")
    print("  tfstate (ledger)  : instance_type = t3.micro   (last known)")
    print("  real cloud (drift): instance_type = t3.large   (someone's console edit)\n")
    # plan WITHOUT refresh: diff(config, state) -- stale, drift invisible
    stale = diff_plan(CONFIG_V1, state["resources"])
    print(f"plan WITHOUT refresh  diff(CONFIG_V1, tfstate): {len(stale)} action(s)")
    print("  -> config matches tfstate, so the drift is INVISIBLE. Dangerous:")
    print("     the next apply would silently 'fix' it back to t3.micro.\n")
    # plan WITH refresh: refresh reads cloud into state, THEN diff
    refreshed = refresh_state(state["resources"], real)
    with_refresh = diff_plan(CONFIG_V1, refreshed)
    print("plan WITH refresh  (refresh first, then diff):")
    for a in with_refresh:
        ch = ", ".join(f"{k}: {v['old']} -> {v['new']}"
                       for k, v in a["changed"].items())
        print(f"  # {a['action'].upper():<7} {a['address']}   ({ch}  [in-place])")
    print()
    print("WHY: `terraform plan` runs a REFRESH by default -- it re-reads every")
    print("resource's current cloud attributes into state BEFORE diffing. So the")
    print("drift (t3.micro wanted vs t3.large real) shows up as an UPDATE that")
    print("would change instance_type back to t3.micro. `terraform plan")
    print("-refresh-only` would instead just update tfstate to record the drift.\n")
    saw_drift = (len(with_refresh) == 1 and with_refresh[0]["action"] == "update"
                 and with_refresh[0]["changed"].get("instance_type",
                            {}).get("old") == "t3.large")
    print(f"[check] refresh made plan detect the drift (t3.large)?  "
          f"{'OK' if saw_drift else 'FAIL'}")


# ============================================================================
# main
# ============================================================================

def main():
    print("terraform_state.py - reference simulation.")
    print("All output below feeds TERRAFORM_STATE.md.")
    print("stdlib only; deterministic.")

    state = section_state_structure()
    actions = section_plan(state)
    section_apply(state, actions)
    section_backend(state)
    section_drift(state)

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
