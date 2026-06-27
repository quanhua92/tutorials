#!/usr/bin/env python3
"""UML Class Diagrams -- class structure, relationships, multiplicity.

Ground-truth UML model + ASCII/Mermaid renderer. Pure Python stdlib.

What this demonstrates:
  * Class anatomy -- three compartments (name, attributes, methods),
    visibility modifiers (+ public, - private, # protected, ~ package),
    static ({static}) and abstract (*) member markers, and the
    <<interface>> / <<abstract>> stereotypes.
  * The six relationship types -- inheritance, realization, composition,
    aggregation, association, dependency -- each with its UML glyph,
    Mermaid syntax, arrow direction, and a concrete example.
  * Multiplicity at both ends of every relationship (1, 0..1, *, 1..*, n..m).
  * An ASCII three-compartment class-box renderer.
  * A Mermaid classDiagram source generator (arrow direction handled per type).
  * A coupling score (relationship-strength weighted) + structural validation.
  * Two worked systems: Parking Lot and Library Management.

Companion files: UML_CLASS_DIAGRAMS.md, uml_class_diagrams.html
"""

# --------------------------------------------------------------------------- #
#  Visibility modifiers
# --------------------------------------------------------------------------- #
PUBLIC, PRIVATE, PROTECTED, PACKAGE = "+", "-", "#", "~"
VISIBILITY_NAMES = {
    PUBLIC: "public", PRIVATE: "private",
    PROTECTED: "protected", PACKAGE: "package",
}


# --------------------------------------------------------------------------- #
#  Members
# --------------------------------------------------------------------------- #
class Attribute:
    """A field: visibility + name: type, optionally {static}."""

    def __init__(self, name, type_, visibility=PRIVATE, is_static=False):
        self.name = name
        self.type = type_
        self.visibility = visibility
        self.is_static = is_static

    def render(self):
        s = f"{self.visibility} {self.name}: {self.type}"
        if self.is_static:
            s += " {static}"
        return s


class Method:
    """An operation: visibility + name(params): ReturnType, optionally * / {static}."""

    def __init__(self, name, params=None, return_type="void",
                 visibility=PUBLIC, is_static=False, is_abstract=False):
        self.name = name
        self.params = params or []           # list of (name, type)
        self.return_type = return_type
        self.visibility = visibility
        self.is_static = is_static
        self.is_abstract = is_abstract

    def render(self):
        params = ", ".join(f"{n}: {t}" for n, t in self.params)
        s = f"{self.visibility} {self.name}({params}): {self.return_type}"
        if self.is_abstract:
            s += "*"                          # Mermaid abstract marker
        if self.is_static:
            s += " {static}"
        return s


# --------------------------------------------------------------------------- #
#  Class box
# --------------------------------------------------------------------------- #
class UMLClass:
    """A UML class with optional stereotype: None | 'interface' | 'abstract'."""

    def __init__(self, name, stereotype=None, attributes=None, methods=None):
        self.name = name
        self.stereotype = stereotype
        self.attributes = attributes or []
        self.methods = methods or []

    @property
    def is_interface(self):
        return self.stereotype == "interface"

    @property
    def is_abstract(self):
        return self.stereotype == "abstract"


# --------------------------------------------------------------------------- #
#  Relationships
# --------------------------------------------------------------------------- #
# type -> (mermaid operator, coupling strength 1..5, plain-english semantics)
REL_META = {
    "inheritance": {"mermaid": "<|--", "strength": 5,
                    "glyph": "--<", "desc": "child IS-A parent (extends a concrete class)"},
    "realization": {"mermaid": "<|..", "strength": 4,
                    "glyph": "..<", "desc": "class implements an <<interface>> contract"},
    "composition": {"mermaid": "*--",  "strength": 5,
                    "glyph": "*--", "desc": "part dies with whole (lifetime ownership)"},
    "aggregation": {"mermaid": "o--",  "strength": 3,
                    "glyph": "o--", "desc": "part outlives whole (loose has-a)"},
    "association": {"mermaid": "-->",  "strength": 2,
                    "glyph": "-->", "desc": "persistent reference between independent peers"},
    "dependency":  {"mermaid": "..>",  "strength": 1,
                    "glyph": "..>", "desc": "transient use (method param / local variable)"},
}
# Canonical order used for the gold-check signature.
REL_ORDER = ["inheritance", "realization", "composition",
             "aggregation", "association", "dependency"]


class Relationship:
    """One edge between two classes.

    For inheritance / realization `source` is the CHILD / IMPLEMENTOR and
    `target` is the PARENT / INTERFACE (the arrow points source -> target).
    For composition / aggregation `source` is the OWNER (diamond side).
    For association / dependency `source` is the CALLER that holds/uses target.
    """

    def __init__(self, source, target, rel_type,
                 source_mult="1", target_mult="1", label=None):
        if rel_type not in REL_META:
            raise ValueError(f"unknown relationship type: {rel_type}")
        self.source = source
        self.target = target
        self.rel_type = rel_type
        self.source_mult = source_mult
        self.target_mult = target_mult
        self.label = label


def mermaid_relationship(rel):
    """Render ONE relationship line in Mermaid classDiagram syntax.

    Inheritance / realization flip source<->target because the hollow
    triangle sits on the parent/interface side: `Parent <|-- Child`.
    """
    op = REL_META[rel.rel_type]["mermaid"]
    if rel.rel_type in ("inheritance", "realization"):
        line = f"{rel.target} {op} {rel.source}"          # Parent <|-- Child
    else:
        sm, tm = f'"{rel.source_mult}"', f'"{rel.target_mult}"'
        line = f"{rel.source} {sm} {op} {tm} {rel.target}"
    if rel.label:
        line += f" : {rel.label}"
    return line


# --------------------------------------------------------------------------- #
#  Diagram container
# --------------------------------------------------------------------------- #
class UMLDiagram:
    def __init__(self, name=""):
        self.name = name
        self.classes = {}                  # name -> UMLClass
        self.relationships = []

    def add_class(self, cls):
        self.classes[cls.name] = cls
        return cls

    def add_relationship(self, rel):
        for n in (rel.source, rel.target):
            if n not in self.classes:
                raise ValueError(f"relationship references unknown class: {n}")
        self.relationships.append(rel)
        return rel

    def counts(self):
        c = {k: 0 for k in REL_ORDER}
        for r in self.relationships:
            c[r.rel_type] += 1
        return c

    def signature(self):
        """Per-type counts in canonical order, comma-joined (no spaces)."""
        c = self.counts()
        return ",".join(str(c[k]) for k in REL_ORDER)

    def coupling_score(self):
        return sum(REL_META[r.rel_type]["strength"] for r in self.relationships)

    def coupling_density(self):
        return self.coupling_score() / max(1, len(self.classes))

    def mermaid(self):
        lines = ["classDiagram"]
        for rel in self.relationships:
            lines.append("    " + mermaid_relationship(rel))
        for cls in self.classes.values():
            lines += _mermaid_class_block(cls)
        return "\n".join(lines)

    def validate(self):
        issues = []
        for r in self.relationships:
            tgt = self.classes.get(r.target)
            src = self.classes.get(r.source)
            if r.rel_type == "realization" and tgt and not tgt.is_interface:
                issues.append(
                    f"  ! {r.source} realizes {r.target}, but {r.target} "
                    f"lacks the <<interface>> stereotype")
            if r.rel_type in ("inheritance", "realization") and r.source == r.target:
                issues.append(f"  ! self-{r.rel_type}: {r.source}")
            if r.rel_type == "dependency" and src and tgt:
                # dependency target used only transiently -- informational
                pass
        for c in self.classes.values():
            if c.is_abstract and not any(m.is_abstract for m in c.methods):
                issues.append(
                    f"  ! {c.name} is <<abstract>> but declares no abstract method (*)")
        return issues


def _mermaid_class_block(cls):
    body = []
    if cls.stereotype:
        body.append(f"    class {cls.name} {{")
        body.append(f"        <<{cls.stereotype}>>")
    else:
        body.append(f"    class {cls.name} {{")
    for a in cls.attributes:
        body.append("        " + _mermaid_attr(a))
    for m in cls.methods:
        body.append("        " + _mermaid_method(m))
    body.append("    }")
    return body


def _mermaid_attr(a):
    s = f"{a.visibility}{a.name}: {a.type}"
    if a.is_static:
        s += "$"
    return s


def _mermaid_method(m):
    params = ",".join(f"{n}: {t}" for n, t in m.params)
    s = f"{m.visibility}{m.name}({params}) {m.return_type}"
    if m.is_abstract:
        s += "*"
    if m.is_static:
        s += "$"
    return s


# --------------------------------------------------------------------------- #
#  ASCII three-compartment class-box renderer
# --------------------------------------------------------------------------- #
def _center(s, w):
    if len(s) >= w:
        return s
    left = (w - len(s)) // 2
    return " " * left + s + " " * (w - len(s) - left)


def render_class_box(cls, indent="  "):
    """Return ASCII lines for a three-compartment UML class box."""
    name_comp = []
    if cls.stereotype:
        name_comp.append(f"<<{cls.stereotype}>>")
    name_comp.append(cls.name)
    attr_comp = [a.render() for a in cls.attributes]
    method_comp = [m.render() for m in cls.methods]

    pad = max([len(x) for x in name_comp + attr_comp + method_comp]
              + [len(cls.name) + 4])
    top = "+" + "-" * (pad + 2) + "+"
    bot = "+" + "-" * (pad + 2) + "+"
    sep = "+" + "-" * (pad + 2) + "+"
    out = [top]
    for ln in name_comp:                    # name compartment: centered
        out.append("| " + _center(ln, pad) + " |")
    out.append(sep)
    for ln in (attr_comp or [""]):          # attribute compartment: left
        out.append("| " + (ln.ljust(pad) if ln else " " * pad) + " |")
    out.append(sep)
    for ln in (method_comp or [""]):        # method compartment: left
        out.append("| " + (ln.ljust(pad) if ln else " " * pad) + " |")
    out.append(bot)
    return [indent + x for x in out]


# --------------------------------------------------------------------------- #
#  Pretty-printer
# --------------------------------------------------------------------------- #
def banner(title):
    line = "=" * 78
    print(f"\n{line}\n{title}\n{line}")


# --------------------------------------------------------------------------- #
#  Demo sections
# --------------------------------------------------------------------------- #
def section_class_anatomy():
    banner("CLASS ANATOMY -- compartments, visibility, static & abstract")

    account = UMLClass(
        "BankAccount",
        attributes=[
            Attribute("accountId", "UUID", PRIVATE),
            Attribute("balance", "Decimal", PROTECTED),
            Attribute("tag", "String", PACKAGE),
            Attribute("routingCode", "String", PUBLIC, is_static=True),
        ],
        methods=[
            Method("deposit", [("amount", "Decimal")], "void", PUBLIC),
            Method("withdraw", [("amount", "Decimal")], "Boolean", PUBLIC),
            Method("reconcile", [], "void", PRIVATE),
            Method("formatIban", [("raw", "String")], "String", PUBLIC,
                   is_static=True),
        ],
    )
    print("\n  Concrete class -- all four visibility modifiers + a static member:")
    for ln in render_class_box(account):
        print(ln)

    processor = UMLClass(
        "PaymentProcessor", stereotype="interface",
        methods=[Method("charge", [("amount", "Money")], "Boolean",
                        is_abstract=True)],
    )
    print("\n  Interface -- <<interface>> stereotype, all methods implicitly abstract:")
    for ln in render_class_box(processor):
        print(ln)

    vehicle = UMLClass(
        "Vehicle", stereotype="abstract",
        attributes=[
            Attribute("licensePlate", "String", PROTECTED),
            Attribute("size", "VehicleSize", PROTECTED),
        ],
        methods=[
            Method("start", [], "void", PUBLIC, is_abstract=True),
            Method("stop", [], "void", PUBLIC),
        ],
    )
    print("\n  Abstract class -- shared state + at least one abstract method (*):")
    for ln in render_class_box(vehicle):
        print(ln)

    print("""
  Visibility:   + public    - private    # protected    ~ package
  Suffixes:     *  abstract method (class must be <<abstract>>)
                $  static member  (Mermaid; shown as {static} in ASCII)
  Stereotypes:  <<interface>>  pure contract, no fields
                <<abstract>>   may hold fields + concrete + abstract methods""")


def section_relationships():
    banner("THE SIX RELATIONSHIP TYPES -- glyph, mermaid, direction, example")

    samples = [
        ("inheritance", "Square", "Shape", "Square IS-A Shape"),
        ("realization", "StripeProcessor", "PaymentProcessor",
         "StripeProcessor implements the contract"),
        ("composition", "Order", "OrderItem",
         "delete the Order -> the OrderItems die"),
        ("aggregation", "Library", "Book",
         "close the Library -> the Books still exist"),
        ("association", "Order", "Customer",
         "Order holds a persistent Customer reference"),
        ("dependency", "OrderService", "Logger",
         "OrderService uses Logger only as a method parameter"),
    ]
    print(f"\n  {'Type':<13}{'Glyph':<7}{'Mermaid':<8}"
          f"{'Example':<38}Semantics")
    print("  " + "-" * 76)
    for rel_type, src, tgt, why in samples:
        meta = REL_META[rel_type]
        ex = f"{src} {meta['glyph']} {tgt}"
        print(f"  {rel_type:<13}{meta['glyph']:<7}{meta['mermaid']:<8}"
              f"{ex:<38}{why}")

    print("""
  Composition vs Aggregation -- the single most-tested distinction:
    Verbal test: "if I delete the PARENT, must the CHILD also be deleted?"
      YES -> composition  (filled diamond *-- , Order *-- OrderItem)
      NO  -> aggregation  (hollow diamond o--, Library o-- Book)

  Arrow direction gotcha:
      inheritance / realization point CHILD -> PARENT  (the is-a direction)
      In Mermaid the triangle is on the parent side, so write:
          Parent <|-- Child     (NOT  Child <|-- Parent)""")


def section_multiplicity():
    banner("MULTIPLICITY -- how many objects participate at each end")
    rows = [
        ("1", "exactly one (mandatory)", "Order \"1\" --> \"1\" Customer"),
        ("0..1", "zero or one (optional)", "User \"1\" --> \"0..1\" PremiumSub"),
        ("*", "zero or more", "Customer \"1\" --> \"*\" Order"),
        ("1..*", "one or more (at least one)", "Order \"1\" *-- \"1..*\" Item"),
        ("n..m", "between n and m", "Team \"1\" --> \"5..15\" Player"),
    ]
    print(f"\n  {'Mult':<6}{'Meaning':<28}Example")
    print("  " + "-" * 60)
    for m, meaning, ex in rows:
        print(f"  {m:<6}{meaning:<28}{ex}")
    print("\n  Multiplicity goes at BOTH ends, in quotes adjacent to the line.")
    print("  Omitting it is the most common 6/10 -> 8/10 gap.")


def build_parking_lot():
    d = UMLDiagram("Parking Lot System")

    d.add_class(UMLClass("ParkingLot", attributes=[
        Attribute("id", "UUID"), Attribute("name", "String"),
        Attribute("levels", "List<Level>")],
        methods=[Method("parkVehicle", [("v", "Vehicle")], "Ticket"),
                 Method("unparkVehicle", [("t", "Ticket")], "Receipt"),
                 Method("findAvailableSpot", [("v", "Vehicle")], "ParkingSpot")]))

    d.add_class(UMLClass("Level", attributes=[
        Attribute("floor", "int"), Attribute("spots", "List<ParkingSpot>")],
        methods=[Method("availableCount", [("type", "SpotType")], "int")]))

    d.add_class(UMLClass("ParkingSpot", stereotype="abstract", attributes=[
        Attribute("spotId", "UUID", PROTECTED),
        Attribute("isOccupied", "Boolean", PROTECTED)],
        methods=[Method("canFit", [("v", "Vehicle")], "Boolean", PROTECTED,
                        is_abstract=True),
                 Method("occupy", [("v", "Vehicle")], "void"),
                 Method("vacate", [], "void")]))

    d.add_class(UMLClass("CompactSpot", methods=[
        Method("canFit", [("v", "Vehicle")], "Boolean")]))
    d.add_class(UMLClass("LargeSpot", methods=[
        Method("canFit", [("v", "Vehicle")], "Boolean")]))
    d.add_class(UMLClass("HandicappedSpot", attributes=[
        Attribute("permitRequired", "Boolean")],
        methods=[Method("canFit", [("v", "Vehicle")], "Boolean")]))

    d.add_class(UMLClass("Vehicle", stereotype="abstract", attributes=[
        Attribute("licensePlate", "String", PROTECTED),
        Attribute("size", "VehicleSize", PROTECTED)],
        methods=[Method("requiredSpotType", [], "SpotType", PROTECTED,
                        is_abstract=True)]))
    d.add_class(UMLClass("Car", methods=[
        Method("requiredSpotType", [], "SpotType")]))
    d.add_class(UMLClass("Truck", methods=[
        Method("requiredSpotType", [], "SpotType")]))
    d.add_class(UMLClass("Motorcycle", methods=[
        Method("requiredSpotType", [], "SpotType")]))

    d.add_class(UMLClass("Ticket", attributes=[
        Attribute("ticketId", "UUID"), Attribute("entryTime", "DateTime"),
        Attribute("spotId", "UUID")],
        methods=[Method("duration", [], "Duration")]))

    d.add_class(UMLClass("PricingStrategy", stereotype="interface",
        methods=[Method("computeFee", [("duration", "Duration")], "Money",
                        is_abstract=True)]))
    d.add_class(UMLClass("HourlyPricing", attributes=[
        Attribute("ratePerHour", "Money")],
        methods=[Method("computeFee", [("duration", "Duration")], "Money")]))
    d.add_class(UMLClass("FlatRatePricing", attributes=[
        Attribute("flatRate", "Money")],
        methods=[Method("computeFee", [("duration", "Duration")], "Money")]))

    # --- relationships (source = child/owner/caller, target = parent/part/callee)
    d.add_relationship(Relationship("ParkingLot", "Level", "composition", "1", "*"))
    d.add_relationship(Relationship("Level", "ParkingSpot", "composition", "1", "*"))
    d.add_relationship(Relationship("CompactSpot", "ParkingSpot", "inheritance"))
    d.add_relationship(Relationship("LargeSpot", "ParkingSpot", "inheritance"))
    d.add_relationship(Relationship("HandicappedSpot", "ParkingSpot", "inheritance"))
    d.add_relationship(Relationship("Car", "Vehicle", "inheritance"))
    d.add_relationship(Relationship("Truck", "Vehicle", "inheritance"))
    d.add_relationship(Relationship("Motorcycle", "Vehicle", "inheritance"))
    d.add_relationship(Relationship("ParkingLot", "Ticket", "aggregation", "1", "*"))
    d.add_relationship(Relationship("Ticket", "Vehicle", "association", "*", "1"))
    d.add_relationship(Relationship("Ticket", "ParkingSpot", "association", "*", "1"))
    d.add_relationship(Relationship("ParkingLot", "PricingStrategy", "dependency"))
    d.add_relationship(Relationship("HourlyPricing", "PricingStrategy", "realization"))
    d.add_relationship(Relationship("FlatRatePricing", "PricingStrategy", "realization"))
    return d


def build_library():
    d = UMLDiagram("Library Management System")

    d.add_class(UMLClass("Library", attributes=[
        Attribute("name", "String"), Attribute("address", "String")],
        methods=[Method("addBook", [("b", "Book")], "void"),
                 Method("search", [("q", "String")], "List<Book>")]))

    d.add_class(UMLClass("Book", attributes=[
        Attribute("isbn", "String"), Attribute("title", "String"),
        Attribute("authors", "List<Author>")],
        methods=[Method("isAvailable", [], "Boolean")]))

    d.add_class(UMLClass("Author", attributes=[
        Attribute("name", "String"), Attribute("birthYear", "int")]))

    d.add_class(UMLClass("Member", attributes=[
        Attribute("memberId", "UUID"), Attribute("name", "String")],
        methods=[Method("borrow", [("b", "Book")], "Loan")]))

    d.add_class(UMLClass("Loan", attributes=[
        Attribute("loanId", "UUID"), Attribute("borrowedAt", "DateTime"),
        Attribute("dueAt", "DateTime")],
        methods=[Method("isOverdue", [], "Boolean"),
                 Method("computeOverdueDays", [], "int", PRIVATE)]))

    d.add_class(UMLClass("Fine", attributes=[Attribute("amount", "Money")],
        methods=[Method("waive", [], "void")]))

    d.add_class(UMLClass("BookCatalog", attributes=[
        Attribute("books", "Map<String,Book>")],
        methods=[Method("findByIsbn", [("isbn", "String")], "Book")]))

    d.add_class(UMLClass("SearchService",
        methods=[Method("search", [("q", "String"), ("catalog", "BookCatalog")],
                        "List<Book>")]))

    # Library o-- Book : books outlive the library  -> aggregation
    d.add_relationship(Relationship("Library", "Book", "aggregation", "1", "*", "has"))
    # Book -- Author : many-to-many persistent reference -> association
    d.add_relationship(Relationship("Book", "Author", "association", "*", "1..*", "writtenBy"))
    # Member -- Loan : a member has many loans -> association
    d.add_relationship(Relationship("Member", "Loan", "association", "1", "*", "borrows"))
    # Loan -- Book : each loan is for one book -> association
    d.add_relationship(Relationship("Loan", "Book", "association", "*", "1", "for"))
    # Loan *-- Fine : the fine cannot exist outside the loan -> composition
    d.add_relationship(Relationship("Loan", "Fine", "composition", "1", "0..1", "incurs"))
    # SearchService ..> BookCatalog : used only as a method param -> dependency
    d.add_relationship(Relationship("SearchService", "BookCatalog", "dependency", "1", "1", "uses"))
    return d


def section_parking_lot():
    banner("EXAMPLE 1 -- PARKING LOT SYSTEM")
    d = build_parking_lot()
    print(f"\n  {len(d.classes)} classes, {len(d.relationships)} relationships.\n")

    print("  Key class boxes:")
    for name in ("ParkingLot", "ParkingSpot", "PricingStrategy"):
        for ln in render_class_box(d.classes[name]):
            print(ln)
        print()

    print("  Relationship list (source -> target):")
    for r in d.relationships:
        meta = REL_META[r.rel_type]
        print(f"    {r.source:<16}{meta['glyph']:<6}{r.target:<16}"
              f"[{r.source_mult}..{r.target_mult}]  {r.rel_type}")

    print("\n  Structural validation:")
    issues = d.validate()
    if issues:
        for i in issues:
            print(i)
    else:
        print("    [ok] no issues -- realizations target interfaces, "
              "abstract classes declare abstract methods")

    c = d.counts()
    print(f"\n  Counts: {c}")
    print(f"  Coupling score = {d.coupling_score()}  "
          f"(sum of relationship strengths)")
    print(f"  Coupling density = {d.coupling_density():.1f}  (score / classes)")

    print("\n  Mermaid classDiagram source (renders in UML_CLASS_DIAGRAMS.md):")
    for ln in d.mermaid().splitlines()[:10]:
        print("    " + ln)
    print(f"    ... ({len(d.mermaid().splitlines())} lines total)")


def section_library():
    banner("EXAMPLE 2 -- LIBRARY MANAGEMENT (composition vs aggregation focus)")
    d = build_library()
    print(f"\n  {len(d.classes)} classes, {len(d.relationships)} relationships.\n")

    print("  Relationship decisions (the lifetime test in action):")
    for r in d.relationships:
        meta = REL_META[r.rel_type]
        print(f"    {r.source:<14}{meta['glyph']:<6}{r.target:<12}"
              f"{r.rel_type:<12}{r.label or ''}")

    print("""
  Lifetime arguments (say these OUT LOUD in the interview):
    Library o-- Book    AGGREGATION  -- closing the library does not burn the
                                       books; they can move to another branch.
    Loan    *-- Fine    COMPOSITION  -- a Fine cannot exist without the Loan
                                       that created it; delete the loan, the
                                       fine is meaningless.
    SearchService ..> BookCatalog  DEPENDENCY -- the catalog is passed in as a
                                       method parameter; it is not stored.""")

    c = d.counts()
    print(f"\n  Counts: {c}")
    print(f"  Coupling score = {d.coupling_score()}")
    print(f"  Coupling density = {d.coupling_density():.1f}")


def section_gold_check():
    """A single concrete value recomputed by uml_class_diagrams.html in JS."""
    banner("GOLD CHECK  (recomputed by uml_class_diagrams.html in JS)")
    d = build_parking_lot()
    sig = d.signature()
    density = d.coupling_density()
    gold_sig = "6,2,2,1,2,1"          # [inheritance,realization,composition,
    #                                      aggregation,association,dependency]
    gold_density = f"{density:.1f}"
    print(f"  parking_lot.signature()           = {sig}")
    print(f"  parking_lot.coupling_density()    = {gold_density}")
    print(f"    (score {d.coupling_score()} / classes {len(d.classes)})")
    assert sig == gold_sig, f"signature mismatch: {sig} != {gold_sig}"
    assert gold_density == "4.0", f"density mismatch: {gold_density}"
    print("  [check] OK")


# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    print("#" * 78)
    print("# UML CLASS DIAGRAMS -- structure, relationships, multiplicity "
          "(pure stdlib)")
    print("#" * 78)
    section_class_anatomy()
    section_relationships()
    section_multiplicity()
    section_parking_lot()
    section_library()
    section_gold_check()
    print("\n[check] OK -- all sections ran")
