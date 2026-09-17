"""Circuit language input and normalized internal schema validation."""

import json
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from jsonschema import Draft202012Validator

from .model import ElectricalError, canonical

SCHEMA = json.loads(files("design2allegro").joinpath("schema.json").read_text())


def fail(message, obj=None, context=""):
    location = getattr(obj, "source", None)
    prefix = ":".join(map(str, location)) if location else ""
    template = getattr(obj, "template_source", None)
    if template:
        message += " (template at " + ":".join(map(str, template)) + ")"
    raise ElectricalError(f"{prefix} {context}: {message}".strip())


def validate(value, kind):
    schema = dict(SCHEMA, **{"$ref": "#/$defs/" + kind})
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        error = min(errors, key=lambda e: tuple(map(str, e.absolute_path)))
        obj = value
        location = getattr(obj, "source", None)
        template = None
        for key in error.absolute_path:
            location = getattr(obj, "locations", {}).get(key, location)
            obj = obj[key]
            template = getattr(obj, "template_source", template)
            location = getattr(obj, "source", location)
        prefix = ":".join(map(str, location)) if location else kind
        suffix = (
            " (template at " + ":".join(map(str, template)) + ")" if template else ""
        )
        raise ElectricalError(
            f'{prefix} /{"/".join(map(str, error.absolute_path))}: {error.message}{suffix}'
        )
    try:
        canonical(value)
    except (ValueError, TypeError) as exc:
        raise ElectricalError(
            f"{kind}: metadata must contain finite JSON-compatible values: {exc}"
        ) from exc


@dataclass
class LoadedDesign:
    document: dict
    components: dict
    rules: dict
    waivers: list
    inputs: dict
    name: str = "design"
    path: str = ""
    catalog: dict | None = None
    netlist_expectations: dict | None = None


def load_design(path, *, library_root=None):
    path = Path(path).resolve()
    inputs = {}

    if path.suffix.lower() != ".circuit":
        raise ElectricalError(f"{path}: YAML input retired; use a .circuit design")
    from .elaboration import load_source

    document = load_source(path, inputs)
    validate(document, "design")
    expectations = None
    if "netlist_expectations" in document:
        from .expectations import load_expectations

        relative = Path(document["netlist_expectations"])
        if relative.is_absolute():
            fail("netlist_expectations must be a relative path", document)
        expected_path = (path.parent / relative).resolve()
        expectations, checksum = load_expectations(expected_path, document["id"])
        inputs[str(expected_path)] = checksum
    from .catalog import load_catalog

    catalog = load_catalog(document["library"], inputs, library_root)
    components = catalog["devices"]
    rules = document.get("rules", {"version": 1, "rules": []})
    waivers = document.get("waivers", [])
    return LoadedDesign(
        document,
        components,
        rules,
        waivers,
        inputs,
        document["name"],
        str(path),
        catalog,
        expectations,
    )
