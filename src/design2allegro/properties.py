"""Typed procurement specifications; no inferred or placeholder ratings."""

import re
from decimal import Decimal

from .model import ElectricalError

# Property names map to dimensions, or to nonempty descriptive strings.
FIELDS = {
    "resistance": "resistance",
    "tolerance": "ratio",
    "power_rating": "power",
    "capacitance": "capacitance",
    "voltage_rating": "voltage",
    "dielectric": None,
    "polarized": "boolean",
    "inductance": "inductance",
    "impedance": "resistance",
    "impedance_frequency": "frequency",
    "current_rating": "current",
    "dc_resistance": "resistance",
    "frequency": "frequency",
    "load_capacitance": "capacitance",
    "frequency_tolerance": "ratio",
    "type": None,
    "color": None,
    "manufacturer": None,
    "mpn": None,
    "supply_min": "voltage",
    "supply_max": "voltage",
    "output_voltage": "voltage",
    "pitch": "length",
    "positions": "integer",
    "initial_state": "state",
}
REQUIRED = {
    "resistor": ["resistance", "tolerance", "power_rating"],
    "capacitor": [
        "capacitance",
        "voltage_rating",
        "tolerance",
        "dielectric",
        "polarized",
    ],
    "inductor": ["inductance", "current_rating", "dc_resistance"],
    "ferrite": ["impedance", "impedance_frequency", "current_rating", "dc_resistance"],
    "crystal": ["frequency", "load_capacitance", "frequency_tolerance"],
    "transistor": ["type", "current_rating", "voltage_rating", "power_rating"],
    "diode": ["type", "current_rating", "voltage_rating"],
    "led": ["type", "current_rating", "voltage_rating", "color"],
    "ic": ["manufacturer", "mpn", "supply_min", "supply_max"],
    "regulator": [
        "manufacturer",
        "mpn",
        "supply_min",
        "supply_max",
        "output_voltage",
        "current_rating",
    ],
    "connector": ["positions", "pitch", "current_rating", "voltage_rating"],
    "switch": ["initial_state", "current_rating", "voltage_rating"],
    "jumper": ["initial_state"],
    # Explicitly synthetic library entries, never procurement-ready devices.
    "testpoint": [],
}
UNITS = {}
for base, dimension in [
    ("ohm", "resistance"),
    ("V", "voltage"),
    ("A", "current"),
    ("W", "power"),
    ("F", "capacitance"),
    ("H", "inductance"),
    ("Hz", "frequency"),
    ("m", "length"),
]:
    for prefix, scale in [
        ("", "1"),
        ("p", "1e-12"),
        ("n", "1e-9"),
        ("u", "1e-6"),
        ("m", "1e-3"),
        ("k", "1e3"),
        ("M", "1e6"),
    ]:
        UNITS[prefix + base] = (dimension, Decimal(scale))
UNITS.update({"%": ("ratio", Decimal(".01")), "ppm": ("ratio", Decimal("1e-6"))})


def normalize(name, value):
    if name not in FIELDS:
        raise ElectricalError("unknown property " + name)
    dim = FIELDS[name]
    if dim == "boolean":
        if type(value) is not bool:
            raise ElectricalError(name + " must be boolean")
        return value
    if dim == "integer":
        if type(value) is not int or value < 1:
            raise ElectricalError(name + " must be positive integer")
        return value
    if dim == "state":
        if value not in ("open", "closed"):
            raise ElectricalError("invalid initial_state")
        return value
    if dim is None:
        if (
            not isinstance(value, str)
            or not value.strip()
            or value.lower() in ("unknown", "tbd", "n/a")
        ):
            raise ElectricalError(name + " requires a known value")
        return value
    m = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*([A-Za-z%]+)\s*",
        str(value),
    )
    if (
        m
        and m[2] in UNITS
        and name == "tolerance"
        and UNITS[m[2]][0] in ("capacitance", "resistance")
    ):
        dim = UNITS[m[2]][0]
    if not m or m[2] not in UNITS or UNITS[m[2]][0] != dim:
        raise ElectricalError(name + ": wrong or missing unit")
    n = Decimal(m[1]) * UNITS[m[2]][1]
    zero_allowed = name in ("resistance", "dc_resistance", "supply_min")
    if n < 0 or (not zero_allowed and n == 0) or (dim == "ratio" and n > 1):
        raise ElectricalError(name + ": value outside allowed range")
    return {"dimension": dim, "value": format(n.normalize(), "f")}


def resolve(category, fixed, supplied):
    if category not in REQUIRED:
        raise ElectricalError("unknown device category " + category)
    merged = dict(fixed)
    for k, v in supplied.items():
        if k in fixed and normalize(k, v) != normalize(k, fixed[k]):
            raise ElectricalError("fixed device specification conflict: " + k)
        merged[k] = v
    normalized = {k: normalize(k, v) for k, v in merged.items()}
    if "supply_min" in normalized and "supply_max" in normalized:
        if Decimal(normalized["supply_min"]["value"]) > Decimal(
            normalized["supply_max"]["value"]
        ):
            raise ElectricalError("supply_min exceeds supply_max")
    if "tolerance" in normalized:
        allowed = {
            "ratio",
            {"resistor": "resistance", "capacitor": "capacitance"}.get(
                category, "ratio"
            ),
        }
        if normalized["tolerance"]["dimension"] not in allowed:
            raise ElectricalError("tolerance dimension does not match device")
    missing = sorted(set(REQUIRED[category]) - set(merged))
    return merged, normalized, missing
