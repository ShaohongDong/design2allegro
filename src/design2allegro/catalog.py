"""Versioned, offline shared device and package catalogue."""

import hashlib
import json
import os
import re
from importlib.resources import files
from pathlib import Path

from .model import ElectricalError, canonical
from .properties import REQUIRED, resolve


def load_catalog(selection, inputs, root=None):
    try:
        return _load_catalog(selection, inputs, root)
    except ElectricalError:
        raise
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise ElectricalError(f"malformed shared catalogue: {exc}") from exc


def _load_catalog(selection, inputs, root=None):
    root = root if root is not None else os.environ.get("DESIGN2ALLEGRO_LIBRARY_ROOT")
    name, version = selection["name"], selection["version"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", version):
        raise ElectricalError("unsafe library version")
    relative = f"libraries/{name}/{version}.json"
    source = (
        Path(root) / name / (version + ".json")
        if root is not None
        else files("design2allegro").joinpath(relative)
    )
    try:
        raw = source.read_bytes()
    except FileNotFoundError as exc:
        raise ElectricalError(f"library version unavailable: {name}@{version}") from exc

    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ElectricalError("duplicate catalogue key " + k)
            result[k] = v
        return result

    try:
        catalog = json.loads(raw, object_pairs_hook=unique)
        canonical(catalog)
    except ValueError as exc:
        raise ElectricalError("invalid catalogue JSON") from exc
    if (
        set(catalog) != {"version", "name", "revision", "devices"}
        or catalog["version"] != 2
        or catalog["name"] != name
        or catalog["revision"] != version
    ):
        raise ElectricalError("library identity/version mismatch")
    inputs["catalog:" + name + "@" + version] = hashlib.sha256(raw).hexdigest()
    if not isinstance(catalog["devices"], dict):
        raise ElectricalError("invalid devices")
    from .loader import validate

    names = {}
    for key, device in catalog["devices"].items():
        if set(device) - {
            "category",
            "prefix",
            "pins",
            "packages",
            "properties",
            "groups",
            "electrical",
            "source",
            "description",
        }:
            raise ElectricalError("unknown device fields: " + key)
        if device.get("category") not in REQUIRED or not re.fullmatch(
            "[A-Z]+", device.get("prefix", "")
        ):
            raise ElectricalError("invalid category/prefix: " + key)
        resolve(device["category"], device.get("properties", {}), {})
        pins = device.get("pins", {})
        if not pins:
            raise ElectricalError("device has no logical pins: " + key)
        for pin, config in pins.items():
            if not re.fullmatch("[A-Za-z0-9_]+", pin):
                raise ElectricalError("unsafe logical pin " + pin)
            if set(config) - {"type", "electrical"}:
                raise ElectricalError("unknown logical pin fields")
            validate(dict(config, name=pin), "pin")
        packages = device.get("packages", {})
        if not packages:
            raise ElectricalError("device has no packages")
        for package, binding in packages.items():
            if set(binding) != {"allegro", "pads"} or not re.fullmatch(
                "[A-Za-z0-9_+-]+", binding["allegro"]
            ):
                raise ElectricalError("invalid package binding")
            if set(binding["pads"].values()) != set(pins) or len(
                binding["pads"]
            ) != len(pins):
                raise ElectricalError(
                    "package must bind every logical pin exactly once"
                )
            pads = list(binding["pads"])
            if any(not re.fullmatch("[A-Za-z0-9_]+", p) for p in pads) or len(
                {p.upper() for p in pads}
            ) != len(pads):
                raise ElectricalError("physical pad collision or invalid pad")
            upper = binding["allegro"].upper()
            if upper in names and names[upper] != binding["allegro"]:
                raise ElectricalError("package case collision")
            names[upper] = binding["allegro"]
        for group, members in device.get("groups", {}).items():
            if (
                not members
                or len(set(members)) != len(members)
                or not set(members) <= set(pins)
            ):
                raise ElectricalError("invalid pin group " + group)
    return catalog


def bind_device(catalog, config):
    from .loader import fail
    from .rules import intersect

    key = config["device"]
    if key not in catalog["devices"]:
        fail("unknown device " + key, config)
    device = catalog["devices"][key]
    if config["package"] not in device["packages"]:
        fail("unknown package binding", config)
    binding = device["packages"][config["package"]]
    try:
        props, normal, missing = resolve(
            device["category"],
            device.get("properties", {}),
            config.get("properties", {}),
        )
        electrical = intersect(
            device.get("electrical", {}), config.get("electrical", {})
        )
    except ElectricalError as exc:
        fail(str(exc), config)
    electrical = intersect(electrical, {"assembly": config["assembly"]})
    if "resistance" in props:
        electrical = intersect(
            electrical, {"resistance": normal["resistance"]["value"] + " ohm"}
        )
    if "initial_state" in props:
        electrical = intersect(electrical, {"initial_state": props["initial_state"]})
    if device["category"] != "testpoint":
        electrical.setdefault("role", device["category"])
    value = next(
        (
            props[k]
            for k in ("resistance", "capacitance", "frequency", "mpn", "impedance")
            if k in props
        ),
        key,
    )
    return dict(
        package=binding["allegro"],
        pins={
            pad: dict(device["pins"][pin], name=pin)
            for pad, pin in binding["pads"].items()
        },
        groups={
            g: [
                next(p for p, n in binding["pads"].items() if n == pin)
                for pin in members
            ]
            for g, members in device.get("groups", {}).items()
        },
        value=value,
        electrical=electrical,
        category=device["category"],
        prefix=device["prefix"],
        properties=props,
        normalized_properties=normal,
        missing_properties=missing,
        device=key,
        package_id=config["package"],
        source=device.get("source", {}),
    )
