"""
hcl_graph.py - Reference simulation of the Terraform HCL resource dependency
graph: how resources reference each other, how that forms a DAG, and how the
DAG drives creation order and parallel execution.

This is the single source of truth that HCL_GRAPH.md is built from. Every
graph, topological order, and execution wave in the guide is printed by this
file. If you change something here, re-run and re-paste the output.

Run:
    python3 hcl_graph.py      (pure stdlib; no dependencies)

============================================================================
THE INTUITION (read this first) -- the construction site with prerequisites
============================================================================
Think of Terraform config as a construction site. Each `resource` block is a
TASK. Some tasks cannot start until another finishes: you cannot pour the
floor (subnet) before the foundation (VPC) exists, and you cannot wire the
doorbell (EIP) before the wall with the door (instance) is up.

Terraform discovers these prerequisites by READING YOUR HCL:

  * IMPLICIT dependency -- when one block references another's output, e.g.
        subnet_id = aws_subnet.main.id
    Terraform KNOWS the instance needs the subnet, so it draws an edge
    aws_subnet.main -> aws_instance.app.
  * EXPLICIT dependency -- when you write
        depends_on = [aws_iam_role_policy.app]
    you add an edge yourself, for cases Terraform cannot infer from any
    reference (e.g. a runtime ordering with no data flowing between them).

The result is a DIRECTED ACYCLIC GRAPH (DAG). Terraform then:
  1. topologically SORTS it (a valid build order -- every edge points "earlier"),
  2. runs nodes whose prerequisites are all done, IN PARALLEL.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
  node           : one resource block, expanded -- so `count = 3` is 3 nodes.
  edge           : a dependency arrow u -> v meaning "u must exist before v".
                   u is the DEPENDENCY, v is the DEPENDENT.
  implicit dep   : an edge inferred from an attribute reference
                   (vpc_id = aws_vpc.main.id).
  explicit dep   : an edge added by `depends_on = [...]`.
  reference      : a pointer to another resource inside an attribute value.
  topological    : a node ordering where every edge u -> v has u before v.
  sort (topo)    : producing such an order. Kahn's algorithm does it.
  wave / level   : a set of nodes runnable at the same time = all nodes whose
                   longest dependency chain has the same length. Same-wave
                   nodes have no edges between them -> they run in PARALLEL.
  count /        : HCL meta-arguments that generate N nodes from one block.
  for_each         count = N -> address[0..N-1]; for_each = toset(...) ->
                   address["key"]. Each generated node is its own graph node.
  DOT            : the graph description language `terraform graph` emits,
                   renderable with Graphviz.

KEY FACTS (all asserted in code below):
  * A reference `X.id` inside block B adds edge X -> B automatically.
  * `depends_on` adds an edge even with no reference (no data flowing).
  * `count = 3` creates THREE independent nodes (parallel where deps allow).
  * A valid topological order has every dependency BEFORE its dependent.
  * Nodes sharing a wave have NO edges among them -> safe to create in parallel.

Sources: Terraform docs -- "Resource Dependencies", "Meta-Arguments: count /
for_each / depends_on", Command: graph (developer.hashicorp.com/terraform);
Kahn's algorithm (Kahn 1962) for topological sorting.
"""

from __future__ import annotations


BANNER = "=" * 72

# ============================================================================
# 0. THE HCL MODEL -- each resource block with its references, depends_on,
#    and an optional count. Deterministic; no randomness.
# ============================================================================

# Each entry models one `resource "type" "name" { ... }` block:
#   refs        : addresses referenced inside attribute values (IMPLICIT deps)
#   depends_on  : addresses listed in depends_on (EXPLICIT deps)
#   count       : meta-argument (1 means single node, no index)
HCL_BLOCKS = [
    {"address": "aws_vpc.main", "refs": [], "depends_on": [], "count": 1},
    {"address": "aws_subnet.main",
     "refs": ["aws_vpc.main"], "depends_on": [], "count": 1},
    {"address": "aws_subnet.zone",
     "refs": ["aws_vpc.main"], "depends_on": [], "count": 3},
    {"address": "aws_security_group.app",
     "refs": ["aws_vpc.main"], "depends_on": [], "count": 1},
    {"address": "aws_iam_role.app",
     "refs": [], "depends_on": [], "count": 1},
    {"address": "aws_iam_role_policy.app",
     "refs": ["aws_iam_role.app"], "depends_on": [], "count": 1},
    {"address": "aws_instance.app",
     "refs": ["aws_subnet.main", "aws_security_group.app"],
     "depends_on": ["aws_iam_role_policy.app"], "count": 1},
    {"address": "aws_eip.app",
     "refs": ["aws_instance.app"], "depends_on": [], "count": 1},
]


# ============================================================================
# 1. GRAPH CONSTRUCTION + TOPOLOGICAL SORT + WAVES  (the code HCL_GRAPH.md walks)
# ============================================================================

def expand_blocks(blocks: list) -> list:
    """Expand count/for_each into concrete nodes. count=3 -> address[0..2]."""
    nodes = []
    for b in blocks:
        n = b["count"]
        if n == 1:
            nodes.append({"address": b["address"], "refs": list(b["refs"]),
                          "depends_on": list(b["depends_on"])})
        else:
            for i in range(n):
                # a counted node's references point at the un-indexed base,
                # which we resolve to ALL expanded instances of that target.
                nodes.append({"address": f"{b['address']}[{i}]",
                              "refs": list(b["refs"]),
                              "depends_on": list(b["depends_on"])})
    return nodes


def resolve_refs(refs: list, all_addrs: list) -> list:
    """A reference like 'aws_vpc.main' resolves to the (single) matching node.
    A reference to a counted block's base 'aws_subnet.zone' resolves to ALL its
    instances 'aws_subnet.zone[0]', '[1]', '[2]'."""
    out = []
    for r in refs:
        matches = [a for a in all_addrs if a == r or a.startswith(r + "[")]
        out.extend(matches)
    return out


def build_graph(nodes: list) -> dict:
    """Return {node_address: set_of_dependency_addresses}. Edges go from each
    dependency to this node. deps[n] = everything n needs first."""
    all_addrs = [n["address"] for n in nodes]
    deps = {}
    for n in nodes:
        implicit = set(resolve_refs(n["refs"], all_addrs))
        explicit = set(n["depends_on"])
        # explicit depends_on may also target a counted block's base
        explicit = set(resolve_refs(list(explicit), all_addrs)) | \
            {e for e in n["depends_on"] if e in all_addrs}
        deps[n["address"]] = implicit | explicit
    return deps


def topo_sort_kahn(nodes: list, deps: dict) -> list:
    """Kahn's algorithm. Deterministic: the ready set is kept sorted, so the
    output order is identical across runs and across the .html recompute."""
    addrs = [n["address"] for n in nodes]
    indeg = {a: len(deps[a]) for a in addrs}
    dependents = {a: [] for a in addrs}      # dep -> who depends on it
    for a in addrs:
        for d in deps[a]:
            dependents[d].append(a)
    ready = sorted(a for a in addrs if indeg[a] == 0)
    order = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        newly = []
        for m in dependents[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                newly.append(m)
        ready = sorted(ready + newly)
    assert len(order) == len(addrs), "graph has a cycle (not a DAG)"
    return order


def compute_waves(order: list, deps: dict) -> dict:
    """Longest-path level: wave[n] = 0 if no deps, else 1 + max(wave of deps).
    Computed in topological order so deps are always ready first."""
    wave = {}
    for n in order:
        wave[n] = 0 if not deps[n] else 1 + max(wave[d] for d in deps[n])
    return wave


def wave_groups(wave: dict) -> list:
    """Group node addresses by wave, each wave sorted."""
    if not wave:
        return []
    max_w = max(wave.values())
    return [sorted(n for n, w in wave.items() if w == lvl)
            for lvl in range(max_w + 1)]


def validate_topo_order(order: list, deps: dict) -> bool:
    """GOLD: every dependency appears BEFORE its dependent in `order`."""
    pos = {a: i for i, a in enumerate(order)}
    for n in order:
        for d in deps[n]:
            if pos[d] >= pos[n]:
                return False         # a dependency came after the dependent
    return True


def to_dot(nodes: list, deps: dict) -> str:
    """Emit a Graphviz DOT digraph (what `terraform graph` produces)."""
    lines = ["digraph G {"]
    for n in nodes:
        for d in sorted(deps[n["address"]]):
            lines.append(f'  "{d}" -> "{n["address"]}";')
    lines.append("}")
    return "\n".join(lines)


# ============================================================================
# 2. PRETTY PRINTERS
# ============================================================================

def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


# ============================================================================
# 3. THE SECTIONS
# ============================================================================

# ----------------------------------------------------------------------------
# SECTION A: The resource graph (VPC -> subnet -> sg -> instance -> EIP)
# ----------------------------------------------------------------------------

def section_graph(nodes, deps):
    banner("SECTION A: The resource DAG (refs + depends_on => edges)")
    print("Each HCL block is a node. A reference 'X.id' inside block B, or a")
    print("'depends_on = [X]', draws an edge X -> B (X must exist before B).\n")
    print("Nodes and their dependencies (the DAG edges):")
    for n in nodes:
        a = n["address"]
        ds = sorted(deps[a])
        print(f"  {a:<26} depends on {ds if ds else '{} (root)'}")
    print()
    edge_count = sum(len(deps[n["address"]]) for n in nodes)
    roots = sorted(n["address"] for n in nodes if not deps[n["address"]])
    leaves = sorted(n["address"] for n in nodes
                    if not any(n["address"] in deps[m] for m in deps))
    print(f"total nodes: {len(nodes)}   total edges: {edge_count}")
    print(f"roots (no dependencies, can start immediately): {roots}")
    print(f"leaves (nothing depends on them): {leaves}")
    print()
    print("The classic chain in this graph:")
    print("  aws_vpc.main -> aws_subnet.main / aws_security_group.app")
    print("             -> aws_instance.app -> aws_eip.app")


# ----------------------------------------------------------------------------
# SECTION B: Topological sort (creation order)  -- GOLD: order respects deps
# ----------------------------------------------------------------------------

def section_topo(nodes, deps):
    banner("SECTION B: Topological sort -- a valid creation order  (GOLD)")
    print("A topological order lists every node AFTER its dependencies. Terraform")
    print("uses it to decide what to create first. Kahn's algorithm (deterministic,\n"
          "ready-set kept sorted) produces:\n")
    order = topo_sort_kahn(nodes, deps)
    print("  creation order:")
    for i, a in enumerate(order):
        print(f"    {i + 1:>2}. {a}")
    print()
    ok = validate_topo_order(order, deps)
    print("VALIDATION: for every edge dependency -> dependent, the dependency is")
    print("listed first:")
    violations = []
    pos = {a: i for i, a in enumerate(order)}
    for n in order:
        for d in deps[n]:
            if pos[d] >= pos[n]:
                violations.append((d, n))
    if violations:
        for d, n in violations:
            print(f"  VIOLATION: {d} must precede {n} but does not")
    else:
        print("  no violations found -- every dependency precedes its dependent.")
    print()
    print("GOLD (pinned for hcl_graph.html):")
    print(f"  topological order has {len(order)} nodes, all edges respected")
    print(f"[check] topological order respects ALL dependencies?  "
          f"{'OK' if ok else 'FAIL'}")
    return order


# ----------------------------------------------------------------------------
# SECTION C: Parallel execution -- waves (same-wave nodes run concurrently)
# ----------------------------------------------------------------------------

def section_waves(order, deps):
    banner("SECTION C: Parallel execution -- waves of concurrent creation")
    print("Terraform creates nodes as soon as their dependencies finish. Grouping")
    print("nodes by 'wave' (longest dependency chain length) shows what runs in")
    print("PARALLEL: nodes in the same wave have NO edges between them.\n")
    wave = compute_waves(order, deps)
    groups = wave_groups(wave)
    for lvl, grp in enumerate(groups):
        print(f"  wave {lvl}: {grp}   ({len(grp)} node(s) in parallel)")
    print()
    print("WATCH WAVE 1: aws_subnet.zone[0..2] (the count=3 block) all sit in the")
    print("same wave as aws_subnet.main and aws_security_group.app -- none of them")
    print("depend on each other, so Terraform creates them concurrently.\n")
    # check: within each wave, no internal edges
    internal_ok = True
    for grp in groups:
        gs = set(grp)
        for a in grp:
            if any(d in gs for d in deps[a]):
                internal_ok = False
    max_parallel = max(len(g) for g in groups)
    print(f"widest wave has {max_parallel} nodes -> up to {max_parallel} concurrent")
    print("API calls. Sequential creation would take as many round-trips as nodes")
    print(f"({len(order)}); waves collapse it to {len(groups)} rounds.\n")
    print(f"[check] no intra-wave edges (each wave is a safe parallel set)?  "
          f"{'OK' if internal_ok else 'FAIL'}")
    return groups


# ----------------------------------------------------------------------------
# SECTION D: Implicit vs explicit dependencies
# ----------------------------------------------------------------------------

def section_deps(nodes, deps):
    banner("SECTION D: Implicit (refs) vs explicit (depends_on) dependencies")
    print("IMPLICIT -- inferred from an attribute reference. The instance block:")
    print('  resource "aws_instance" "app" {')
    print("    subnet_id              = aws_subnet.main.id          # <- ref")
    print("    vpc_security_group_ids = [aws_security_group.app.id] # <- ref")
    print("  }")
    print("makes Terraform draw two edges WITHOUT depends_on:")
    print("    aws_subnet.main         -> aws_instance.app")
    print("    aws_security_group.app  -> aws_instance.app\n")
    print("EXPLICIT -- added by you, for cases no reference exposes. The instance")
    print("also has:")
    print('    depends_on = [aws_iam_role_policy.app]')
    print("There is no data flowing from the policy to the instance, but the app")
    print("needs the policy attached at runtime -- so you force the edge:\n")
    print("    aws_iam_role_policy.app -> aws_instance.app   (explicit)\n")
    inst = next(n for n in nodes if n["address"] == "aws_instance.app")
    implicit = sorted(inst["refs"])
    explicit = sorted(inst["depends_on"])
    alldeps = sorted(deps["aws_instance.app"])
    print(f"aws_instance.app implicit deps : {implicit}")
    print(f"aws_instance.app explicit deps : {explicit}")
    print(f"aws_instance.app combined deps : {alldeps}\n")
    ok = (set(alldeps) == set(implicit) | set(explicit))
    print("KEY POINT: an edge is an edge. Once built, Terraform treats implicit")
    print("and explicit dependencies identically for ordering -- both must be")
    print("satisfied before the node runs. depends_on is the escape hatch for")
    print("ordering that no reference can express.\n")
    print(f"[check] combined deps == implicit | explicit for aws_instance.app?  "
          f"{'OK' if ok else 'FAIL'}")


# ----------------------------------------------------------------------------
# SECTION E: count / for_each -- one block, many graph nodes
# ----------------------------------------------------------------------------

def section_count():
    banner("SECTION E: count / for_each -- generate N separate nodes")
    print("The meta-argument 'count = 3' generates three resources from one block:")
    print('  resource "aws_subnet" "zone" {')
    print("    count       = 3")
    print("    vpc_id      = aws_vpc.main.id")
    print("    cidr_block  = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)")
    print("  }")
    print("Expands to THREE nodes in the graph, each a distinct address:\n")
    zones = [n for n in expand_blocks(HCL_BLOCKS) if n["address"].startswith("aws_subnet.zone")]
    for z in zones:
        print(f"  {z['address']}   refs -> {z['refs']}")
    print()
    all_nodes = expand_blocks(HCL_BLOCKS)
    deps = build_graph(all_nodes)
    order = topo_sort_kahn(all_nodes, deps)
    wave = compute_waves(order, deps)
    print("Each aws_subnet.zone[i] depends on aws_vpc.main (its vpc_id ref), and")
    print("NOTHING else -- they are siblings with no edges among them:\n")
    for z in zones:
        print(f"  {z['address']}: depends on {sorted(deps[z['address']])} ; "
              f"wave {wave[z['address']]}")
    print()
    print("So all three land in the SAME wave and Terraform creates them in")
    print("parallel. 'for_each' works identically: each map key becomes a node")
    print('with an indexed address like aws_subnet.zone["a"].')
    ok = (len(zones) == 3
          and all(deps[z["address"]] == {"aws_vpc.main"} for z in zones)
          and len({wave[z["address"]] for z in zones}) == 1)
    print(f"[check] count=3 made 3 independent sibling nodes (same wave)?  "
          f"{'OK' if ok else 'FAIL'}")


# ============================================================================
# main
# ============================================================================

def main():
    print("hcl_graph.py - reference simulation.")
    print("All output below feeds HCL_GRAPH.md.")
    print("stdlib only; deterministic.")

    nodes = expand_blocks(HCL_BLOCKS)
    deps = build_graph(nodes)

    section_graph(nodes, deps)
    order = section_topo(nodes, deps)
    section_waves(order, deps)
    section_deps(nodes, deps)
    section_count()

    # show `terraform graph` DOT output (appendix)
    banner("APPENDIX: `terraform graph` -> DOT (render with Graphviz)")
    print(to_dot(nodes, deps))

    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
