"""Non-executable Decimal expressions and dimensional type checking."""

from dataclasses import dataclass
from decimal import Decimal, DecimalException, localcontext

from .model import ElectricalError
from .properties import UNITS

# Basis: voltage, current, time, length. Ratio is dimensionless.
DIMENSIONS = {
    "number": (0, 0, 0, 0),
    "ratio": (0, 0, 0, 0),
    "voltage": (1, 0, 0, 0),
    "current": (0, 1, 0, 0),
    "resistance": (1, -1, 0, 0),
    "power": (1, 1, 0, 0),
    "capacitance": (-1, 1, 1, 0),
    "inductance": (1, -1, 1, 0),
    "frequency": (0, 0, -1, 0),
    "length": (0, 0, 0, 1),
}
BASE_UNITS = {
    "voltage": "V",
    "current": "A",
    "resistance": "ohm",
    "power": "W",
    "capacitance": "F",
    "inductance": "H",
    "frequency": "Hz",
    "length": "m",
}
TYPES = set(DIMENSIONS) | {"integer", "boolean", "string", "group"}


def error(message, source):
    raise ElectricalError(":".join(map(str, source)) + ": " + message)


@dataclass(frozen=True)
class Expr:
    op: str
    args: tuple
    source: tuple


@dataclass(frozen=True)
class Quantity:
    number: Decimal
    dimension: tuple = DIMENSIONS["number"]
    ratio: bool = False


def evaluate(expr, lookup, depth=0):
    if not isinstance(expr, Expr):
        return expr
    op, args, source = expr.op, expr.args, expr.source
    if depth >= 64:
        error("expression evaluation depth limit (64) exceeded", source)
    if op == "lookup":
        return lookup(args[0], source)
    if op == "literal":
        n, unit = args
        if unit is not None and unit not in UNITS:
            error(f"unknown unit {unit!r}", source)
        try:
            with localcontext() as ctx:
                ctx.prec = 28
                ctx.Emax, ctx.Emin = 999, -999
                value = +Decimal(n)
                if unit is None:
                    return Quantity(value)
                kind, scale = UNITS[unit]
                return Quantity(value * scale, DIMENSIONS[kind], kind == "ratio")
        except DecimalException:
            error("numeric literal outside supported range", source)
    values = [evaluate(a, lookup, depth + 1) for a in args]
    if any(not isinstance(v, Quantity) for v in values):
        error("arithmetic requires numeric quantities", source)
    a = values[0]
    try:
        with localcontext() as ctx:
            ctx.prec = 28
            ctx.Emax, ctx.Emin = 999, -999
            if op in ("positive", "negative"):
                return Quantity(
                    +a.number if op == "positive" else -a.number, a.dimension, a.ratio
                )
            b = values[1]
            if op in ("+", "-"):
                if a.dimension != b.dimension:
                    error("addition/subtraction requires matching dimensions", source)
                return Quantity(
                    a.number + b.number if op == "+" else a.number - b.number,
                    a.dimension,
                    a.ratio or b.ratio,
                )
            if op == "*":
                dims = tuple(x + y for x, y in zip(a.dimension, b.dimension))
                return Quantity(a.number * b.number, dims, a.ratio or b.ratio)
            if b.number == 0:
                error("division by zero", source)
            dims = tuple(x - y for x, y in zip(a.dimension, b.dimension))
            return Quantity(a.number / b.number, dims, a.ratio and not b.ratio)
    except DecimalException:
        error("expression result outside supported range", source)


def typed(value, kind, source):
    if kind not in TYPES:
        error(f"unknown parameter/constant type {kind!r}", source)
    if kind == "group":
        from .syntax import Reference

        if not isinstance(value, list) or any(
            not isinstance(v, Reference) for v in value
        ):
            error("group requires explicit object references", source)
        if len({v.kind for v in value}) > 1 or len(set(value)) != len(value):
            error("group must contain unique references of one kind", source)
        return value
    if kind in ("boolean", "string"):
        if type(value) is not (bool if kind == "boolean" else str):
            error(f"expected {kind}", source)
        return value
    if not isinstance(value, Quantity):
        error(f"expected numeric {kind}", source)
    expected = DIMENSIONS["number"] if kind == "integer" else DIMENSIONS[kind]
    if value.dimension != expected:
        error(f"wrong dimension for {kind}", source)
    if kind == "integer" and value.number != value.number.to_integral_value():
        error("expected integer, not fractional value", source)
    return Quantity(value.number, value.dimension, kind == "ratio")


def materialize(value, source):
    if not isinstance(value, Quantity):
        return value
    n = value.number
    if not n.is_finite():
        error("expression result must be finite", source)
    if value.dimension == DIMENSIONS["number"]:
        if value.ratio:
            return format((n * 100).normalize(), "f") + " %"
        return int(n) if n == n.to_integral_value() else float(n)
    for kind, dim in DIMENSIONS.items():
        if dim == value.dimension and kind in BASE_UNITS:
            return format(n.normalize(), "f") + " " + BASE_UNITS[kind]
    error("result has unsupported compound dimension", source)
