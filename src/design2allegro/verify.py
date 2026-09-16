"""Independent parser for the supported Telesis/device subset (no writer imports)."""

import hashlib
import json
import re
from pathlib import Path


class NetlistFormatError(ValueError):
    pass


def parse_netlist(text):
    if not text.isascii():
        raise NetlistFormatError("non-ASCII netlist")
    # Continuations have a comma at the end of the preceding line.
    logical = re.sub(r",\s*\n\s*", ",", text).splitlines()
    section = None
    packages = {}
    nets = {}
    endpoints = set()
    seen = []
    for raw in logical:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("$"):
            if line not in ("$PACKAGES", "$NETS", "$END"):
                raise NetlistFormatError("unsupported section")
            seen.append(line)
            section = line
            continue
        if section == "$PACKAGES":
            m = re.fullmatch(
                r"'([A-Za-z0-9_+\-]+)'\s*!\s*'([A-Za-z0-9_]+)'\s*;\s*([A-Za-z][A-Za-z0-9_]*)",
                line,
            )
            if not m or m[3] in packages:
                raise NetlistFormatError("invalid/duplicate package")
            packages[m[3]] = {"package": m[1], "device": m[2]}
        elif section == "$NETS":
            fields = line.split(";")
            if len(fields) != 2:
                raise NetlistFormatError("invalid net record")
            name = fields[0].strip()
            nodes = [s.strip() for s in fields[1].split(",")]
            if not re.fullmatch(r"[A-Za-z0-9_]+", name) or name in nets:
                raise NetlistFormatError("duplicate/invalid net")
            for node in nodes:
                if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*\.[A-Za-z0-9_]+", node):
                    raise NetlistFormatError("invalid endpoint")
                if node in endpoints:
                    raise NetlistFormatError("physical pin repeated")
                endpoints.add(node)
            nets[name] = set(nodes)
        else:
            raise NetlistFormatError("content outside section")
    if seen != ["$PACKAGES", "$NETS", "$END"]:
        raise NetlistFormatError("section order/incomplete file")
    return packages, nets


def parse_device(text):
    if not text.isascii():
        raise NetlistFormatError("non-ASCII device")
    text = re.sub(r",\s*\n\s*", ",", text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if len(lines) != 6:
        raise NetlistFormatError("invalid device record count")
    package = re.fullmatch(r"PACKAGE '([A-Za-z0-9_+\-]+)'", lines[0])
    count = re.fullmatch(r"PINCOUNT (\d+)", lines[2])
    order = re.fullmatch(r"PINORDER main\s*,(.*)", lines[3])
    function = re.fullmatch(r"FUNCTION main main\s*,(.*)", lines[4])
    if (
        not package
        or lines[1] != "CLASS IC"
        or not count
        or not order
        or not function
        or lines[5] != "END"
    ):
        raise NetlistFormatError("invalid device syntax")
    names = [s.strip() for s in order[1].split(",")]
    numbers = [s.strip() for s in function[1].split(",")]
    if (
        len(names) != int(count[1])
        or len(numbers) != len(names)
        or len(set(numbers)) != len(numbers)
        or len(set(names)) != len(names)
    ):
        raise NetlistFormatError("device pin count/identity mismatch")
    if any(not re.fullmatch(r"[A-Za-z0-9_]+", v) for v in names + numbers):
        raise NetlistFormatError("invalid device terminal")
    return package[1], dict(zip(numbers, names))


def _verify_package(directory, expected=None):
    root = Path(directory)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise NetlistFormatError("symlink package path")
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest.get("producer") != "design2allegro" or manifest.get("version") not in (
        1,
        2,
    ):
        raise NetlistFormatError("unsupported manifest")
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    if actual != set(manifest["files"]) | {"manifest.json"} or any(
        p.is_symlink() for p in root.rglob("*")
    ):
        raise NetlistFormatError("unmanaged files or symlinks in package")
    required = {
        "circuit.json",
        "drc.json",
        "drc.md",
        "electrical-rules.json",
        "hierarchy.json",
        "inputs.json",
        "IMPORT.md",
    }
    if not required <= set(manifest["files"]):
        raise NetlistFormatError("incomplete delivery package")
    for name, want in manifest["files"].items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts:
            raise NetlistFormatError("unsafe manifest path")
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != want:
            raise NetlistFormatError("file digest mismatch " + name)
    circuit = json.loads((root / "circuit.json").read_text())
    from .model import CompiledDesign, canonical

    if CompiledDesign(canonical(circuit)).digest != manifest["snapshot"]:
        raise NetlistFormatError("snapshot digest mismatch")
    if expected is not None and circuit != expected:
        raise NetlistFormatError("delivered circuit differs from input")
    expected = circuit
    if not manifest.get("strict") or not manifest.get("drc_ok"):
        raise NetlistFormatError("package did not pass strict checking")
    if not json.loads((root / "drc.json").read_text()).get("ok"):
        raise NetlistFormatError("check report is blocked")
    tel = [p for p in manifest["files"] if p.endswith(".tel")]
    if len(tel) != 1:
        raise NetlistFormatError("expected one netlist")
    packages, nets = parse_netlist((root / tel[0]).read_text())
    references = {
        key: part.get("reference", key).upper()
        for key, part in expected["parts"].items()
    }
    expected_pins = {
        key: references[pin["ref"]] + "." + pin["num"]
        for key, pin in expected["pins"].items()
    }
    if manifest["references"] != references or manifest["pins"] != expected_pins:
        raise NetlistFormatError("manifest physical mapping differs from circuit")

    def encoded(value):
        return (
            "".join(
                chr(b) if 48 <= b <= 57 or 65 <= b <= 90 else "_%02X" % b
                for b in value.encode("utf-8")
            )
            or "_EMPTY"
        )

    if manifest["net_names"] != {name: encoded(name) for name in expected["nets"]}:
        raise NetlistFormatError("manifest net mapping differs from circuit")
    inverse_refs = {v: k for k, v in references.items()}
    physical = set()
    for ref, package in packages.items():
        device, terminals = parse_device(
            (root / "devices" / (package["device"] + ".txt")).read_text()
        )
        source_ref = inverse_refs.get(ref)
        if (
            source_ref not in expected["parts"]
            or expected["parts"][source_ref]["footprint"] != device
        ):
            raise NetlistFormatError("circuit package mismatch")
        if device != package["package"]:
            raise NetlistFormatError("package/device mismatch")
        want_terminals = {
            expected["pins"][key]["num"]: encoded(expected["pins"][key]["name"])
            + "__"
            + encoded(expected["pins"][key]["num"])
            for key in expected["parts"][source_ref]["pins"]
        }
        if terminals != want_terminals:
            raise NetlistFormatError("device terminals differ from circuit")
        physical.update(ref + "." + n for n in terminals)
    for endpoints in nets.values():
        if not endpoints <= physical:
            raise NetlistFormatError("net references unknown physical pin")
    if physical != set(manifest["pins"].values()):
        raise NetlistFormatError("physical inventory differs from manifest")
    if expected is not None:
        if set(packages) != set(manifest["references"].values()):
            raise NetlistFormatError("reference inventory mismatch")
        if set(manifest["pins"]) != set(expected["pins"]):
            raise NetlistFormatError("lost physical pins")
        want = {
            manifest["net_names"][n]: {manifest["pins"][k] for k in v["pins"]}
            for n, v in expected["nets"].items()
        }
        if nets != want:
            raise NetlistFormatError("connectivity mismatch")
    statistics = {"parts": len(packages), "pins": len(physical), "nets": len(nets)}
    if manifest["statistics"] != statistics:
        raise NetlistFormatError("manifest statistics mismatch")
    if json.loads((root / "hierarchy.json").read_text()) != expected["hierarchy"]:
        raise NetlistFormatError("hierarchy mismatch")
    if json.loads((root / "inputs.json").read_text()) != expected["inputs"]:
        raise NetlistFormatError("input provenance mismatch")
    if manifest["version"] == 2:
        from .artifacts import generate
        from .properties import resolve

        if expected.get("version") != 2 or expected.get("stage") != "annotated":
            raise NetlistFormatError("invalid annotated circuit")
        if (
            len(set(references.values())) != len(references)
            or expected["references"] != references
        ):
            raise NetlistFormatError("annotation mismatch")
        for identity, part in expected["parts"].items():
            _, normalized, missing = resolve(part["category"], {}, part["properties"])
            if (
                missing
                or normalized != part["normalized_properties"]
                or part["missing_properties"]
            ):
                raise NetlistFormatError(
                    "incomplete or inconsistent device specifications"
                )
            if part["id"] != identity or not re.fullmatch(
                part["prefix"] + "[1-9][0-9]*", part["reference"]
            ):
                raise NetlistFormatError("invalid annotated identity")
        for name, text in generate(expected).items():
            if name not in manifest["files"]:
                raise NetlistFormatError("missing derived artifact: " + name)
            if (root / name).read_text() != text:
                raise NetlistFormatError(
                    "derived artifact differs from circuit: " + name
                )
    return statistics


def verify_package(directory, expected=None):
    try:
        return _verify_package(directory, expected)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        if isinstance(exc, NetlistFormatError):
            raise
        raise NetlistFormatError(f"invalid package: {exc}") from exc
