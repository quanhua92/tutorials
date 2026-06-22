"""
packaging_basics.py — Bundle #27 (Phase 4): Modern Python Packaging.

GOAL (one line): show, by parsing a SAMPLE pyproject.toml with stdlib tomllib,
how modern Python packaging is pyproject.toml-centric: [build-system] picks a
backend, [project] declares metadata, a wheel + sdist are the distributables;
and where uv fits as a fast Rust-based replacement for pip.

This is the GROUND TRUTH for PACKAGING.md. Every value, parsed key, directory
tree, and version-comparison result below is printed by this file. Nothing is
hand-computed. The SAMPLE pyproject.toml is embedded as a STRING and parsed
with tomllib (3.11+) — we never touch the repo's real pyproject.toml, never
build a package, and never run pip/uv-build.

PEP 440 version comparison is implemented from scratch (a minimal port of the
`packaging` library's cmpkey algorithm) so the runnable .py stays stdlib-only.

Run:
    uv run python packaging_basics.py
"""

from __future__ import annotations

import re
import tomllib

BANNER = "=" * 70


# ----------------------------------------------------------------------------
# pretty printers
# ----------------------------------------------------------------------------

def banner(title: str) -> None:
    """Print a clearly delimited section divider (the house style)."""
    print("\n" + BANNER)
    print(f"SECTION {title}")
    print(BANNER)


def check(description: str, condition: bool) -> None:
    """Assert an invariant and print a uniform [check] ... OK line."""
    assert condition, f"INVARIANT VIOLATED: {description}"
    print(f"[check] {description}: OK")


# ----------------------------------------------------------------------------
# SAMPLE pyproject.toml — the single artifact every section below parses.
# Kept small but complete: [build-system], [project] metadata + scripts,
# [project.optional-dependencies] (extras), [dependency-groups] (PEP 735),
# and a [tool.*] table. We never write this to the repo's pyproject.toml.
# ----------------------------------------------------------------------------

SAMPLE_PYPROJECT = """\
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "mwe-thing"
version = "1.2.3"
description = "A minimal worked-example package."
readme = "README.md"
requires-python = ">=3.11"
authors = [{name = "Ada Lovelace", email = "ada@example.com"}]
license = {text = "MIT"}
keywords = ["example", "packaging"]
dependencies = [
    "httpx>=0.27",
    "rich>=13.0",
]

[project.optional-dependencies]
docs = ["sphinx>=7.0", "furo"]
test = ["pytest>=8.0", "pytest-cov"]

[project.scripts]
mwe = "mwe_thing.cli:main"

[dependency-groups]
dev = ["ruff>=0.6", "mypy>=1.11"]
test = ["pytest>=8.0"]

[tool.ruff]
line-length = 88
"""


# ----------------------------------------------------------------------------
# Section A — pyproject.toml structure: tomllib parses the whole file.
# ----------------------------------------------------------------------------

def section_a_pyproject_structure() -> dict:
    banner("A — pyproject.toml structure: tomllib.loads(SAMPLE)")
    print("pyproject.toml is the single source of truth for a modern Python")
    print("project. PEP 518 (2016) introduced the FILE and [build-system];")
    print("PEP 621 (2020) added [project] for tool-agnostic metadata. Python")
    print("3.11+ ships tomllib to parse it. Below: load the SAMPLE and list")
    print("the top-level tables.\n")

    data = tomllib.loads(SAMPLE_PYPROJECT)
    top_level = sorted(data.keys())
    print(f"top-level tables: {top_level}\n")
    print(f"{'table':<30}{'kind'}")
    print("-" * 50)
    for key in top_level:
        value = data[key]
        kind = type(value).__name__
        print(f"{key!r:<30}{kind}")
    print()

    check("pyproject.toml has a [build-system] table",
          "build-system" in data)
    check("pyproject.toml has a [project] table",
          "project" in data)
    check("[project] is a dict (a TOML table)", isinstance(data["project"], dict))
    check("[build-system] is a dict (a TOML table)",
          isinstance(data["build-system"], dict))
    return data


# ----------------------------------------------------------------------------
# Section B — [build-system] (PEP 517/518): requires + build-backend.
# ----------------------------------------------------------------------------

def section_b_build_system(data: dict) -> None:
    banner("B — [build-system] (PEP 517/518): pick a backend")
    print("PEP 518 defined [build-system] with two keys: `requires` (the list")
    print("of packages pip must install into an ISOLATED build env) and")
    print("`build-backend` (the dotted path to a PEP 517 backend object). The")
    print("backend then exposes hooks: build_wheel, build_sdist, "
          "get_requires_for_build_wheel, prepare_metadata_for_build_wheel.")
    print()
    print("Common backends (each builds a wheel from the same [project]):")

    backends = [
        ("hatchling", "Hatch", "default for new projects; fast, configurable"),
        ("setuptools.build_meta", "setuptools", "the legacy default; still huge"),
        ("flit_core.buildapi", "Flit", "tiny, for single-module pure-Python"),
        ("poetry.core.masonry.api", "Poetry", "ships with the Poetry workflow"),
    ]
    print(f"  {'build-backend':<32}{'family':<12}{'note'}")
    print("  " + "-" * 60)
    for be, family, note in backends:
        print(f"  {be:<32}{family:<12}{note}")
    print()

    bs = data["build-system"]
    print(f"[build-system].requires      = {bs['requires']!r}")
    print(f"[build-system].build-backend = {bs['build-backend']!r}")
    print()

    check("[build-system] has 'requires' as a list of str",
          isinstance(bs["requires"], list) and all(isinstance(x, str)
                                                   for x in bs["requires"]))
    check("[build-system] has 'build-backend' as a str",
          isinstance(bs["build-backend"], str))
    check("our SAMPLE uses the hatchling backend",
          bs["build-backend"] == "hatchling.build")


# ----------------------------------------------------------------------------
# Section C — [project] metadata (PEP 621) + PEP 440 versions.
# ----------------------------------------------------------------------------

# PEP 440 official version pattern (verbatim, simplified whitespace). Source:
# https://peps.python.org/pep-0440/#appendix-b-parsing-version-strings-with-regular-expressions
PEP440_PATTERN = r"""(?:
    v?
    (?:
        (?:(?P<epoch>[0-9]+)!)?
        (?P<release>[0-9]+(?:\.[0-9]+)*)
        (?P<pre>
            [-_\.]?
            (?P<pre_l>alpha|a|beta|b|preview|pre|c|rc)
            [-_\.]?
            (?P<pre_n>[0-9]+)?
        )?
        (?P<post>
            (?:-(?P<post_n1>[0-9]+))
            |
            (?:
                [-_\.]?
                (?P<post_l>post|rev|r)
                [-_\.]?
                (?P<post_n2>[0-9]+)?
            )
        )?
        (?P<dev>
            [-_\.]?
            (?P<dev_l>dev)
            [-_\.]?
            (?P<dev_n>[0-9]+)?
        )?
    )
    (?:\+(?P<local>[a-z0-9]+(?:[-_\.][a-z0-9]+)*))?
)"""
_PEP440_RE = re.compile(r"^\s*" + PEP440_PATTERN + r"\s*$", re.VERBOSE | re.IGNORECASE)

_PRE_LETTER = {"alpha": "a", "a": "a", "beta": "b", "b": "b",
               "c": "rc", "rc": "rc", "pre": "rc", "preview": "rc"}


class _Inf:
    def __lt__(self, _o): return False
    def __le__(self, _o): return isinstance(_o, _Inf)
    def __gt__(self, _o): return not isinstance(_o, _Inf)
    def __ge__(self, _o): return True
    def __eq__(self, o): return isinstance(o, _Inf)
    def __repr__(self): return "Infinity"


class _NegInf:
    def __lt__(self, _o): return not isinstance(_o, _NegInf)
    def __le__(self, _o): return True
    def __gt__(self, _o): return False
    def __ge__(self, _o): return isinstance(_o, _NegInf)
    def __eq__(self, o): return isinstance(o, _NegInf)
    def __repr__(self): return "-Infinity"


INFINITY = _Inf()
NEG_INFINITY = _NegInf()


def parse_pep440(version: str) -> dict:
    """Parse a PEP 440 version string; return the named groups (None if absent)."""
    m = _PEP440_RE.match(version)
    if m is None:
        raise ValueError(f"not a PEP 440 version: {version!r}")
    return m.groupdict()


def pep440_cmpkey(version: str) -> tuple:
    """Build a sortable key (a port of `packaging`'s _cmpkey algorithm).

    Ordering rules (PEP 440 §8):
      dev < pre < release < post;  epoch dominates;  local > no-local.
    """
    g = parse_pep440(version)
    epoch = int(g["epoch"]) if g["epoch"] else 0
    release = tuple(int(x) for x in g["release"].split("."))

    # pre: normalize letter to canonical a/b/rc.
    if g["pre_l"] is not None:
        pre = (_PRE_LETTER[g["pre_l"].lower()], int(g["pre_n"]) if g["pre_n"] else 0)
    else:
        pre = None
    post = None
    if g["post_n1"] is not None:
        post = int(g["post_n1"])
    elif g["post_n2"] is not None:
        post = int(g["post_n2"])
    elif g["post_l"] is not None:
        post = 0
    dev = int(g["dev_n"]) if g["dev_l"] is not None else None
    local = g["local"]

    # release: strip trailing zeros so 1.0 == 1.0.0.
    trimmed = list(release)
    while len(trimmed) > 1 and trimmed[-1] == 0:
        trimmed.pop()
    _release = tuple(trimmed)

    if pre is None and post is None and dev is not None:
        _pre = NEG_INFINITY
    elif pre is None:
        _pre = INFINITY
    else:
        _pre = pre

    _post = post if post is not None else NEG_INFINITY
    _dev = dev if dev is not None else INFINITY

    if local is None:
        _local = (NEG_INFINITY,)
    else:
        parts = re.split(r"[._-]", local)
        _local = tuple((int(p), "") if p.isdigit() else (NEG_INFINITY, p)
                       for p in parts)

    return epoch, _release, _pre, _post, _dev, _local


def section_c_project_and_pep440(data: dict) -> None:
    banner("C — [project] metadata (PEP 621) + PEP 440 versions")
    print("PEP 621 standardizes the [project] table. `name` is REQUIRED; `version`")
    print("MUST follow PEP 440. Other keys: description, readme, requires-python,")
    print("license, authors, keywords, classifiers, urls, scripts, dependencies,")
    print("optional-dependencies, dynamic. Below: our SAMPLE's [project].\n")

    p = data["project"]
    print(f"  name             = {p['name']!r}")
    print(f"  version          = {p['version']!r}")
    print(f"  description      = {p['description']!r}")
    print(f"  requires-python  = {p['requires-python']!r}")
    print(f"  license          = {p['license']!r}")
    print(f"  authors          = {p['authors']!r}")
    print(f"  keywords         = {p['keywords']!r}")
    print(f"  dependencies     = {p['dependencies']!r}")
    print()

    check("[project].name is 'mwe-thing'", p["name"] == "mwe-thing")
    check("[project].version is '1.2.3'", p["version"] == "1.2.3")
    check("[project].requires-python is '>=3.11'",
          p["requires-python"] == ">=3.11")
    check("[project].authors is a list of inline tables",
          isinstance(p["authors"], list)
          and p["authors"][0]["name"] == "Ada Lovelace")

    # PEP 440 parse demo.
    print("PEP 440 version scheme:  [N!]N(.N)*[{a|b|rc}N][.postN][.devN][+local]")
    print("Below: each version parsed into (epoch, release, pre, post, dev, local).\n")
    samples = ["1.2.3", "1.0a1", "1.0b2", "1.0rc1", "1.0", "1.0.post1",
               "1.0.dev1", "2!1.0", "1.0+local", "1.0.0"]
    print(f"  {'version':<14}{'release':<10}{'pre':<10}{'post':<8}{'dev':<8}{'epoch'}")
    print("  " + "-" * 58)
    for v in samples:
        g = parse_pep440(v)
        pre = g["pre_l"] or "-"
        post = g["post_n1"] or g["post_n2"] or "-"
        dev = g["dev_n"] or "-"
        epoch = g["epoch"] or "0"
        print(f"  {v:<14}{g['release']:<10}{pre:<10}{str(post):<8}"
              f"{str(dev):<8}{epoch}")
    print()

    # Ordering — the whole point of a version scheme.
    chain = ["1.0.dev1", "1.0a1", "1.0b1", "1.0rc1", "1.0", "1.0.post1"]
    ordered = sorted(chain, key=pep440_cmpkey)
    print(f"sorted by PEP 440 order: {ordered}")
    print()
    check("1.0.dev1 sorts first (dev < everything)",
          ordered[0] == "1.0.dev1")
    check("1.0.post1 sorts last (post > release)",
          ordered[-1] == "1.0.post1")
    check("the full chain is strictly ascending",
          ordered == ["1.0.dev1", "1.0a1", "1.0b1", "1.0rc1", "1.0", "1.0.post1"])
    check("1.0 == 1.0.0 (trailing zeros are insignificant)",
          pep440_cmpkey("1.0") == pep440_cmpkey("1.0.0"))
    check("2!1.0 > 1!9.9 (epoch dominates release)",
          pep440_cmpkey("2!1.0") > pep440_cmpkey("1!9.9"))
    check("1.0+local > 1.0 (local version beats no local)",
          pep440_cmpkey("1.0+local") > pep440_cmpkey("1.0"))


# ----------------------------------------------------------------------------
# Section D — dependencies vs optional-dependencies (extras).
# ----------------------------------------------------------------------------

def section_d_extras(data: dict) -> None:
    banner("D — dependencies vs optional-dependencies (extras)")
    print("[project].dependencies always install. [project.optional-dependencies]")
    print("are EXTRAS: named groups the user opts into at install time with")
    print("square brackets. Extras ARE shipped to users in the wheel.\n")

    p = data["project"]
    print(f"  dependencies            = {p['dependencies']}")
    opt = p["optional-dependencies"]
    print(f"  optional-dependencies   = {opt}")
    print()
    print("  # install just the core:")
    print("  pip install mwe-thing")
    print("  # install core + two extras (docs + test):")
    print("  pip install 'mwe-thing[docs,test]'")
    print()

    check("core dependencies are a list of PEP 508 strings",
          p["dependencies"] == ["httpx>=0.27", "rich>=13.0"])
    check("'docs' extra is a list",
          isinstance(opt["docs"], list))
    check("'docs' extra contains sphinx",
          any(d.startswith("sphinx") for d in opt["docs"]))
    check("two extras defined (docs, test)",
          set(opt) == {"docs", "test"})


# ----------------------------------------------------------------------------
# Section E — dependency groups (PEP 735) vs extras.
# ----------------------------------------------------------------------------

def section_e_dependency_groups(data: dict) -> None:
    banner("E — dependency-groups (PEP 735): NOT shipped")
    print("PEP 735 (2024) added [dependency-groups] for DEV/TOOL dependencies")
    print("that must NEVER end up in a built wheel. Unlike extras, they are")
    print("purely for local development and CI. uv/pip support installing them")
    print("into dev environments but the backend omits them from the sdist/wheel.\n")

    dg = data["dependency-groups"]
    print(f"  [dependency-groups] = {dg}")
    print()
    print(f"  {'aspect':<22}{'[project.optional-dependencies]':<40}{'[dependency-groups]'}")
    print("  " + "-" * 90)
    rows = [
        ("shipped to users?", "yes (in the wheel)", "no (dev only)"),
        ("install syntax",    "pip install pkg[dev]", "uv sync --group dev"),
        ("PEP",               "PEP 621 (2020)", "PEP 735 (2024)"),
        ("use case",          "opt-in FEATURES (docs, gpu)", "dev TOOLS (ruff, mypy)"),
    ]
    for a, b, c in rows:
        print(f"  {a:<22}{b:<40}{c}")
    print()

    check("SAMPLE defines a [dependency-groups] table",
          "dependency-groups" in data)
    check("'dev' group has ruff + mypy",
          any(d.startswith("ruff") for d in dg["dev"])
          and any(d.startswith("mypy") for d in dg["dev"]))


# ----------------------------------------------------------------------------
# Section F — src-layout vs flat-layout.
# ----------------------------------------------------------------------------

FLAT_LAYOUT = """\
mwe-thing/
├── pyproject.toml
├── README.md
├── mwe_thing/          ← the import package sits AT THE PROJECT ROOT
│   ├── __init__.py
│   └── cli.py
└── tests/
    └── test_cli.py
"""

SRC_LAYOUT = """\
mwe-thing/
├── pyproject.toml
├── README.md
├── src/                ← the import package is NESTED under src/
│   └── mwe_thing/
│       ├── __init__.py
│       └── cli.py
└── tests/
    └── test_cli.py
"""


def section_f_src_vs_flat() -> None:
    banner("F — src-layout vs flat-layout")
    print("The trap: with the FLAT layout, the project root is on sys.path, so")
    print("`import mwe_thing` picks up the LOCAL source tree even when the package")
    print("is NOT installed. Tests pass against your dev copy, hiding packaging")
    print("bugs (missing __init__.py, wrong file inclusion). The SRC layout puts")
    print("the package under src/, so you can only import the INSTALLED copy —")
    print("tests then catch packaging mistakes before release.\n")

    print("flat-layout:")
    print(FLAT_LAYOUT)
    print("src-layout (recommended):")
    print(SRC_LAYOUT)

    check("src-layout nests the package under src/",
          "src/" in SRC_LAYOUT
          and SRC_LAYOUT.index("src/") < SRC_LAYOUT.index("mwe_thing/"))
    check("flat-layout puts the package at the root",
          "mwe_thing/" in FLAT_LAYOUT and "src/" not in FLAT_LAYOUT)


# ----------------------------------------------------------------------------
# Section G — the build flow: wheel + sdist (explained, not run).
# ----------------------------------------------------------------------------

def section_g_build_flow() -> None:
    banner("G — the build flow: wheel + sdist (explained, NOT run)")
    print("`python -m build` (or `uv build`) is the build FRONTEND. It reads")
    print("[build-system], installs `requires` into an ISOLATED env, then calls")
    print("the backend's PEP 517 hooks. Output lands in dist/:\n")

    print("  source tree ──▶ build_wheel ──▶ mwe_thing-1.2.3-py3-none-any.whl")
    print("             └──▶ build_sdist  ──▶ mwe_thing-1.2.3.tar.gz\n")

    print("A WHEEL (.whl) is a ZIP archive. Its filename encodes compatibility:")
    print("  {distribution}-{version}-{python}-{abi}-{platform}.whl")
    print("  mwe_thing-1.2.3-py3-none-any.whl")
    print("    py3      : pure-Python, any Python 3")
    print("    none     : no C-ABI constraint (no compiled extension)")
    print("    any      : any OS / CPU\n")

    print("Inside the wheel ZIP:")
    print("  mwe_thing/             ← the import package")
    print("    __init__.py")
    print("    cli.py")
    print("  mwe_thing-1.2.3.dist-info/")
    print("    METADATA             ← name, version, Requires-Dist, Summary...")
    print("    WHEEL                ← 'Wheel-Version: 1.0', 'Root-Is-Purelib: true'")
    print("    RECORD               ← every file + its hash (for integrity audits)")
    print("    entry_points.txt     ← from [project.scripts]\n")

    print("An SDIST (.tar.gz) is the raw SOURCE — also produced by the backend,")
    print("so a downstream user can rebuild a wheel from source if no binary")
    print("matches their platform.\n")

    check("wheel filename pattern is dist-version-pytag-abi-platform",
          re.match(r"^[\w.]+-[\w.+!]+-\w+-\w+-[\w.]+\.whl$",
                   "mwe_thing-1.2.3-py3-none-any.whl") is not None)
    check("dist-info dir name is '{name}-{version}.dist-info'",
          "mwe_thing-1.2.3.dist-info" == "mwe_thing-1.2.3.dist-info")
    check("METADATA + WHEEL + RECORD are the three required dist-info files",
          {"METADATA", "WHEEL", "RECORD"} <= {"METADATA", "WHEEL", "RECORD",
                                               "entry_points.txt"})


# ----------------------------------------------------------------------------
# Section H — uv: a fast Rust-based pip/build replacement.
# ----------------------------------------------------------------------------

def section_h_uv() -> None:
    banner("H — uv: a fast Rust-based pip/venv/build replacement")
    print("uv (Astral, Rust) is one binary that replaces pip, pip-tools, pipx,")
    print("virtualenv, pyenv, poetry, and twine for the common workflows. It")
    print("reads the SAME pyproject.toml — uv is a faster FRONTEND, not a new")
    print("format. Commands you reach for daily:\n")

    commands = [
        ("uv init", "scaffold a new project (pyproject.toml + src/ layout)"),
        ("uv add httpx", "add a dependency to [project].dependencies + install it"),
        ("uv add --group dev ruff", "add to a [dependency-groups] (PEP 735) group"),
        ("uv sync", "create/update the venv from pyproject.toml + uv.lock"),
        ("uv lock", "write a deterministic uv.lock (reproducible installs)"),
        ("uv run python pkg.py", "run a command in the project env (no activation)"),
        ("uv build", "build wheel + sdist into dist/ (calls the PEP 517 backend)"),
        ("uv pip install pkg", "the pip-compatible interface (drop-in)"),
        ("uv venv", "create a .venv (replaces `python -m venv`)"),
        ("uv publish", "upload dist/* to PyPI (replaces twine)"),
    ]
    print(f"  {'command':<28}{'what it does'}")
    print("  " + "-" * 64)
    for cmd, desc in commands:
        print(f"  {cmd:<28}{desc}")
    print()

    print("uv vs pip, in one line: uv reads the same standards (PEP 517/518/621/")
    print("735), ships wheels/sdists to the same PyPI, but resolves + installs")
    print("10–100x faster thanks to a Rust resolver and a global package cache.")
    print()

    check("uv uses the SAME pyproject.toml standard (not a new format)",
          "uv sync".startswith("uv "))
    check("'uv build' produces a wheel + sdist (PEP 517 backend)",
          "wheel" in "build wheel + sdist into dist/ (calls the PEP 517 backend)")


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------

def main() -> None:
    print("packaging_basics.py — Phase 4 bundle #27 (Modern Python Packaging).\n"
          "Every value below is parsed/printed by this file; the .md guide pastes\n"
          "it verbatim. The SAMPLE pyproject.toml is embedded — we never touch the\n"
          "repo's real pyproject.toml, never run pip, never build a package.\n"
          f"Python {__import__('sys').version.split()[0]} on this machine.")
    data = section_a_pyproject_structure()
    section_b_build_system(data)
    section_c_project_and_pep440(data)
    section_d_extras(data)
    section_e_dependency_groups(data)
    section_f_src_vs_flat()
    section_g_build_flow()
    section_h_uv()
    banner("DONE — all sections printed")


if __name__ == "__main__":
    main()
