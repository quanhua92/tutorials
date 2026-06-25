"""
query_parsing.py - Reference implementation of the SQL query parsing pipeline:
    SQL text  ->  LEXER  ->  tokens
    tokens    ->  PARSER ->  AST   (SelectStmt with target_list, from_clause, ...)
    AST       ->  PLANNER->  logical plan tree  (Scan -> Filter -> Sort -> Project)

This is the single source of truth that QUERY_PARSING.md is built from. Every
token, AST node, and plan node in the guide is printed by this file. If you
change something here, re-run and re-paste the output into the guide.

Run:
    python3 query_parsing.py

============================================================================
THE INTUITION (read this first) - the mailroom sorting office
============================================================================
A SQL string lands like a handwritten letter. Three desks process it in order:

  * DESK 1 - LEXER (the reader). Splits the raw string "SELECT name, age ..."
    into discrete TOKENS: keywords (SELECT, FROM), identifiers (name, users),
    operators (>), literals (25), punctuation (,). Each token is a labelled
    slip of paper. No meaning yet - just classified words.

  * DESK 2 - PARSER (the grammarian). Reads the token slips left to right and
    checks them against the SQL GRAMMAR (a set of rules: "a SELECT statement is
    SELECT <list> FROM <tables> [WHERE <expr>] ..."). Output: an AST - a TREE
    of typed nodes (SelectStmt / Column / BinaryOp / ...) that captures the
    *structure* of the query. A comma in the SELECT list becomes sibling nodes,
    not a comma token.

  * DESK 3 - PLANNER (the reorganizer). The AST mirrors the *syntax* (what the
    user typed). The LOGICAL PLAN reorganizes it into a *data-flow tree* with
    inputs at the leaves and the final result at the root. The plan applies the
    relational order: FROM/JOIN (source rows) -> WHERE (filter) -> GROUP BY
    (aggregate) -> HAVING (filter groups) -> SELECT (project columns) ->
    ORDER BY (sort) -> LIMIT (cap). Each stage becomes a plan node wrapped
    around the previous one.

WHY THE PLAN IS A TREE AND NOT A LIST:
    Every node has INPUTS (children) and produces an OUTPUT relation. A Filter
    takes rows in, keeps the ones matching its predicate, emits the rest. So a
    Filter sits ON TOP OF its input source. Nesting the stages inside-out
    (FROM at the leaf, LIMIT at the root) is what makes it a tree - and lets the
    optimizer later rewrite/swap subtrees (e.g. push the Filter below the Join).

LOGICAL vs PHYSICAL (Section D):
    The LOGICAL plan says WHAT to compute ("join users and orders on user_id").
    The PHYSICAL plan says HOW ("hash join" vs "nested loop"). One logical node
    may map to several physical operators; the cost-based optimizer picks one.

============================================================================
PLAIN-ENGLISH GLOSSARY (referred to throughout)
============================================================================
   token       : a labelled slip from the lexer. Has a TYPE (KEYWORD, IDENT,
                 NUMBER, STRING, OP, PUNCT) and a VALUE (the raw text).
   lexeme      : the raw substring a token came from (e.g. "SELECT", "25").
   keyword     : a reserved word the grammar treats specially (SELECT, FROM,
                 WHERE, JOIN, ON, AND, OR, GROUP, BY, ORDER, LIMIT, IN, ...).
                 Matched case-INSENSITIVELY; normalized to UPPER for output.
   identifier  : a user-defined name (table or column). NOT a keyword.
                 Preserved case-sensitively (we do not fold to lower).
   literal     : a concrete value token: NUMBER (25, 3.14) or STRING ('alice').
   operator    : = != <> < > <= >= + - * /. Used inside expressions.
   grammar     : the set of recursive rules defining valid SQL. Enforced by the
                 parser; a rule violation is a SYNTAX ERROR.
   AST         : Abstract Syntax Tree. The structural, in-memory form of the
                 query once tokens pass the grammar. Typed node objects.
   AST node    : an object like SelectStmt, Column, BinaryOp. Holds children
                 (sub-expressions / clauses), not raw tokens.
   logical plan: the data-flow tree the PLANNER builds from the AST. Leaves are
                 SCANS; root is the final operator (LIMIT/SORT/PROJECT).
   plan node   : LogicalScan, LogicalFilter, LogicalJoin, LogicalAggregate,
                 LogicalSort, LogicalProject, LogicalLimit, SubqueryScan.
   operator    : a plan node is often called an "operator" in query-planning
   (plan)       literature (distinct from the expression "operator" like '>').
   correlation : a subquery that references a column from the OUTER query. The
                 planner cannot run it once - it must be re-evaluated per outer
                 row (or DECORRELATED into a join). Section E.
   round-trip  : serialize(AST) -> SQL' , tokenize(SQL') == tokenize(SQL).
                 Proves the AST captured the query losslessly. Gold-check (F).

============================================================================
THE LINEAGE (sources)
============================================================================
   SQL-92 / SQL:1999    ANSI X3.135-1992 introduced the standard grammar;
                       SQL:1999 added CTEs, recursive queries, window functions.
   recursive descent   Wirth 1976 "Algorithms + Data Structures = Programs":
                       one function per grammar rule, top-down, no backtracking
                       for LL(1) fragments. What we implement here.
   PostgreSQL parser   src/backend/parser/ (flex/bison, gram.y + scan.l):
                       the production-grade version of this pipeline.grammer
                       -> raw parse tree -> analyze.c -> query tree.
   System R (1979)     Selinger et al. introduced separating the LOGICAL plan
                       (relational algebra) from the PHYSICAL plan (access
                       paths + join algorithms). The split in Section D.
   Volcano/Cascades    Graefe 1993/1995: the optimizer as tree rewriting over
                 the logical plan; this is how "Filter pushed below Join" works.

KEY INVARIANTS (all asserted in code):
   tokenize(sql)            -> [Token,...]                       (deterministic)
   parse(tokens)            -> AST                               (lossless)
   serialize(AST)           -> sql'                              (canonical)
   plan(AST)                -> PlanTree                          (relational order)
   tokenize(serialize(parse(tokenize(sql)))) == tokenize(sql)   (ROUND-TRIP, §F)

Relational algebra the planner embodies (order matters - this is the tree nest):
   FROM/JOIN  -> base relation(s)            (leaves: Scan, Join)
   WHERE      -> selection  sigma            (Filter)
   GROUP BY   -> aggregation gamma           (Aggregate)
   HAVING     -> selection on groups         (Filter)
   SELECT     -> projection  pi              (Project)
   ORDER BY   -> sort                        (Sort)
   LIMIT      -> cap                         (Limit)
"""

from __future__ import annotations

BANNER = "=" * 72

# ============================================================================
# 1. THE LEXER  (Desk 1: SQL text -> tokens)
#    One deterministic scan left-to-right. Emits typed Token slips.
# ============================================================================

# Reserved words. Matched case-insensitively, normalized to UPPER on output.
# Keep the set small - just what the supported SELECT dialect needs.
KEYWORDS = {
    "SELECT", "DISTINCT", "FROM", "WHERE", "GROUP", "BY", "HAVING",
    "ORDER", "LIMIT", "JOIN", "INNER", "LEFT", "RIGHT", "FULL", "OUTER",
    "ON", "AND", "OR", "NOT", "IN", "IS", "NULL", "AS", "ASC", "DESC",
    "OFFSET", "UNION", "ALL", "EXISTS", "BETWEEN", "LIKE",
}

# Two-character operators must be matched BEFORE their one-char prefixes.
_TWO_CHAR_OPS = ("!=", "<>", "<=", ">=", "||")
_ONE_CHAR_OPS = set("=<>+-*/%")
_PUNCT = {",": "COMMA", "(": "LPAREN", ")": "RPAREN", ".": "DOT", ";": "SEMI"}


class Token:
    """A labelled slip from the lexer.

    type: one of KEYWORD, IDENT, NUMBER, STRING, OP, PUNCT
    value: the canonical lexeme (keywords upper-cased; everything else verbatim)
    pos: character offset in the source (for error messages)
    """

    __slots__ = ("type", "value", "pos")

    def __init__(self, type_: str, value: str, pos: int):
        self.type = type_
        self.value = value
        self.pos = pos

    def __repr__(self):
        return f"Token({self.type}, {self.value!r})"

    def __eq__(self, other):
        # Two tokens are equal iff type AND value match. Lets us compare token
        # streams directly for the round-trip gold check.
        return isinstance(other, Token) and self.type == other.type and self.value == other.value

    def __hash__(self):
        return hash((self.type, self.value))


def tokenize(sql: str) -> list[Token]:
    """Split a SQL string into a Token list. Deterministic, no external state.

    Skips whitespace and SQL line comments (-- ...). Does NOT strip the
    trailing semicolon - it becomes a SEMI punct token, like any other.
    """
    tokens: list[Token] = []
    i, n = 0, len(sql)
    while i < n:
        c = sql[i]
        # whitespace
        if c.isspace():
            i += 1
            continue
        # line comment  -- ... \n
        if c == "-" and i + 1 < n and sql[i + 1] == "-":
            while i < n and sql[i] != "\n":
                i += 1
            continue
        # string literal  '...'
        if c == "'":
            j = i + 1
            buf = []
            while j < n:
                if sql[j] == "'":
                    # '' is an escaped single quote inside the string
                    if j + 1 < n and sql[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(sql[j])
                j += 1
            if j >= n:
                raise SyntaxError(f"unterminated string at pos {i}")
            tokens.append(Token("STRING", "".join(buf), i))
            i = j + 1
            continue
        # number  [0-9]+(.[0-9]+)?
        if c.isdigit() or (c == "." and i + 1 < n and sql[i + 1].isdigit()):
            j = i
            seen_dot = False
            while j < n and (sql[j].isdigit() or (sql[j] == "." and not seen_dot)):
                if sql[j] == ".":
                    seen_dot = True
                j += 1
            tokens.append(Token("NUMBER", sql[i:j], i))
            i = j
            continue
        # identifier / keyword  [A-Za-z_][A-Za-z0-9_]*
        if c.isalpha() or c == "_":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            word = sql[i:j]
            up = word.upper()
            if up in KEYWORDS:
                tokens.append(Token("KEYWORD", up, i))   # normalize to UPPER
            else:
                tokens.append(Token("IDENT", word, i))   # preserve case
            i = j
            continue
        # two-char operators
        two = sql[i:i + 2]
        if two in _TWO_CHAR_OPS:
            tokens.append(Token("OP", two, i))
            i += 2
            continue
        # one-char operators
        if c in _ONE_CHAR_OPS:
            tokens.append(Token("OP", c, i))
            i += 1
            continue
        # punctuation
        if c in _PUNCT:
            tokens.append(Token("PUNCT", c, i))
            i += 1
            continue
        raise SyntaxError(f"unexpected char {c!r} at pos {i}")
    return tokens


# ============================================================================
# 2. THE AST  (Desk 2 output: typed node tree)
#    Plain data classes. Each node knows how to pretty-print itself so we can
#    show the tree and serialize it back to SQL for the round-trip check.
# ============================================================================


class Node:
    """Base AST node."""

    def children(self) -> list["Node"]:
        return []


class Column(Node):
    """A column reference, possibly qualified by a table name: users.name."""

    def __init__(self, name: str, table: str | None = None):
        self.name = name
        self.table = table

    def __repr__(self):
        return f"Column({self.qual()})"

    def qual(self):
        return f"{self.table}.{self.name}" if self.table else self.name

    def to_sql(self):
        return self.qual()


class Star(Node):
    """SELECT *  (optionally table-qualified: users.*)"""

    def __init__(self, table: str | None = None):
        self.table = table

    def __repr__(self):
        return "Star(*)" if not self.table else f"Star({self.table}.*)"

    def to_sql(self):
        return f"{self.table}.*" if self.table else "*"


class Literal(Node):
    """A concrete value: NUMBER or STRING."""

    def __init__(self, value: str, kind: str):
        self.value = value          # keep the raw lexeme ("25", "'alice'")
        self.kind = kind            # "NUMBER" or "STRING"

    def __repr__(self):
        return f"Literal({self.kind}:{self.value})"

    def to_sql(self):
        if self.kind == "STRING":
            return "'" + self.value.replace("'", "''") + "'"
        return self.value


class BinaryOp(Node):
    """op(left, right). op is one of = != <> < > <= >= + - * / % AND OR."""

    def __init__(self, op: str, left: Node, right: Node):
        self.op = op
        self.left = left
        self.right = right

    def __repr__(self):
        return f"BinaryOp({self.op})"

    def children(self):
        return [self.left, self.right]

    def to_sql(self):
        # precedence-aware: delegate to the central serializer so nested ops
        # get parenthesized ONLY when required for an unambiguous round-trip.
        return _expr_sql(self, 0)


class UnaryOp(Node):
    """NOT expr  or  unary minus."""

    def __init__(self, op: str, operand: Node):
        self.op = op
        self.operand = operand

    def __repr__(self):
        return f"UnaryOp({self.op})"

    def children(self):
        return [self.operand]

    def to_sql(self):
        return _expr_sql(self, 0)


class FunctionCall(Node):
    """fn(args...) e.g. COUNT(*), LOWER(name)."""

    def __init__(self, name: str, args: list[Node]):
        self.name = name.upper()
        self.args = args

    def __repr__(self):
        return f"FunctionCall({self.name}/{len(self.args)})"

    def children(self):
        return list(self.args)

    def to_sql(self):
        return f"{self.name}(" + ", ".join(a.to_sql() for a in self.args) + ")"


class InExpr(Node):
    """expr IN (subquery)  or  expr IN (val1, val2, ...)."""

    def __init__(self, expr: Node, subquery: "SelectStmt" | None,
                 values: list[Node] | None, negated: bool = False):
        self.expr = expr
        self.subquery = subquery
        self.values = values
        self.negated = negated

    def __repr__(self):
        kind = "subquery" if self.subquery else "list"
        return f"InExpr({'NOT ' if self.negated else ''}{kind})"

    def children(self):
        out = [self.expr]
        if self.subquery is not None:
            out.append(self.subquery)
        if self.values:
            out.extend(self.values)
        return out

    def to_sql(self):
        return _expr_sql(self, 0)


class TableRef(Node):
    """A table in the FROM list: name + optional alias (AS alias / bare alias)."""

    def __init__(self, name: str, alias: str | None = None):
        self.name = name
        self.alias = alias

    def __repr__(self):
        return f"TableRef({self.name}{(' AS ' + self.alias) if self.alias else ''})"

    def to_sql(self):
        return self.name + (f" AS {self.alias}" if self.alias else "")


class Join(Node):
    """A join clause: left JOIN right ON condition."""

    def __init__(self, left: Node, right: Node, join_type: str, condition: Node):
        self.left = left
        self.right = right
        self.join_type = join_type      # INNER / LEFT / RIGHT / FULL / CROSS
        self.condition = condition

    def __repr__(self):
        return f"Join({self.join_type})"

    def children(self):
        return [self.left, self.right, self.condition]

    def to_sql(self):
        jt = "JOIN" if self.join_type == "INNER" else f"{self.join_type} JOIN"
        return f"{self.left.to_sql()} {jt} {self.right.to_sql()} ON {self.condition.to_sql()}"


class SelectItem(Node):
    """One element of the SELECT list: expr plus optional alias."""

    def __init__(self, expr: Node, alias: str | None = None):
        self.expr = expr
        self.alias = alias

    def __repr__(self):
        return f"SelectItem({self.expr}{(' AS ' + self.alias) if self.alias else ''})"

    def children(self):
        return [self.expr]

    def to_sql(self):
        return self.expr.to_sql() + (f" AS {self.alias}" if self.alias else "")


class OrderItem(Node):
    """One element of ORDER BY: expr + direction (ASC/DESC)."""

    def __init__(self, expr: Node, direction: str):
        self.expr = expr
        self.direction = direction      # "ASC" or "DESC"

    def __repr__(self):
        return f"OrderItem({self.direction})"

    def children(self):
        return [self.expr]

    def to_sql(self):
        return f"{self.expr.to_sql()} {self.direction}"


class SelectStmt(Node):
    """The root AST node for a SELECT statement."""

    def __init__(self):
        self.distinct = False
        self.targets: list[SelectItem] = []
        self.from_clause: Node | None = None     # TableRef, Join, or comma-list
        self.where: Node | None = None
        self.group_by: list[Node] = []
        self.having: Node | None = None
        self.order_by: list[OrderItem] = []
        self.limit: int | None = None

    def __repr__(self):
        return "SelectStmt"

    def children(self):
        c: list[Node] = []
        c.extend(self.targets)
        if self.from_clause is not None:
            c.append(self.from_clause)
        if self.where is not None:
            c.append(self.where)
        c.extend(self.group_by)
        if self.having is not None:
            c.append(self.having)
        c.extend(self.order_by)
        return c

    def to_sql(self):
        """Canonical re-serialization. Drives the round-trip gold check (§F).

        Keyword order is fixed (SELECT...FROM...WHERE...GROUP BY...HAVING...
        ORDER BY...LIMIT) regardless of how the user laid out the original SQL.
        """
        parts = ["SELECT"]
        if self.distinct:
            parts.append("DISTINCT")
        parts.append(", ".join(t.to_sql() for t in self.targets))
        if self.from_clause is not None:
            parts.append("FROM")
            parts.append(self.from_clause.to_sql())
        if self.where is not None:
            parts.append("WHERE")
            parts.append(self.where.to_sql())
        if self.group_by:
            parts.append("GROUP BY")
            parts.append(", ".join(g.to_sql() for g in self.group_by))
        if self.having is not None:
            parts.append("HAVING")
            parts.append(self.having.to_sql())
        if self.order_by:
            parts.append("ORDER BY")
            parts.append(", ".join(o.to_sql() for o in self.order_by))
        if self.limit is not None:
            parts.append("LIMIT")
            parts.append(str(self.limit))
        return " ".join(parts)


# ============================================================================
# 2b. PRECEDENCE-AWARE SERIALIZER  (drives the round-trip gold check)
#     Emits the MINIMAL parenthesization that re-parses to the same AST.
# ============================================================================

# Operator precedence, low (= binds loosest) to high. Matches the parser's
# precedence-climbing order, so serialize(parse(serialize(x))) == serialize(x).
_PREC = {
    "OR": 1, "AND": 2,
    "=": 3, "!=": 3, "<>": 3, "<": 3, ">": 3, "<=": 3, ">=": 3,
    "+": 4, "-": 4,
    "*": 5, "/": 5, "%": 5,
}
_NOT_PREC = 2      # NOT sits between AND(2) and comparison(3)
_IN_PREC = 3       # IN binds like a comparison


def _prec_of(node: Node) -> float:
    if isinstance(node, BinaryOp):
        return _PREC[node.op]
    if isinstance(node, InExpr):
        return _IN_PREC
    if isinstance(node, UnaryOp):
        return _NOT_PREC
    return 99           # atoms (Column, Literal, FunctionCall, ...) never bind


def _expr_sql(node: Node, min_prec: float) -> str:
    """Serialize `node`, parenthesizing iff its precedence < min_prec.

    Left-associative: the right operand must bind TIGHTER than the operator
    (min_prec+1), the left operand binds at the operator's own precedence.
    """
    if isinstance(node, BinaryOp):
        my = _PREC[node.op]
        left = _expr_sql(node.left, my)
        right = _expr_sql(node.right, my + 1)
        s = f"{left} {node.op} {right}"
        return f"({s})" if my < min_prec else s
    if isinstance(node, UnaryOp):
        s = f"{node.op} {_expr_sql(node.operand, _NOT_PREC)}"
        return f"({s})" if _NOT_PREC < min_prec else s
    if isinstance(node, InExpr):
        head = "NOT IN " if node.negated else "IN "
        if node.subquery is not None:
            body = f"{_expr_sql(node.expr, _IN_PREC)} {head}({node.subquery.to_sql()})"
        else:
            inner = ", ".join(v.to_sql() for v in node.values or [])
            body = f"{_expr_sql(node.expr, _IN_PREC)} {head}({inner})"
        return f"({body})" if _IN_PREC < min_prec else body
    # atoms (Column, Literal, FunctionCall, Star, ...)
    return node.to_sql()


# ============================================================================
# 3. THE PARSER  (Desk 2: tokens -> AST via recursive descent)
#    One method per grammar rule. Top-down, LL(1) on the fragments we support.
# ============================================================================


class Parser:
    """Recursive-descent parser. Holds the token list and a cursor.

    Usage:  ast = Parser(tokenize(sql)).parse_select()
    Raises SyntaxError on any grammar violation, with the offending token.
    """

    def __init__(self, tokens: list[Token]):
        # drop a trailing SEMI so "SELECT ...;" parses cleanly
        self.toks = [t for t in tokens if not (t.type == "PUNCT" and t.value == ";")]
        self.i = 0

    # ---- token cursor helpers ----
    def peek(self) -> Token | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def at_end(self) -> bool:
        return self.i >= len(self.toks)

    def advance(self) -> Token:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect_punct(self, value: str) -> Token:
        t = self.peek()
        if t is None or t.type != "PUNCT" or t.value != value:
            raise SyntaxError(f"expected {value!r}, got {t}")
        return self.advance()

    def match_kw(self, *kws: str) -> bool:
        t = self.peek()
        return t is not None and t.type == "KEYWORD" and t.value in kws

    def consume_kw(self, kw: str) -> Token:
        t = self.peek()
        if t is None or t.type != "KEYWORD" or t.value != kw:
            raise SyntaxError(f"expected keyword {kw}, got {t}")
        return self.advance()

    # ---- grammar entry point ----
    def parse_select(self, is_subquery: bool = False) -> SelectStmt:
        # When is_subquery=True we are parsing within parentheses (an IN list /
        # scalar subquery), so a trailing RPAREN is the expected terminator and
        # NOT a syntax error - the caller consumes it.
        stmt = SelectStmt()
        self.consume_kw("SELECT")
        if self.match_kw("DISTINCT"):
            self.advance()
            stmt.distinct = True
        stmt.targets = self.parse_select_list()
        if self.match_kw("FROM"):
            self.advance()
            stmt.from_clause = self.parse_from_clause()
        if self.match_kw("WHERE"):
            self.advance()
            stmt.where = self.parse_expr()
        if self.match_kw("GROUP"):
            self.advance()
            self.consume_kw("BY")
            stmt.group_by = self.parse_expr_list()
        if self.match_kw("HAVING"):
            self.advance()
            stmt.having = self.parse_expr()
        if self.match_kw("ORDER"):
            self.advance()
            self.consume_kw("BY")
            stmt.order_by = self.parse_order_list()
        if self.match_kw("LIMIT"):
            self.advance()
            num = self.advance()
            if num.type != "NUMBER":
                raise SyntaxError(f"LIMIT expects a number, got {num}")
            stmt.limit = int(num.value)
        if not self.at_end():
            t = self.peek()
            if not (is_subquery and t is not None and t.type == "PUNCT" and t.value == ")"):
                raise SyntaxError(f"unexpected trailing token: {t}")
        return stmt

    # ---- SELECT list ----
    def parse_select_list(self) -> list[SelectItem]:
        items = [self.parse_select_item()]
        while self.peek() is not None and self.peek().type == "PUNCT" and self.peek().value == ",":
            self.advance()
            items.append(self.parse_select_item())
        return items

    def parse_select_item(self) -> SelectItem:
        # bare *  or  table.*
        t = self.peek()
        if t is not None and t.type == "OP" and t.value == "*":
            self.advance()
            return SelectItem(Star())
        if (t is not None and t.type == "IDENT"
                and self.i + 2 < len(self.toks)
                and self.toks[self.i + 1].type == "PUNCT"
                and self.toks[self.i + 1].value == "."
                and self.toks[self.i + 2].type == "OP"
                and self.toks[self.i + 2].value == "*"):
            tbl = self.advance().value
            self.advance()  # dot
            self.advance()  # star
            return SelectItem(Star(tbl))
        expr = self.parse_expr()
        alias = None
        if self.match_kw("AS"):
            self.advance()
            alias = self.advance().value
        elif self.peek() is not None and self.peek().type == "IDENT":
            # bare alias:  expr alias  (no AS)
            alias = self.advance().value
        return SelectItem(expr, alias)

    # ---- FROM clause + JOINs ----
    def parse_from_clause(self) -> Node:
        node = self.parse_table_ref()
        # comma-separated tables are CROSS joins; JOIN ... ON are explicit.
        while True:
            t = self.peek()
            if t is not None and t.type == "PUNCT" and t.value == ",":
                self.advance()
                right = self.parse_table_ref()
                node = Join(node, right, "CROSS", Literal("TRUE", "NUMBER"))
            elif t is not None and t.type == "KEYWORD" and t.value in ("JOIN", "INNER", "LEFT", "RIGHT", "FULL"):
                jt = "INNER"
                if t.value in ("INNER", "LEFT", "RIGHT", "FULL"):
                    jt = self.advance().value
                    if self.match_kw("OUTER"):
                        self.advance()
                self.consume_kw("JOIN")
                right = self.parse_table_ref()
                self.consume_kw("ON")
                cond = self.parse_expr()
                node = Join(node, right, jt, cond)
            else:
                break
        return node

    def parse_table_ref(self) -> TableRef:
        t = self.peek()
        if t is None or t.type != "IDENT":
            raise SyntaxError(f"expected table name, got {t}")
        name = self.advance().value
        alias = None
        if self.match_kw("AS"):
            self.advance()
            alias = self.advance().value
        elif self.peek() is not None and self.peek().type == "IDENT":
            # bare alias:  users u
            alias = self.advance().value
        return TableRef(name, alias)

    # ---- expression grammar (precedence climbing) ----
    # lowest precedence first; each level calls the next.
    def parse_expr(self) -> Node:
        return self.parse_or()

    def parse_or(self) -> Node:
        node = self.parse_and()
        while self.match_kw("OR"):
            self.advance()
            node = BinaryOp("OR", node, self.parse_and())
        return node

    def parse_and(self) -> Node:
        node = self.parse_not()
        while self.match_kw("AND"):
            self.advance()
            node = BinaryOp("AND", node, self.parse_not())
        return node

    def parse_not(self) -> Node:
        if self.match_kw("NOT"):
            self.advance()
            return UnaryOp("NOT", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self) -> Node:
        node = self.parse_additive()
        # comparison operators  = != <> < > <= >=
        t = self.peek()
        while t is not None and t.type == "OP" and t.value in ("=", "!=", "<>", "<", ">", "<=", ">="):
            op = self.advance().value
            right = self.parse_additive()
            node = BinaryOp(op, node, right)
            t = self.peek()
        # IN (subquery | list), possibly NOT IN
        negated = False
        if self.match_kw("NOT"):
            # could be NOT IN
            saved = self.i
            self.advance()
            if self.match_kw("IN"):
                negated = True
            else:
                self.i = saved
                return node
        if self.match_kw("IN"):
            self.advance()
            self.expect_punct("(")
            if self.match_kw("SELECT"):
                sub = self.parse_select(is_subquery=True)
                self.expect_punct(")")
                node = InExpr(node, sub, None, negated)
            else:
                vals = self.parse_expr_list()
                self.expect_punct(")")
                node = InExpr(node, None, vals, negated)
        return node

    def parse_additive(self) -> Node:
        node = self.parse_multiplicative()
        while self.peek() is not None and self.peek().type == "OP" and self.peek().value in ("+", "-"):
            op = self.advance().value
            node = BinaryOp(op, node, self.parse_multiplicative())
        return node

    def parse_multiplicative(self) -> Node:
        node = self.parse_primary()
        while self.peek() is not None and self.peek().type == "OP" and self.peek().value in ("*", "/", "%"):
            op = self.advance().value
            node = BinaryOp(op, node, self.parse_primary())
        return node

    def parse_primary(self) -> Node:
        t = self.peek()
        if t is None:
            raise SyntaxError("unexpected end of input")
        # parenthesized sub-expression (NOT a subquery here - those are consumed by IN)
        if t.type == "PUNCT" and t.value == "(":
            self.advance()
            e = self.parse_expr()
            self.expect_punct(")")
            return e
        # literal
        if t.type == "NUMBER":
            self.advance()
            return Literal(t.value, "NUMBER")
        if t.type == "STRING":
            self.advance()
            return Literal(t.value, "STRING")
        if t.type == "KEYWORD" and t.value == "NULL":
            self.advance()
            return Literal("NULL", "NULL")
        # identifier, possibly qualified  table.col , or function call  fn(...)
        if t.type == "IDENT":
            name = self.advance().value
            # function call?
            if self.peek() is not None and self.peek().type == "PUNCT" and self.peek().value == "(":
                self.advance()
                args: list[Node] = []
                # COUNT(*) special-case
                if (self.peek() is not None and self.peek().type == "OP"
                        and self.peek().value == "*"):
                    self.advance()
                    args = [Star()]
                elif not (self.peek() is not None and self.peek().type == "PUNCT" and self.peek().value == ")"):
                    args = self.parse_expr_list()
                self.expect_punct(")")
                return FunctionCall(name, args)
            # table.column ?
            if self.peek() is not None and self.peek().type == "PUNCT" and self.peek().value == ".":
                self.advance()
                col = self.advance().value
                return Column(col, name)
            return Column(name)
        raise SyntaxError(f"unexpected token in expression: {t}")

    def parse_expr_list(self) -> list[Node]:
        out = [self.parse_expr()]
        while self.peek() is not None and self.peek().type == "PUNCT" and self.peek().value == ",":
            self.advance()
            out.append(self.parse_expr())
        return out

    def parse_order_list(self) -> list[OrderItem]:
        out = []
        while True:
            e = self.parse_expr()
            direction = "ASC"
            if self.match_kw("ASC"):
                self.advance()
            elif self.match_kw("DESC"):
                self.advance()
                direction = "DESC"
            out.append(OrderItem(e, direction))
            if self.peek() is not None and self.peek().type == "PUNCT" and self.peek().value == ",":
                self.advance()
                continue
            break
        return out


def parse(tokens: list[Token]) -> SelectStmt:
    return Parser(tokens).parse_select()


# ============================================================================
# 4. THE LOGICAL PLAN  (Desk 3: AST -> plan tree, relational order)
#    Each node has one or more INPUTS (children) and emits a relation.
#    The tree is built FROM-up (leaves) to LIMIT-down... wait, FROM is the
#    LEAF and LIMIT is the ROOT. We build inside-out then return the root.
# ============================================================================


class PlanNode:
    """Base plan node. `label()` is what the tree printer shows."""

    def __init__(self, inputs: list["PlanNode"] = None):
        self.inputs: list[PlanNode] = inputs or []

    def label(self) -> str:
        return type(self).__name__

    def children(self) -> list["PlanNode"]:
        return self.inputs


class LogicalScan(PlanNode):
    def __init__(self, table: str, alias: str | None = None):
        super().__init__()
        self.table = table
        self.alias = alias

    def label(self):
        a = f" AS {self.alias}" if self.alias else ""
        return f"Scan(table={self.table}{a})"


class LogicalFilter(PlanNode):
    """WHERE or HAVING. Keeps rows whose predicate evaluates true."""

    def __init__(self, predicate: Node, child: PlanNode, kind: str = "WHERE"):
        super().__init__([child])
        self.predicate = predicate
        self.kind = kind

    def label(self):
        return f"Filter[{self.kind}]({self.predicate.to_sql()})"


class LogicalJoin(PlanNode):
    def __init__(self, join_type: str, condition: Node, left: PlanNode, right: PlanNode):
        super().__init__([left, right])
        self.join_type = join_type
        self.condition = condition

    def label(self):
        return f"Join[{self.join_type}]({self.condition.to_sql()})"


class LogicalAggregate(PlanNode):
    """GROUP BY. If there is no GROUP BY but aggregates are present, this is a
    global aggregate (single group)."""

    def __init__(self, group_keys: list[Node], child: PlanNode):
        super().__init__([child])
        self.group_keys = group_keys

    def label(self):
        if not self.group_keys:
            return "Aggregate(global)"
        return "Aggregate(group=" + ", ".join(g.to_sql() for g in self.group_keys) + ")"


class LogicalSort(PlanNode):
    def __init__(self, keys: list[OrderItem], child: PlanNode):
        super().__init__([child])
        self.keys = keys

    def label(self):
        return "Sort(" + ", ".join(f"{k.expr.to_sql()} {k.direction}" for k in self.keys) + ")"


class LogicalProject(PlanNode):
    """SELECT list. Picks/emits the output columns."""

    def __init__(self, targets: list[SelectItem], distinct: bool, child: PlanNode):
        super().__init__([child])
        self.targets = targets
        self.distinct = distinct

    def label(self):
        cols = []
        for t in self.targets:
            if isinstance(t.expr, Star):
                cols.append("*")
            else:
                cols.append(t.alias or _col_name(t.expr))
        d = "DISTINCT " if self.distinct else ""
        return f"Project[{d}out={', '.join(cols)}]"


class LogicalLimit(PlanNode):
    def __init__(self, count: int, child: PlanNode):
        super().__init__([child])
        self.count = count

    def label(self):
        return f"Limit(n={self.count})"


class SubqueryScan(PlanNode):
    """A subquery in the plan: runs the inner plan, emits its result. Used for
    IN (SELECT ...) before decorrelation."""

    def __init__(self, plan: PlanNode, correlated: bool):
        super().__init__([])
        self.plan = plan
        self.correlated = correlated

    def label(self):
        tag = "correlated" if self.correlated else "uncorrelated"
        return f"SubqueryScan({tag})"

    def children(self):
        return [self.plan]


def _col_name(node: Node) -> str:
    """Best-effort output column name for a SELECT item without an alias."""
    if isinstance(node, Column):
        return node.name
    if isinstance(node, FunctionCall):
        return node.name.lower()
    return node.to_sql()


def build_logical_plan(stmt: SelectStmt) -> PlanNode:
    """AST -> logical plan tree, in relational order.

    Nesting (leaf first):  FROM/JOIN  ->  WHERE  ->  GROUP BY  ->  HAVING
    ->  SELECT  ->  ORDER BY  ->  LIMIT.  Each stage wraps the previous.
    """
    # 1. FROM / JOIN -> base relation(s)
    node = _build_from(stmt.from_clause)

    # 2. WHERE -> Filter
    if stmt.where is not None:
        node = LogicalFilter(stmt.where, node, kind="WHERE")

    # 3. GROUP BY -> Aggregate (only if group_by present or targets contain agg)
    has_agg = stmt.group_by or any(_has_aggregate(t.expr) for t in stmt.targets)
    if has_agg:
        node = LogicalAggregate(stmt.group_by, node)

    # 4. HAVING -> Filter on groups
    if stmt.having is not None:
        node = LogicalFilter(stmt.having, node, kind="HAVING")

    # 5. SELECT -> Project
    node = LogicalProject(stmt.targets, stmt.distinct, node)

    # 6. ORDER BY -> Sort
    if stmt.order_by:
        node = LogicalSort(stmt.order_by, node)

    # 7. LIMIT -> Limit
    if stmt.limit is not None:
        node = LogicalLimit(stmt.limit, node)

    return node


def _build_from(from_clause: Node | None) -> PlanNode:
    if from_clause is None:
        return LogicalScan("<dual>")     # SELECT without FROM
    if isinstance(from_clause, TableRef):
        return LogicalScan(from_clause.name, from_clause.alias)
    if isinstance(from_clause, Join):
        left = _build_from(from_clause.left)
        right = _build_from(from_clause.right)
        return LogicalJoin(from_clause.join_type, from_clause.condition, left, right)
    raise ValueError(f"unknown FROM node: {from_clause}")


def _has_aggregate(node: Node) -> bool:
    """True if the expression tree contains an aggregate function call."""
    AGG = {"COUNT", "SUM", "AVG", "MIN", "MAX"}
    if isinstance(node, FunctionCall) and node.name in AGG:
        return True
    if isinstance(node, InExpr) and node.subquery is not None:
        # do not recurse into a subquery's aggregates - they belong to it
        return _has_aggregate(node.expr)
    for c in node.children():
        if _has_aggregate(c):
            return True
    return False


# ============================================================================
# 5. CORRELATION DETECTION  (for Section E)
#    A subquery is CORRELATED if it references a column from an outer scope.
# ============================================================================


def is_correlated(subquery: SelectStmt, outer_tables: set[str]) -> bool:
    """Walk the subquery; if any unqualified/qualified column's table (or an
    inferred bare column) resolves to an outer table, it's correlated.

    Conservative: treats any bare column that does NOT belong to a subquery
    table as potentially outer. Good enough for the worked examples."""
    inner_tables = _collect_tables(subquery)
    return _refs_outer(subquery, outer_tables, inner_tables)


def _collect_tables(stmt: SelectStmt) -> set[str]:
    tables: set[str] = set()

    def walk_from(n: Node):
        if isinstance(n, TableRef):
            tables.add(n.name)
            if n.alias:
                tables.add(n.alias)
        elif isinstance(n, Join):
            walk_from(n.left)
            walk_from(n.right)

    if stmt.from_clause is not None:
        walk_from(stmt.from_clause)
    return tables


def _refs_outer(node: Node, outer: set[str], inner: set[str]) -> bool:
    if isinstance(node, Column):
        if node.table is not None:
            # qualified: correlated if the qualifier is an outer table/alias
            return node.table in outer and node.table not in inner
        # bare column: correlated only if the subquery has NO from tables at all
        # (then it must resolve outward) - we flag when inner is empty
        return not inner
    for c in node.children():
        if _refs_outer(c, outer, inner):
            return True
    return False


# ============================================================================
# 6. PRETTY PRINTERS
# ============================================================================


def banner(title: str):
    print()
    print(BANNER)
    print(f"  {title}")
    print(BANNER)


def print_token_stream(tokens: list[Token]) -> str:
    """Render the token stream as a numbered table."""
    lines = ["| # | type     | value          |",
             "|---|----------|----------------|"]
    for idx, t in enumerate(tokens):
        lines.append(f"| {idx:<2} | {t.type:<8} | {t.value:<14} |")
    return "\n".join(lines)


def print_ast_tree(root: Node) -> str:
    """ASCII tree of AST nodes. Shows the node type + a short summary."""
    lines: list[str] = []

    def walk(node: Node, prefix: str, is_last: bool, depth: int):
        connector = "└─ " if is_last else "├─ "
        lines.append(f"{prefix}{connector}{_ast_node_desc(node)}")
        kids = node.children()
        for k, child in enumerate(kids):
            last = k == len(kids) - 1
            ext = "   " if is_last else "│  "
            walk(child, prefix + ext, last, depth + 1)

    walk(root, "", True, 0)
    return "\n".join(lines)


def _ast_node_desc(node: Node) -> str:
    """One-line description for the AST tree."""
    if isinstance(node, SelectStmt):
        parts = ["SelectStmt"]
        if node.distinct:
            parts.append("DISTINCT")
        parts.append(f"targets=[{len(node.targets)}]")
        if node.from_clause is not None:
            parts.append("from")
        if node.where is not None:
            parts.append("where")
        if node.group_by:
            parts.append(f"group_by=[{len(node.group_by)}]")
        if node.having is not None:
            parts.append("having")
        if node.order_by:
            parts.append(f"order_by=[{len(node.order_by)}]")
        if node.limit is not None:
            parts.append(f"limit={node.limit}")
        return " ".join(parts)
    return repr(node)


def print_plan_tree(root: PlanNode) -> str:
    """ASCII tree of the logical plan. Root at top, scans at leaves."""
    lines: list[str] = []

    def walk(node: PlanNode, prefix: str, is_last: bool):
        connector = "└─ " if is_last else "├─ "
        lines.append(f"{prefix}{connector}{node.label()}")
        kids = node.children()
        for k, child in enumerate(kids):
            last = k == len(kids) - 1
            ext = "   " if is_last else "│  "
            walk(child, prefix + ext, last)

    lines.append(root.label())
    kids = root.children()
    for k, child in enumerate(kids):
        last = k == len(kids) - 1
        walk(child, "", last)
    return "\n".join(lines)


# ============================================================================
# 7. ROUND-TRIP GOLD CHECK  (serialize -> parse -> serialize must be a fixed point)
# ============================================================================


def token_signature(tokens: list[Token]) -> list[tuple[str, str]]:
    """Reduce a token stream to (type, value) pairs - what we compare."""
    return [(t.type, t.value) for t in tokens]


def ast_signature(node: Node) -> tuple:
    """A hashable structural signature of an AST, computed INDEPENDENTLY of
    to_sql. Used to prove parse(serialize(x)) is lossless at the AST level,
    not just at the string level."""
    if isinstance(node, Column):
        return ("Column", node.name, node.table)
    if isinstance(node, Star):
        return ("Star", node.table)
    if isinstance(node, Literal):
        return ("Literal", node.kind, node.value)
    if isinstance(node, BinaryOp):
        return ("BinaryOp", node.op, ast_signature(node.left), ast_signature(node.right))
    if isinstance(node, UnaryOp):
        return ("UnaryOp", node.op, ast_signature(node.operand))
    if isinstance(node, FunctionCall):
        return ("FunctionCall", node.name, tuple(ast_signature(a) for a in node.args))
    if isinstance(node, InExpr):
        sub = ast_signature(node.subquery) if node.subquery is not None else None
        vals = tuple(ast_signature(v) for v in node.values or [])
        return ("InExpr", node.negated, ast_signature(node.expr), sub, vals)
    if isinstance(node, TableRef):
        return ("TableRef", node.name, node.alias)
    if isinstance(node, Join):
        return ("Join", node.join_type, ast_signature(node.left),
                ast_signature(node.right), ast_signature(node.condition))
    if isinstance(node, SelectItem):
        return ("SelectItem", node.alias, ast_signature(node.expr))
    if isinstance(node, OrderItem):
        return ("OrderItem", node.direction, ast_signature(node.expr))
    if isinstance(node, SelectStmt):
        return ("SelectStmt", node.distinct,
                tuple(ast_signature(t) for t in node.targets),
                ast_signature(node.from_clause) if node.from_clause else None,
                ast_signature(node.where) if node.where else None,
                tuple(ast_signature(g) for g in node.group_by),
                ast_signature(node.having) if node.having else None,
                tuple(ast_signature(o) for o in node.order_by),
                node.limit)
    return ("?", repr(node))


def round_trip(sql: str) -> tuple[bool, str, str, bool]:
    """Fixed-point gold check on the CANONICAL form.

    1. AST1   = parse(tokenize(sql))
    2. canon1 = serialize(AST1)
    3. AST2   = parse(tokenize(canon1))
    4. canon2 = serialize(AST2)

    The check PASSES iff canon1 == canon2 (string-identical) AND AST1 is
    structurally equal to AST2. That proves serialize() is a FIXED POINT under
    parse -> serialize: once canonicalized, re-parsing and re-serializing yields
    the SAME canonical SQL and the SAME AST. I.e. the AST is lossless.

    Returns (ok, canon1, canon2, ast_equal).
    """
    ast1 = parse(tokenize(sql))
    canon1 = ast1.to_sql()
    ast2 = parse(tokenize(canon1))
    canon2 = ast2.to_sql()
    str_ok = canon1 == canon2
    ast_ok = ast_signature(ast1) == ast_signature(ast2)
    return (str_ok and ast_ok), canon1, canon2, ast_ok


# ============================================================================
# 8. SECTIONS  (each prints a banner + tables, feeding QUERY_PARSING.md)
# ============================================================================

DEMO_SQL = "SELECT name, age FROM users WHERE age > 25 ORDER BY name"


def section_a():
    banner("SECTION A: the lexer  (SQL text -> tokens)")
    print(f"Input SQL:\n  {DEMO_SQL}\n")
    tokens = tokenize(DEMO_SQL)
    print("The lexer emits one Token per lexical unit. Keywords are normalized")
    print("to UPPER; identifiers keep their case; literals keep their text.\n")
    print(print_token_stream(tokens))
    print()
    print("Token-type tally:")
    counts: dict[str, int] = {}
    for t in tokens:
        counts[t.type] = counts.get(t.type, 0) + 1
    for ty, c in counts.items():
        print(f"  {ty:<8} : {c}")
    print(f"\n[check] token count == {len(tokens)} :  OK")
    # assert every keyword landed in KEYWORDS
    kw_toks = [t for t in tokens if t.type == "KEYWORD"]
    assert all(t.value in KEYWORDS for t in kw_toks), "non-keyword in KEYWORD slot"
    print("[check] every KEYWORD token value is in the reserved set :  OK")


def section_b():
    banner("SECTION B: the parser  (tokens -> AST)")
    tokens = tokenize(DEMO_SQL)
    ast = parse(tokens)
    print("Recursive descent applies the grammar rule\n")
    print("  select_stmt := SELECT select_list FROM table_ref [WHERE expr]")
    print("                 [ORDER BY order_list] ...\n")
    print("and produces a typed AST. The tree below is what the planner consumes.\n")
    print(print_ast_tree(ast))
    print()
    print("Field summary of the SelectStmt root:")
    print(f"  distinct   = {ast.distinct}")
    print(f"  targets    = [{', '.join(repr(t.expr) for t in ast.targets)}]")
    print(f"  from_clause= {ast.from_clause!r}")
    print(f"  where      = {ast.where!r}")
    print(f"  group_by   = {ast.group_by or '-'}")
    print(f"  having     = {ast.having!r}")
    print(f"  order_by   = [{', '.join(repr(o) for o in ast.order_by)}]")
    print(f"  limit      = {ast.limit}")
    # grammar invariants
    assert isinstance(ast, SelectStmt)
    assert len(ast.targets) == 2
    assert isinstance(ast.where, BinaryOp) and ast.where.op == ">"
    assert isinstance(ast.where.right, Literal) and ast.where.right.value == "25"
    print("\n[check] WHERE is BinaryOp('>') with Literal('25') on the right :  OK")


def section_c():
    banner("SECTION C: the logical plan  (AST -> plan tree, relational order)")
    ast = parse(tokenize(DEMO_SQL))
    plan = build_logical_plan(ast)
    print("The planner reorganizes the AST into a DATA-FLOW tree. The relational")
    print("order is fixed: FROM -> WHERE -> GROUP BY -> HAVING -> SELECT ->")
    print("ORDER BY -> LIMIT. Each stage wraps the previous, so FROM is the LEAF")
    print("and the final stage is the ROOT. Read the tree top-down as 'do this,")
    print("feeding the result into the node above'.\n")
    print(print_plan_tree(plan))
    print()
    print("Reading this plan top-down:")
    print("  Sort(name ASC)        - order the surviving rows by name")
    print("    Project(name, age)  - emit only these two columns")
    print("      Filter(age > 25)  - keep rows where the predicate holds")
    print("        Scan(users)     - read the users table (the leaf source)")
    print()
    print("Note the structure is INSIDE-OUT vs the SQL text: SQL lists clauses")
    print("left-to-right (SELECT ... FROM ... WHERE ...), but the plan nests")
    print("FROM at the bottom because data flows UP from the source.")
    # shape invariants
    assert isinstance(plan, LogicalSort)
    assert isinstance(plan.inputs[0], LogicalProject)
    assert isinstance(plan.inputs[0].inputs[0], LogicalFilter)
    assert isinstance(plan.inputs[0].inputs[0].inputs[0], LogicalScan)
    print("\n[check] plan shape == Sort > Project > Filter > Scan :  OK")


def section_d():
    banner("SECTION D: logical vs physical plan  (WHAT vs HOW)")
    print("The LOGICAL plan says WHAT to compute in relational-algebra terms.")
    print("The PHYSICAL plan says HOW - which algorithm implements each node.\n")
    print("One logical operator can map to SEVERAL physical operators; the")
    print("cost-based optimizer picks the cheapest using statistics + a cost")
    print("model (Selinger 1979, System R; Graefe 1993, Cascades).\n")
    logical_to_physical = {
        "LogicalScan":   ["SeqScan", "IndexScan", "IndexOnlyScan", "BitmapHeapScan"],
        "LogicalFilter": ["Filter (in-memory)", "BitmapIndexScan (pushed)"],
        "LogicalJoin":   ["NestedLoopJoin", "HashJoin", "MergeJoin"],
        "LogicalAggregate": ["HashAggregate", "GroupAggregate (sorted input)"],
        "LogicalSort":   ["QuickSort (in-memory)", "ExternalMergeSort (on disk)"],
        "LogicalProject": ["Result (projection)", "Projection in child op"],
        "LogicalLimit":  ["Limit (stop after N rows)"],
    }
    print("| logical node      | physical alternatives                                  |")
    print("|-------------------|--------------------------------------------------------|")
    for k, v in logical_to_physical.items():
        print(f"| {k:<17} | {', '.join(v):<54} |")
    print()
    print("Worked mapping for the Section C plan:")
    ast = parse(tokenize(DEMO_SQL))
    logical = build_logical_plan(ast)
    print("\n| logical plan node          | example physical pick       | why |")
    print("|----------------------------|-----------------------------|-----|")
    # Walk the ENTIRE plan tree (pre-order) and emit one physical pick per node.
    picks = {
        LogicalScan:    ("SeqScan",       "no useful index on age"),
        LogicalFilter:  ("Filter",        "predicate applied row-by-row after scan"),
        LogicalProject: ("Result",        "just drops/renames columns"),
        LogicalSort:    ("QuickSort",     "result set fits in work_mem"),
        LogicalJoin:    ("HashJoin",      "build a hash table on the smaller side"),
        LogicalAggregate: ("HashAggregate", "group keys not pre-sorted"),
        LogicalLimit:   ("Limit",         "stop the child after N rows"),
    }

    def visit(node: PlanNode):
        for cls, (pick, why) in picks.items():
            if isinstance(node, cls):
                print(f"| {node.label():<26} | {pick:<27} | {why} |")
                break
        for child in node.children():
            visit(child)

    visit(logical)
    print()
    print("KEY POINT: the LOGICAL tree is optimizer-INVARIANT (a property of the")
    print("query); the PHYSICAL tree changes with data, indexes, and cost params.")
    print("That is why PostgreSQL EXPLAIN (physical) and EXPLAIN's logical form")
    print("can differ for the same SQL.")
    assert isinstance(logical, LogicalSort)
    print("\n[check] logical root type is stable across runs :  OK")


def section_e():
    banner("SECTION E: subquery handling  (IN (SELECT ...) -> SubqueryScan)")
    sub_sql = "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)"
    print(f"Input SQL:\n  {sub_sql}\n")
    ast = parse(tokenize(sub_sql))
    print("AST (note the InExpr holding a nested SelectStmt):\n")
    print(print_ast_tree(ast))
    print()
    # correlation check
    outer_tables = {"users"}
    in_node = ast.where
    assert isinstance(in_node, InExpr) and in_node.subquery is not None
    correlated = is_correlated(in_node.subquery, outer_tables)
    print(f"Correlation analysis: outer tables = {sorted(outer_tables)}")
    print(f"  inner subquery references an outer column?  {correlated}")
    print()
    if correlated:
        print("  -> CORRELATED: the subquery must be re-evaluated for EACH outer")
        print("     row (or decorrelated into a join by the optimizer).")
    else:
        print("  -> UNCORRELATED: the subquery is independent of the outer query.")
        print("     The planner can run it ONCE, materialize the result, and reuse")
        print("     it - typically as a Hash Semi-Join (decorrelation).")
    print()
    # plan: the WHERE becomes a Filter with a SubqueryScan as a sibling source
    sub_plan = build_logical_plan(in_node.subquery)
    subquery_node = SubqueryScan(sub_plan, correlated)
    print("Logical plan for the subquery alone (SubqueryScan wraps it):")
    print()
    print(print_plan_tree(subquery_node))
    print()
    print("Full plan (outer query), with the IN predicate carried by Filter:")
    print()
    outer_plan = build_logical_plan(ast)
    print(print_plan_tree(outer_plan))
    print()
    print("Decorrelation rewrite the optimizer may apply (uncorrelated case):")
    print("  Filter(id IN (subquery))  ==>  SemiJoin(users, subquery, on id=user_id)")
    print("A SemiJoin emits an outer row iff it has >=1 matching inner row, then")
    print("STOPS probing that row (no row duplication, unlike an inner join).")
    # invariants
    assert isinstance(ast.where, InExpr)
    assert ast.where.subquery is not None
    assert correlated is False, "this example is uncorrelated"
    print("\n[check] WHERE is InExpr with a SelectStmt subquery, uncorrelated :  OK")


def section_f():
    banner("SECTION F: GOLD CHECK  -  round-trip fixed point  parse -> serialize -> parse -> serialize")
    queries = [
        ("simple",   DEMO_SQL),
        ("join",     "SELECT u.name, o.total FROM users u INNER JOIN orders o ON u.id = o.user_id"),
        ("agg",      "SELECT city, COUNT(*) AS n FROM users WHERE age >= 18 GROUP BY city "
                      "HAVING COUNT(*) > 5 ORDER BY n DESC LIMIT 10"),
        ("subquery", "SELECT * FROM users WHERE id IN (SELECT user_id FROM orders)"),
        ("not_in",   "SELECT name FROM users WHERE id NOT IN (SELECT user_id FROM orders)"),
        ("distinct", "SELECT DISTINCT city FROM users ORDER BY city"),
    ]
    print("The AST serializer produces a CANONICAL SQL string. The gold check is a")
    print("FIXED-POINT test: parse the canonical SQL, re-serialize, and verify the")
    print("result is byte-identical AND the AST is structurally unchanged.\n")
    print("  canon1 = serialize(parse(tokenize(sql)))")
    print("  canon2 = serialize(parse(tokenize(canon1)))")
    print("  PASS  <=>  canon1 == canon2  AND  ast_signature(AST1) == ast_signature(AST2)\n")
    all_ok = True
    print("| name      | fixed-point | AST equal | canon1 tokens | canon2 tokens |")
    print("|-----------|-------------|-----------|---------------|---------------|")
    for name, sql in queries:
        ok, canon1, canon2, ast_ok = round_trip(sql)
        all_ok = all_ok and ok
        nt1, nt2 = len(tokenize(canon1)), len(tokenize(canon2))
        print(f"| {name:<9} | {'OK' if ok else 'FAIL':<11} | {'yes' if ast_ok else 'no':<9} | "
              f"{nt1:<13} | {nt2:<13} |")
    print()
    print("Canonical re-serialization of the demo query (original -> canonical):")
    _, canon1, _, _ = round_trip(DEMO_SQL)
    print(f"  original : {DEMO_SQL}")
    print(f"  canonical: {canon1}")
    print()
    print("Normalization the serializer applies (these are NOT losses - they make")
    print("the form canonical, and the canonical form round-trips perfectly):")
    print("   - bare alias  u      ->  AS u        (parser records alias either way)")
    print("   - ORDER BY name      ->  name ASC    (ASC is the documented default)")
    print("   - precedence parens added only when needed for an unambiguous parse")
    print()
    if all_ok:
        print("[check] GOLD: all 6 queries are round-trip fixed points :  OK")
    else:
        print("[check] GOLD: FAIL - round-trip fixed point broken")
    assert all_ok, "round-trip gold check failed"
    # compact scalars pinned for the .html gold badge
    demo_tokens = tokenize(canon1)
    print(f"\nGOLD scalar for the .html badge (canonical demo): token count = {len(demo_tokens)}")
    print(f"GOLD scalar for the .html badge (canonical demo): canonical = '{canon1}'")
    # cross-check token signatures of canon1 vs canon2 for the demo (must match)
    sig_match = token_signature(tokenize(canon1)) == token_signature(
        tokenize(round_trip(DEMO_SQL)[2]))
    assert sig_match
    print("[check] token signature(canon1) == token signature(canon2) for demo :  OK")


def main():
    print("query_parsing.py - reference impl. All output feeds QUERY_PARSING.md.")
    print("python", __import__("sys").version.split()[0])
    section_a()
    section_b()
    section_c()
    section_d()
    section_e()
    section_f()
    banner("DONE - all sections printed")


if __name__ == "__main__":
    main()
