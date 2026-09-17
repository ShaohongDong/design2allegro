"""Board-owned expectations for independently parsed final physical netlists."""

import hashlib
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from .model import ElectricalError

FILENAME = "netlist.expected.json"
TERMINAL = r"^[A-Za-z0-9_]+$"
REFERENCE = r"^[A-Za-z][A-Za-z0-9_]*$"
ENDPOINT = r"^[A-Za-z][A-Za-z0-9_]*\.[A-Za-z0-9_]+$"


def string_list(pattern):
    return {
        "type": "array",
        "items": {"type": "string", "pattern": pattern},
        "uniqueItems": True,
    }


SCHEMA = {
    "type": "object",
    "required": ["version", "board_id", "parts", "nets", "nc"],
    "additionalProperties": False,
    "properties": {
        "version": {"type": "integer", "const": 1},
        "board_id": {"type": "string", "minLength": 1},
        "parts": {
            "type": "object",
            "propertyNames": {"pattern": REFERENCE},
            "additionalProperties": {
                "type": "object",
                "required": ["package", "pins"],
                "additionalProperties": False,
                "properties": {
                    "package": {"type": "string", "pattern": r"^[A-Za-z0-9_+\-]+$"},
                    "pins": dict(string_list(TERMINAL), minItems=1),
                },
            },
        },
        "nets": {
            "type": "object",
            "propertyNames": {"pattern": TERMINAL},
            "additionalProperties": dict(string_list(ENDPOINT), minItems=1),
        },
        "nc": string_list(ENDPOINT),
    },
}


def validate_expectations(data, board_id, source=FILENAME):
    errors = sorted(
        Draft202012Validator(SCHEMA).iter_errors(data),
        key=lambda error: tuple(map(str, error.absolute_path)),
    )
    if errors:
        error = errors[0]
        path = "/".join(map(str, error.absolute_path))
        raise ElectricalError(f"{source}: /{path}: {error.message}")
    if data["board_id"] != board_id:
        raise ElectricalError(f"{source}: board_id differs from design")
    physical = {
        ref + "." + number
        for ref, part in data["parts"].items()
        for number in part["pins"]
    }
    assigned = set()
    for name, endpoints in [*data["nets"].items(), ("NC", data["nc"])]:
        overlap = assigned.intersection(endpoints)
        if overlap:
            raise ElectricalError(
                f"{source}: {name}: physical pins assigned more than once: {sorted(overlap)}"
            )
        assigned.update(endpoints)
    if assigned != physical:
        raise ElectricalError(
            f"{source}: incomplete physical inventory: "
            f"unassigned={sorted(physical - assigned)}, unknown={sorted(assigned - physical)}"
        )
    return data


def load_expectations(path, board_id):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON key: " + key)
            result[key] = value
        return result

    try:
        raw = Path(path).read_bytes()
        data = json.loads(raw, object_pairs_hook=unique)
    except (OSError, ValueError) as exc:
        raise ElectricalError(f"{path}: invalid netlist expectations: {exc}") from exc
    return (
        validate_expectations(data, board_id, str(path)),
        hashlib.sha256(raw).hexdigest(),
    )


def compare_netlist(expected, board_id, packages, terminals, nets):
    """Compare only actual Telesis/device readback, never the compiler's net graph."""
    validate_expectations(expected, board_id)
    differences = []

    def compare(label, wanted, actual):
        missing, extra = set(wanted) - set(actual), set(actual) - set(wanted)
        if missing or extra:
            differences.append(
                f"{label}: missing={sorted(missing)}, extra={sorted(extra)}"
            )

    compare("parts", expected["parts"], packages)
    for ref in sorted(set(expected["parts"]) & set(packages)):
        want = expected["parts"][ref]
        if want["package"] != packages[ref]["package"]:
            differences.append(
                f"{ref}: package expected={want['package']}, actual={packages[ref]['package']}"
            )
        compare(ref + " pins", want["pins"], terminals[ref])
    compare("nets", expected["nets"], nets)
    for name in sorted(set(expected["nets"]) | set(nets)):
        compare("net " + name, expected["nets"].get(name, []), nets.get(name, []))
    physical = {ref + "." + pin for ref, pins in terminals.items() for pin in pins}
    connected = {pin for pins in nets.values() for pin in pins}
    compare("NC", expected["nc"], physical - connected)
    if differences:
        raise ElectricalError(
            "final netlist expectations failed:\n" + "\n".join(differences)
        )
