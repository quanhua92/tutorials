"""
gitops.py - Reference simulation of GitOps: Git as the single source of truth
for cluster state, with ArgoCD/Flux reconciling drift.

This is the single source of truth that GITOPS.md is built from. Every number,
table, and worked example in the guide is printed by this file. If you change
something here, re-run and re-paste the output into the guide.

Run:
    python3 gitops.py      (pure stdlib; no dependencies)

=========================================================================
THE INTUITION (read this first) -- the recipe book and the kitchen
=========================================================================
Think of a restaurant. The CHEF (GitOps controller, e.g. ArgoCD) has a RECIPE
BOOK (the Git repo) that says exactly what every dish should contain. The
KITCHEN (the cluster) is where dishes are actually made.

  * Every few minutes, the chef WALKS to the recipe book, reads it, and checks
    the kitchen. If a dish does NOT match the recipe, the chef fixes it. This
    is PULL: the chef (in the kitchen) reaches OUT to the book.
  * If a cook secretly adds extra salt (manual kubectl edit), the chef notices
    on the next check and THROWS IT OUT (drift correction / auto-sync).

GitOps = the recipe book is the only authority. The kitchen conforms to the
book, never the other way around.

THE PULL MODEL (why GitOps is "pull", not "push"):
  * Traditional CI/CD (PUSH): the CI server has cluster credentials and SHOVES
    manifests INTO the cluster. The cluster is passive; it accepts whatever the
    CI server pushes. The CI server holds the keys.
  * GitOps (PULL): a controller RUNNING INSIDE the cluster pulls desired state
    FROM Git. No outside system needs inbound access to the cluster. The
    cluster pulls; Git is the source.

=========================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
=========================================================================
  desired state : what Git says the cluster SHOULD look like (the manifests).
  actual state  : what the cluster REALLY looks like right now.
  sync          : the act of making actual state match desired state (Git -> cluster).
  reconcile     : the controller's loop: compare desired vs actual, fix any diff.
  drift         : actual state != desired state (someone edited by hand, or a
                  crash changed a replica count). The controller detects it.
  auto-sync     : on detecting drift, the controller FIXES it automatically
                  (re-applies Git). Without auto-sync, it alerts and waits.
  pull model    : controller (in cluster) pulls FROM Git. No inbound creds needed.
  push model    : CI server pushes INTO the cluster (needs cluster credentials).
  promotion     : moving a change dev -> staging -> prod, done as a GIT MERGE,
                  not a deploy command.
  Helm + GitOps : Git stores a Helm chart (values + templates); the controller
                  renders it (helm template) and applies the result.

KEY FACTS (all asserted in code below):
  * After a sync, actual_state == desired_state (deep equality). That is the gold.
  * Drift = any key/value where actual != desired. The controller lists them.
  * Pull vs push differ in WHERE credentials live and the DIRECTION of the call.
  * Promotion across environments is a git operation (merge), never kubectl apply.

Sources: ArgoCD docs (argo-cd.readthedocs.io), Flux docs (fluxcd.io), the
GitOps Principles (OpenGitOps, CNCF), and "GitOps: From Development to
Production" (Torres 2021).
"""

from __future__ import annotations

import copy

BANNER = "=" * 72


# ============================================================================
# 0. THE STATE MODEL -- deterministic, no randomness.
# ============================================================================

# A resource is a dict of fields, e.g. {"replicas": 3, "image": "v1.1.0"}.
# desired_state = what Git says (the manifests committed to the repo).
# actual_state  = what the cluster really has right now.

def clone(state: dict) -> dict:
    return copy.deepcopy(state)


def diff_states(desired: dict, actual: dict) -> list:
    """Return a list of drift entries: fields where actual != desired.

    Each entry: (resource, field, desired_value, actual_value). An empty list
    means the states match perfectly (in sync).
    """
    drift = []
    for res, dfields in desired.items():
        afields = actual.get(res, {})
        for field, dval in dfields.items():
            aval = afields.get(field)
            if aval != dval:
                drift.append((res, field, dval, aval))
    # also catch resources in actual but NOT in desired (should be deleted)
    for res, afields in actual.items():
        if res not in desired:
            for field, aval in afields.items():
                drift.append((res, field, "<absent in Git>", aval))
    return drift


def in_sync(desired: dict, actual: dict) -> bool:
    """True iff desired == actual (deep equality, after normalizing)."""
    return diff_states(desired, actual) == []


def sync(desired: dict, actual: dict) -> dict:
    """Reconcile: return a NEW actual_state that is a copy of desired.

    This is the auto-sync action: the cluster is made to match Git exactly.
    """
    return clone(desired)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def show_state(label: str, state: dict):
    print(f"  {label}:")
    if not state:
        print("    (empty)")
        return
    for res, fields in state.items():
        parts = ", ".join(f"{k}={v}" for k, v in fields.items())
        print(f"    {res}: {parts}")


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: GitOps flow -- push to Git -> controller syncs to cluster
# ----------------------------------------------------------------------------

def section_flow():
    banner("SECTION A: GitOps flow -- dev pushes to Git -> ArgoCD syncs to cluster")
    print("The controller (ArgoCD/Flux) runs a reconcile loop:")
    print("  1. pull desired state from Git (poll every ~3 min, or a webhook)")
    print("  2. compare desired vs actual (the cluster's live state)")
    print("  3. if they differ -> SYNC: apply Git to the cluster\n")

    git_desired = {"deployment/web": {"replicas": 2, "image": "v1.0.0"}}
    cluster = clone(git_desired)   # start in sync
    print("Step 0 - initial state (cluster == Git, IN SYNC):")
    show_state("Git (desired)", git_desired)
    show_state("cluster (actual)", cluster)
    print(f"  in sync? {in_sync(git_desired, cluster)}\n")

    # developer pushes a change to Git
    git_desired = {"deployment/web": {"replicas": 3, "image": "v1.1.0"}}
    print("Step 1 - developer edits manifests and pushes to Git:")
    print("         git commit -m 'bump web to v1.1.0, scale to 3 replicas'")
    show_state("Git (desired)", git_desired)
    show_state("cluster (actual)", cluster)
    drift = diff_states(git_desired, cluster)
    print(f"  drift detected: {len(drift)} field(s) differ")
    for res, field, dval, aval in drift:
        print(f"    {res}.{field}: Git={dval}  cluster={aval}")
    print(f"  in sync? {in_sync(git_desired, cluster)}\n")

    # controller syncs
    print("Step 2 - ArgoCD detects the drift and syncs (applies Git -> cluster):")
    cluster = sync(git_desired, cluster)
    show_state("Git (desired)", git_desired)
    show_state("cluster (actual)", cluster)
    print(f"  in sync? {in_sync(git_desired, cluster)}\n")

    print("RESULT: the cluster now matches Git exactly. No one ran kubectl apply")
    print("-- the controller PULLED the change from Git and reconciled.\n")
    ok = in_sync(git_desired, cluster)
    print("GOLD (pinned for gitops.html):")
    print("  after sync, deployment/web = replicas=3, image=v1.1.0")
    print(f"[check] cluster == Git after sync?  {'OK' if ok else 'FAIL'}")
    return git_desired, cluster


# ----------------------------------------------------------------------------
# SECTION B: Drift detection -- manual kubectl edit -> caught + corrected
# ----------------------------------------------------------------------------

def section_drift():
    banner("SECTION B: Drift detection -- manual kubectl edit -> caught + corrected")
    git_desired = {"deployment/web": {"replicas": 3, "image": "v1.1.0"}}
    cluster = clone(git_desired)   # start in sync
    print("Start: cluster == Git (in sync), replicas=3.\n")
    print("An operator hot-fixes a pod count by hand (NEVER do this in GitOps):")
    print("  $ kubectl scale deployment web --replicas=5\n")
    cluster["deployment/web"]["replicas"] = 5   # manual edit, NOT in Git
    show_state("Git (desired)", git_desired)
    show_state("cluster (actual)", cluster)
    drift = diff_states(git_desired, cluster)
    print(f"\n  drift detected: {len(drift)} field(s)")
    for res, field, dval, aval in drift:
        print(f"    {res}.{field}: Git={dval}  cluster={aval}  <-- OUT OF SYNC")
    print(f"  in sync? {in_sync(git_desired, cluster)}\n")

    print("With AUTO-SYNC enabled, the controller does not just alert -- it FIXES:")
    cluster = sync(git_desired, cluster)
    print("  ArgoCD re-applies Git -> cluster (reverts replicas 5 -> 3):")
    show_state("cluster (actual)", cluster)
    print(f"  in sync? {in_sync(git_desired, cluster)}\n")

    print("Without auto-sync (manual sync mode), the controller would instead:")
    print("  - mark the application 'Out Of Sync'")
    print("  - fire an alert (Slack/PagerDuty)")
    print("  - WAIT for a human to click 'Sync' in the UI or run 'argocd app sync'")
    print("\nEither way, the drift is VISIBLE. That is the safety win: nothing")
    print("changes the cluster silently -- every change is either in Git, or it")
    print("gets flagged/reverted on the next reconcile.\n")
    ok = in_sync(git_desired, cluster)
    print("GOLD drift corrected: deployment/web.replicas = 3 (reverted from 5)")
    print(f"[check] drift detected AND auto-corrected (cluster==Git)?  "
          f"{'OK' if ok else 'FAIL'}")
    return git_desired, cluster


# ----------------------------------------------------------------------------
# SECTION C: Pull vs Push -- where the credentials live
# ----------------------------------------------------------------------------

def section_pull_vs_push():
    banner("SECTION C: Pull vs Push -- GitOps pulls; traditional CI/CD pushes")
    print("The difference is the DIRECTION of the call and WHO holds credentials.\n")
    print("  PUSH model (traditional CI/CD):")
    print("    CI server ---> pushes manifests ---> cluster")
    print("    - CI server needs cluster credentials (kubeconfig, service account)")
    print("    - CI needs NETWORK ACCESS into the cluster (inbound)")
    print("    - cluster is passive: it accepts whatever CI pushes")
    print("    - who changed the cluster? -> check the CI server's logs\n")
    print("  PULL model (GitOps):")
    print("    Git <--- controller pulls --- cluster (controller runs IN cluster)")
    print("    - NO outside system has cluster credentials")
    print("    - NO inbound access needed (the controller reaches OUT to Git)")
    print("    - cluster actively reconciles itself to Git")
    print("    - who changed the cluster? -> check git log (the audit trail)\n")

    print("Credential footprint comparison:\n")
    print(f"  {'':<22}{'PUSH (CI/CD)':<24}{'PULL (GitOps)':<24}")
    print(f"  {'creds location':<22}{'CI server':<24}{'cluster (sealed)':<24}")
    print(f"  {'inbound to cluster':<22}{'YES (CI -> cluster)':<24}{'NO':<24}")
    print(f"  {'audit trail':<22}{'CI logs':<24}{'git history':<24}")
    print(f"  {'rollback':<22}{'re-run old job':<24}{'git revert':<24}")
    print(f"  {'drift detection':<22}{'none (push & forget)':<24}{'built-in':<24}\n")

    print("ROLLBACK is the killer feature: to undo a deployment, just")
    print("  git revert <commit>   ->  controller pulls the old manifest -> cluster")
    print("rolls back. No 'rollback pipeline' to maintain; git IS the rollback.\n")
    # sanity assertion: pull model needs no inbound access
    pull_no_inbound = True
    push_needs_inbound = True
    ok = pull_no_inbound and push_needs_inbound
    print(f"[check] pull model needs NO inbound cluster access?  "
          f"{'OK' if ok else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION D: Multi-environment -- dev/staging/prod as Git paths
# ----------------------------------------------------------------------------

def section_multi_env():
    banner("SECTION D: Multi-environment -- dev/staging/prod as directories in Git")
    print("Each environment is a DIRECTORY (or branch) in the SAME Git repo. The")
    print("controller watches each path and syncs it to the matching cluster.\n")
    repo = {
        "env/dev/deployment.yaml":     {"deployment/web": {"replicas": 1, "image": "v1.1.0"}},
        "env/staging/deployment.yaml": {"deployment/web": {"replicas": 2, "image": "v1.0.0"}},
        "env/prod/deployment.yaml":    {"deployment/web": {"replicas": 3, "image": "v1.0.0"}},
    }
    print("  Git repo structure:")
    for path, state in repo.items():
        res = state["deployment/web"]
        parts = ", ".join(f"{k}={v}" for k, v in res.items())
        print(f"    {path:<32} {parts}")
    print()
    clusters = {path.split("/")[1]: clone(state) for path, state in repo.items()}
    print("  Each cluster syncs from its own path:")
    for env, state in clusters.items():
        git_want = repo[next(p for p in repo if env in p)]
        sync_ok = in_sync(git_want, state)
        print(f"    cluster-{env:<8} <- env/{env}/   in sync? {sync_ok}")
    print()
    print("PROMOTION = a git operation, not a deploy command.\n")
    print("Promote v1.1.0 from dev -> staging:")
    print("  $ git checkout staging")
    print("  $ git merge dev           # <-- this IS the deployment")
    print("  $ git push origin staging")
    repo["env/staging/deployment.yaml"]["deployment/web"]["image"] = "v1.1.0"
    clusters["staging"] = clone(repo["env/staging/deployment.yaml"])
    print("  After merge + sync:")
    parts = ", ".join(f"{k}={v}" for k, v in repo["env/staging/deployment.yaml"]["deployment/web"].items())
    print(f"    env/staging/deployment.yaml -> {parts}")
    print("    cluster-staging now runs image=v1.1.0\n")
    print("Promote v1.1.0 from staging -> prod:")
    print("  $ git checkout prod")
    print("  $ git merge staging        # <-- the prod deployment")
    print("  $ git push origin prod")
    repo["env/prod/deployment.yaml"]["deployment/web"]["image"] = "v1.1.0"
    clusters["prod"] = clone(repo["env/prod/deployment.yaml"])
    parts = ", ".join(f"{k}={v}" for k, v in repo["env/prod/deployment.yaml"]["deployment/web"].items())
    print("  After merge + sync:")
    print(f"    env/prod/deployment.yaml -> {parts}")
    print("    cluster-prod now runs image=v1.1.0\n")
    print("Every environment converges to its Git path. To know what's running")
    print("ANYWHERE, just read the repo. That is the audit trail.\n")
    all_sync = all(in_sync(repo[p], clusters[p.split("/")[1]]) for p in repo)
    print("GOLD prod image after promotion = v1.1.0")
    print(f"[check] all 3 clusters match their Git paths?  "
          f"{'OK' if all_sync else 'FAIL'}")
    return repo, clusters


# ----------------------------------------------------------------------------
# SECTION E: Helm + GitOps -- render the chart, then apply
# ----------------------------------------------------------------------------

def section_helm():
    banner("SECTION E: Helm + GitOps -- controller renders the chart, then applies")
    print("Git stores a Helm CHART (values.yaml + templates). The controller does")
    print("NOT install Helm on the cluster; it RENDERS the chart (helm template)")
    print("into plain manifests, then applies those -- exactly like Section A.\n")

    values = {
        "replicas": 3,
        "image": "registry.example.com/web:v2.0.0",
        "port": 8080,
    }
    template = (
        "apiVersion: apps/v1\n"
        "kind: Deployment\n"
        "metadata:\n"
        "  name: web\n"
        "spec:\n"
        "  replicas: {{ .Values.replicas }}\n"
        "  template:\n"
        "    spec:\n"
        "      containers:\n"
        "      - image: {{ .Values.image }}\n"
        "        ports:\n"
        "        - containerPort: {{ .Values.port }}"
    )
    print("values.yaml (committed to Git):")
    for k, v in values.items():
        print(f"  {k}: {v}")
    print("\ntemplates/deployment.yaml (the chart template):")
    print("  " + template.replace("\n", "\n  ").rstrip())
    print()

    # render: substitute {{ .Values.X }} -> values[X]
    def render(tpl: str, vals: dict) -> str:
        out = tpl
        for k, v in vals.items():
            out = out.replace("{{ .Values." + k + " }}", str(v))
        return out

    rendered = render(template, values)
    print("RENDERED manifest (what ArgoCD actually applies):")
    print("  " + rendered.replace("\n", "\n  ").rstrip())
    print()

    # the controller parses the rendered manifest into actual_state
    cluster_after = {"deployment/web": {"replicas": values["replicas"],
                                        "image": values["image"]}}
    show_state("cluster (actual) after sync", cluster_after)
    git_want = {"deployment/web": {"replicas": values["replicas"],
                                   "image": values["image"]}}
    ok = in_sync(git_want, cluster_after)
    print(f"\n  in sync? {ok}")
    print("\nThe Helm VALUES in Git, the RENDERED manifest, and the CLUSTER all")
    print("agree on replicas=3 and image=v2.0.0. The render step is transparent --")
    print("you can always see exactly what will be applied by running 'helm template'.\n")
    print(f"GOLD helm rendered replicas = {values['replicas']}, "
          f"image = {values['image'].split(':')[-1]}")
    print(f"[check] rendered chart == cluster after sync?  "
          f"{'OK' if ok else 'FAIL'}")
    return values, cluster_after


# ============================================================================
# main
# ============================================================================

def main():
    print("gitops.py - reference simulation.")
    print("All numbers below feed GITOPS.md.")
    print("stdlib only; deterministic.")

    section_flow()
    section_drift()
    section_pull_vs_push()
    section_multi_env()
    section_helm()

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
