"""Safe, source-located YAML input and schema validation."""

import copy
import hashlib
import io
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

from .model import ElectricalError, canonical


class MarkedDict(dict):
    pass


class Loader(yaml.SafeLoader):
    yaml_implicit_resolvers = copy.deepcopy(yaml.SafeLoader.yaml_implicit_resolvers)

    def compose_node(self, parent, index):
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise ElectricalError(f"{event.start_mark}: YAML aliases are not supported")
        return super().compose_node(parent, index)


for key, resolvers in Loader.yaml_implicit_resolvers.items():
    Loader.yaml_implicit_resolvers[key] = [
        (tag, pattern)
        for tag, pattern in resolvers
        if tag not in ("tag:yaml.org,2002:bool", "tag:yaml.org,2002:timestamp")
    ]
Loader.add_implicit_resolver(
    "tag:yaml.org,2002:bool", re.compile(r"^(?:true|false)$"), list("tf")
)


def construct_mapping(loader, node):
    result = MarkedDict()
    result.source = (
        node.start_mark.name,
        node.start_mark.line + 1,
        node.start_mark.column + 1,
    )
    result.locations = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=True)
        if not isinstance(key, str):
            raise ElectricalError(
                f"{key_node.start_mark}: mapping keys must be strings (quote pin numbers)"
            )
        if key in result:
            raise ElectricalError(f"{key_node.start_mark}: duplicate YAML key {key!r}")
        result[key] = loader.construct_object(value_node, deep=True)
        result.locations[key] = (
            key_node.start_mark.name,
            key_node.start_mark.line + 1,
            key_node.start_mark.column + 1,
        )
    return result


Loader.add_constructor("tag:yaml.org,2002:map", construct_mapping)
SCHEMA = json.loads(files("design2allegro").joinpath("schema.json").read_text())


def fail(message, obj=None, context=""):
    location = getattr(obj, "source", None)
    prefix = ":".join(map(str, location)) if location else ""
    raise ElectricalError(f"{prefix} {context}: {message}".strip())


def validate(value, kind):
    schema = dict(SCHEMA, **{"$ref": "#/$defs/" + kind})
    errors = list(Draft202012Validator(schema).iter_errors(value))
    if errors:
        error = min(errors, key=lambda e: tuple(map(str, e.absolute_path)))
        obj = value
        location = getattr(obj, "source", None)
        for key in error.absolute_path:
            location = getattr(obj, "locations", {}).get(key, location)
            obj = obj[key]
        prefix = ":".join(map(str, location)) if location else kind
        raise ElectricalError(
            f'{prefix} /{"/".join(map(str, error.absolute_path))}: {error.message}'
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


def load_design(path, *, library_root=None):
    path = Path(path).resolve()
    inputs = {}

    def read(file, kind):
        file = file.resolve()
        if file.suffix.lower() not in (".yaml", ".yml"):
            raise ElectricalError(f"{file}: expected .yaml or .yml")
        raw = file.read_bytes()
        try:
            stream = io.StringIO(raw.decode("utf-8"))
            stream.name = str(file)
            value = yaml.load(stream, Loader=Loader)
        except (yaml.YAMLError, UnicodeError) as exc:
            raise ElectricalError(f"{file}: {exc}") from exc
        if kind == "design" and isinstance(value, dict) and value.get("version") == 1:
            fail(
                "version 1 input retired; migrate to version 2 shared library and stable IDs",
                value,
            )
        validate(value, kind)
        inputs[str(file)] = hashlib.sha256(raw).hexdigest()
        return value

    document = read(path, "design")
    from .catalog import load_catalog

    catalog = load_catalog(document["library"], inputs, library_root)
    components = catalog["devices"]
    rules = document.get("rules", {"version": 1, "rules": []})
    if isinstance(rules, str):
        rules = read(path.parent / rules, "rules")
    waivers = document.get("waivers", [])
    if isinstance(waivers, str):
        waivers = read(path.parent / waivers, "waivers")
    return LoadedDesign(
        document,
        components,
        rules,
        waivers,
        inputs,
        document["name"],
        str(path),
        catalog,
    )
