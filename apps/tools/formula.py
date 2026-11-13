"""The worksheet engine's formula language (P12, docs/p12_tools.md).

A small, safe expression language, parsed here and evaluated here: nothing
is ever handed to Python's `eval`, and a name is only ever a field or column
of the worksheet. What it has:

- numbers, "strings", true/false; + - * / ^, parentheses;
- comparisons = != < <= > >=, and `and`, `or`, `not`;
- a field by its key (`hours`), a table's column as a list (`steps.load`),
  and, inside a table's computed column, the row's own columns by key;
- functions: sum, average, min, max, count, if, round, abs, sumif, countif,
  argmax, argmin, filter.

A blank number counts as 0 in arithmetic and is skipped by sum, average, min
and max. `if` evaluates only the branch it takes, so `if(capacity > 0,
demand / capacity, 0)` never divides by zero. Dividing by zero is an error
said in words ("Can't divide by zero"), on the field, never a crash.
"""

from __future__ import annotations

import re
from decimal import Decimal, DivisionByZero, InvalidOperation

MAX_LENGTH = 500
MAX_DEPTH = 40

FUNCTIONS = {"sum", "average", "min", "max", "count", "if", "round", "abs", "sumif",
             "countif", "argmax", "argmin", "filter"}
KEYWORDS = {"and", "or", "not", "true", "false"}


class FormulaError(ValueError):
    """The formula can't be read: said so it can be fixed as it is typed."""


class EvalError(ValueError):
    """The formula reads, but these values can't be worked out."""


_TOKEN = re.compile(r"""
    (?P<space>\s+)
  | (?P<number>\d+(?:\.\d+)?|\.\d+)
  | (?P<string>"[^"]*"|'[^']*')
  | (?P<name>[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)
  | (?P<op><=|>=|!=|==|[-+*/^(),=<>])
""", re.X)


def tokenize(text: str) -> list[tuple[str, str]]:
    if len(text) > MAX_LENGTH:
        raise FormulaError(f"A formula is at most {MAX_LENGTH} characters.")
    out, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if not m:
            raise FormulaError(f"I can't read “{text[pos:pos + 12]}”.")
        kind = m.lastgroup
        value = m.group(kind)
        pos = m.end()
        if kind == "space":
            continue
        if kind == "name" and "." in value:
            table, column = value.split(".", 1)
            if table.startswith("_") or column.startswith("_"):
                raise FormulaError(f"There is no field called “{value}”.")
        out.append((kind, value))
    return out


# ------------------------------------------------------------------ parsing

class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0
        self.depth = 0

    def peek(self):
        return self.tokens[self.i] if self.i < len(self.tokens) else (None, None)

    def take(self, value=None):
        kind, got = self.peek()
        if kind is None:
            raise FormulaError("The formula stops too soon.")
        if value is not None and got != value:
            raise FormulaError(f"Expected “{value}” but found “{got}”.")
        self.i += 1
        return kind, got

    def deeper(self):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            raise FormulaError("The formula nests too deeply.")

    def parse(self):
        if not self.tokens:
            raise FormulaError("The formula is empty.")
        node = self.expr()
        if self.i != len(self.tokens):
            raise FormulaError(f"I didn't expect “{self.peek()[1]}” there.")
        return node

    def expr(self):
        self.deeper()
        node = self.and_()
        while self.peek() == ("name", "or"):
            self.take()
            node = ("or", node, self.and_())
        self.depth -= 1
        return node

    def and_(self):
        node = self.not_()
        while self.peek() == ("name", "and"):
            self.take()
            node = ("and", node, self.not_())
        return node

    def not_(self):
        if self.peek() == ("name", "not"):
            self.take()
            return ("not", self.not_())
        return self.compare()

    def compare(self):
        node = self.add()
        kind, op = self.peek()
        if kind == "op" and op in ("=", "==", "!=", "<", "<=", ">", ">="):
            self.take()
            node = ("cmp", "=" if op == "==" else op, node, self.add())
        return node

    def add(self):
        node = self.mul()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            node = ("bin", op, node, self.mul())
        return node

    def mul(self):
        node = self.unary()
        while self.peek() in (("op", "*"), ("op", "/")):
            op = self.take()[1]
            node = ("bin", op, node, self.unary())
        return node

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            return ("neg", self.unary())
        if self.peek() == ("op", "+"):
            self.take()
            return self.unary()
        return self.power()

    def power(self):
        node = self.atom()
        if self.peek() == ("op", "^"):
            self.take()
            node = ("bin", "^", node, self.unary())
        return node

    def atom(self):
        kind, value = self.peek()
        if kind == "number":
            self.take()
            return ("num", Decimal(value))
        if kind == "string":
            self.take()
            return ("str", value[1:-1])
        if kind == "op" and value == "(":
            self.take()
            self.deeper()
            node = self.expr()
            self.depth -= 1
            self.take(")")
            return node
        if kind == "name":
            self.take()
            lower = value.lower()
            if lower in ("true", "false"):
                return ("num", Decimal(1 if lower == "true" else 0))
            if lower in KEYWORDS:
                raise FormulaError(f"“{value}” goes between two values.")
            if self.peek() == ("op", "("):
                if lower not in FUNCTIONS:
                    raise FormulaError(f"There is no function called “{value}”. The functions "
                                       "are " + ", ".join(sorted(FUNCTIONS)) + ".")
                self.take("(")
                args = []
                if self.peek() != ("op", ")"):
                    args.append(self.expr())
                    while self.peek() == ("op", ","):
                        self.take()
                        args.append(self.expr())
                self.take(")")
                return ("call", lower, args)
            return ("ref", value)
        if kind is None:
            raise FormulaError("The formula stops too soon.")
        raise FormulaError(f"I didn't expect “{value}” there.")


def parse(text: str):
    return _Parser(tokenize(str(text or ""))).parse()


def references(node) -> set[str]:
    """Every name the formula reads."""
    out = set()
    stack = [node]
    while stack:
        n = stack.pop()
        if n[0] == "ref":
            out.add(n[1])
        elif n[0] == "call":
            stack.extend(n[2])
        elif n[0] in ("bin", "cmp"):
            stack.extend(n[2:])
        elif n[0] in ("and", "or"):
            stack.extend(n[1:])
        elif n[0] in ("not", "neg"):
            stack.append(n[1])
    return out


ARITY = {"if": (3, 3), "round": (1, 2), "abs": (1, 1), "sumif": (3, 3), "countif": (2, 2),
         "argmax": (2, 2), "argmin": (2, 2), "filter": (2, 2)}


def check_calls(node):
    stack = [node]
    while stack:
        n = stack.pop()
        if n[0] == "call":
            low, high = ARITY.get(n[1], (1, 99))
            if not low <= len(n[2]) <= high:
                need = str(low) if low == high else f"{low} or {high}"
                raise FormulaError(f"{n[1]}() takes {need} "
                                   f"{'value' if high == 1 else 'values'}.")
            stack.extend(n[2])
        elif n[0] in ("bin", "cmp"):
            stack.extend(n[2:])
        elif n[0] in ("and", "or"):
            stack.extend(n[1:])
        elif n[0] in ("not", "neg"):
            stack.append(n[1])


def compile_(text: str):
    node = parse(text)
    check_calls(node)
    return node


# ------------------------------------------------------------------ evaluating

def _num(value):
    if value is None or value == "":
        return Decimal(0)
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, list):
        raise EvalError("A list of values can't be used as one number; sum it first.")
    try:
        return Decimal(str(value).replace(",", "").replace("$", "").rstrip("%").strip())
    except InvalidOperation:
        raise EvalError(f"“{value}” isn't a number.") from None


def _numbers(args) -> list[Decimal]:
    out = []
    for a in _flat(args):
        if a is None or a == "":
            continue
        if isinstance(a, str):
            try:
                out.append(_num(a))
            except EvalError:
                continue
        else:
            out.append(_num(a))
    return out


def _flat(args):
    for a in args:
        if isinstance(a, list):
            yield from a
        else:
            yield a


def _truthy(value) -> bool:
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, str):
        return bool(value.strip())
    if value is None:
        return False
    return _num(value) != 0


def _same(a, b) -> bool:
    if isinstance(a, str) or isinstance(b, str):
        return str(a if a is not None else "").strip().lower() == \
            str(b if b is not None else "").strip().lower()
    return _num(a) == _num(b)


def _list(value, name):
    if not isinstance(value, list):
        raise EvalError(f"{name}() needs a table's column, like steps.load.")
    return value


def evaluate(node, lookup):
    """`lookup(name)` returns a value or raises EvalError for an unknown name."""
    kind = node[0]
    if kind == "num":
        return node[1]
    if kind == "str":
        return node[1]
    if kind == "ref":
        return lookup(node[1])
    if kind == "neg":
        return -_num(evaluate(node[1], lookup))
    if kind == "not":
        return Decimal(0 if _truthy(evaluate(node[1], lookup)) else 1)
    if kind == "and":
        return Decimal(1 if _truthy(evaluate(node[1], lookup))
                       and _truthy(evaluate(node[2], lookup)) else 0)
    if kind == "or":
        return Decimal(1 if _truthy(evaluate(node[1], lookup))
                       or _truthy(evaluate(node[2], lookup)) else 0)
    if kind == "cmp":
        op, a, b = node[1], evaluate(node[2], lookup), evaluate(node[3], lookup)
        if op in ("=", "!="):
            same = _same(a, b)
            return Decimal(1 if same == (op == "=") else 0)
        x, y = _num(a), _num(b)
        return Decimal(1 if {"<": x < y, "<=": x <= y, ">": x > y, ">=": x >= y}[op] else 0)
    if kind == "bin":
        op = node[1]
        x, y = _num(evaluate(node[2], lookup)), _num(evaluate(node[3], lookup))
        try:
            if op == "+":
                return x + y
            if op == "-":
                return x - y
            if op == "*":
                return x * y
            if op == "/":
                if y == 0:
                    raise EvalError("Can't divide by zero.")
                return x / y
            if op == "^":
                if abs(y) > 12:
                    raise EvalError("A power is at most 12.")
                return x ** y
        except (DivisionByZero, InvalidOperation):
            raise EvalError("Can't divide by zero.") from None
    if kind == "call":
        return _call(node[1], node[2], lookup)
    raise EvalError("I can't work that out.")


def _call(name, args, lookup):
    if name == "if":
        cond = evaluate(args[0], lookup)
        return evaluate(args[1] if _truthy(cond) else args[2], lookup)
    values = [evaluate(a, lookup) for a in args]
    if name == "sum":
        return sum(_numbers(values), Decimal(0))
    if name == "average":
        nums = _numbers(values)
        return (sum(nums, Decimal(0)) / len(nums)) if nums else None
    if name == "min":
        nums = _numbers(values)
        return min(nums) if nums else None
    if name == "max":
        nums = _numbers(values)
        return max(nums) if nums else None
    if name == "count":
        return Decimal(sum(1 for v in _flat(values) if v not in (None, "")))
    if name == "round":
        places = int(_num(values[1])) if len(values) > 1 else 0
        if not 0 <= places <= 6:
            raise EvalError("round() keeps 0 to 6 places.")
        value = values[0]
        if value is None:
            return None
        return _num(value).quantize(Decimal(1).scaleb(-places))
    if name == "abs":
        return None if values[0] is None else abs(_num(values[0]))
    if name == "sumif":
        keys, values_ = _list(values[0], "sumif"), _list(values[2], "sumif")
        return sum((_num(v) for k, v in zip(keys, values_) if _same(k, values[1])
                    and v not in (None, "")), Decimal(0))
    if name == "countif":
        return Decimal(sum(1 for v in _list(values[0], "countif") if _same(v, values[1])))
    if name in ("argmax", "argmin"):
        labels, nums = _list(values[0], name), _list(values[1], name)
        pairs = [(lab, _num(n)) for lab, n in zip(labels, nums) if n not in (None, "")]
        if not pairs:
            return None
        chosen = (max if name == "argmax" else min)(pairs, key=lambda p: p[1])
        return chosen[0]
    if name == "filter":
        labels, flags = _list(values[0], "filter"), _list(values[1], "filter")
        return [lab for lab, f in zip(labels, flags) if _truthy(f) and lab not in (None, "")]
    raise EvalError(f"There is no function called {name}.")
