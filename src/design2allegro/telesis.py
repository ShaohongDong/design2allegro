"""Deterministic Telesis package writer with rollback-safe publication."""

import ctypes
import hashlib
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from .model import ElectricalError, canonical, digest
from .rules import RuleSet


def token(value):
    """Injective ASCII encoding, including the escape character itself."""
    out = []
    for b in str(value).encode("utf-8"):
        out.append(chr(b) if 48 <= b <= 57 or 65 <= b <= 90 else "_%02X" % b)
    return "".join(out) or "_EMPTY"


def publish(stage, target):
    if not target.exists():
        os.replace(stage, target)
        return
    if target.is_symlink() or not target.is_dir():
        raise ElectricalError("destination must be a real directory")
    entries = list(target.iterdir())
    if entries:
        try:
            old = json.loads((target / "manifest.json").read_text())
        except Exception as exc:
            raise ElectricalError(
                "refusing to replace unmanaged output directory"
            ) from exc
        if old.get("producer") != "design2allegro":
            raise ElectricalError("unmanaged output manifest")
        actual = {
            p.relative_to(target).as_posix() for p in target.rglob("*") if p.is_file()
        }
        if actual != set(old["files"]) | {"manifest.json"} or any(
            p.is_symlink() for p in target.rglob("*")
        ):
            raise ElectricalError(
                "output directory contains unmanaged files or symlinks"
            )
    # Linux RENAME_EXCHANGE atomically swaps complete directories; old output remains
    # in stage until cleanup. Failure leaves the existing target untouched.
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, "renameat2", None)
    if rename is None:
        raise ElectricalError("atomic directory replacement requires Linux renameat2")
    result = rename(-100, os.fsencode(stage), -100, os.fsencode(target), 2)
    if result:
        raise OSError(ctypes.get_errno(), "cannot atomically publish export")


def export(
    snapshot,
    output_dir,
    mapping,
    rules=None,
    waivers=None,
    filename=None,
):
    if filename is None:
        filename = snapshot.data.get("name", "design") + ".tel"
    if Path(filename).name != filename or not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.tel", filename
    ):
        raise ElectricalError("filename must be a .tel basename")
    if not isinstance(mapping, dict) or mapping.get("version") != 1:
        raise ElectricalError("mapping requires version 1")
    if set(mapping) - {"version", "parts"}:
        raise ElectricalError("unknown mapping fields")
    # Freeze configuration so the checked rules match the delivered rules.
    mapping = json.loads(canonical(mapping))
    frozen_rules = RuleSet.load(rules) if rules is not None else None
    waivers = json.loads(canonical(waivers or []))
    rules = frozen_rules
    data = snapshot.data
    partmap = mapping.get("parts", {})
    if set(partmap) != set(data["parts"]):
        raise ElectricalError("mapping must cover exactly every physical part")
    report = snapshot.check(rules, waivers)
    if not report.ok:
        raise ElectricalError(
            "electrical DRC blocked export: " + canonical(report.data["coverage"])
        )
    if data.get("version") == 2 and data.get("stage") != "annotated":
        raise ElectricalError("automatic annotation required; use export_design")
    device_text = {}
    packages = []
    mapped_pins = {}
    refs = {}
    device_info = {}
    package_names = {}
    for ref, part in sorted(data["parts"].items()):
        outref = part.get("reference", ref).upper()
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", outref):
            raise ElectricalError("illegal reference " + ref)
        if outref in refs.values():
            raise ElectricalError("case-insensitive reference collision")
        refs[ref] = outref
        config = partmap[ref]
        if set(config) - {"package", "pins"}:
            raise ElectricalError("unknown package mapping fields")
        package = config.get("package", "")
        if not re.fullmatch(r"[A-Za-z0-9_+-]+", package):
            raise ElectricalError("explicit ASCII Allegro package required for " + ref)
        upper = package.upper()
        if upper in package_names and package_names[upper] != package:
            raise ElectricalError("package case collision")
        package_names[upper] = package
        pins = [data["pins"][key] for key in part["pins"]]
        if not pins:
            raise ElectricalError("physical package has no pins " + ref)
        numbers = {pin["num"] for pin in pins}
        overrides = config.get("pins")
        if overrides is not None and set(overrides) != numbers:
            raise ElectricalError("pin remapping must be complete for " + ref)
        terminal_rows = []
        used = set()
        for pin in pins:
            number = str(overrides[pin["num"]]) if overrides is not None else pin["num"]
            if not re.fullmatch(r"[A-Za-z0-9_]+", number):
                raise ElectricalError(
                    "unsafe physical pin number; explicit mapping required"
                )
            if number.upper() in used:
                raise ElectricalError("duplicate mapped physical pin")
            used.add(number.upper())
            mapped_pins[pin["id"]] = outref + "." + number
            terminal_rows.append(
                (number, token(pin["name"]) + "__" + token(number), pin["func"])
            )
        terminal_rows.sort()
        identity = {
            "package": package,
            "pins": terminal_rows,
            "value": part["value"],
            "name": part["name"],
        }
        dev = "D" + digest(identity)[:32]
        text = [
            "PACKAGE '" + package + "'",
            "CLASS IC",
            "PINCOUNT " + str(len(terminal_rows)),
            "PINORDER main " + "".join(",\n\t" + row[1] for row in terminal_rows),
            "FUNCTION main main " + "".join(",\n\t" + row[0] for row in terminal_rows),
            "END",
            "",
        ]
        rendered = "\n".join(text)
        if dev in device_text and device_info[dev] != identity:
            raise ElectricalError("device hash collision")
        device_text[dev] = rendered
        device_info[dev] = identity
        packages.append("'" + package + "' ! '" + dev + "' ; " + outref)
    names = {name: token(name) for name in data["nets"]}
    if len(set(names.values())) != len(names):
        raise ElectricalError("encoded net name collision")
    lines = ["$PACKAGES"] + packages + ["$NETS"]
    for name, net in sorted(data["nets"].items()):
        endpoints = [mapped_pins[p] for p in net["pins"]]
        lines.append(names[name] + " ; " + ",\n\t".join(endpoints))
    lines += ["$END", ""]
    content = {
        filename: "\n".join(lines),
        "circuit.json": canonical(data) + "\n",
        "hierarchy.json": canonical(data["hierarchy"]) + "\n",
        "inputs.json": canonical(data["inputs"]) + "\n",
        "drc.json": canonical(report.data) + "\n",
        "drc.md": report.markdown(),
        "electrical-rules.json": canonical(
            RuleSet.load(rules).data
            if rules is not None
            else {"version": 1, "rules": []}
        )
        + "\n",
        "IMPORT.md": "# Allegro import\n\nImport the .tel through the Telesis/Other logic import workflow for your Allegro version.\n"
        "Set devpath to devices/ and provide matching package symbols and padstacks through your library paths.\n"
        "No .psm or padstack is generated. Electrical rules are a sidecar, not imported Allegro constraints.\n"
        "This package has offline validation only; actual Allegro import is not verified.\n",
    }
    content.update(
        {"devices/" + dev + ".txt": text for dev, text in device_text.items()}
    )
    if data.get("version") == 2:
        from .artifacts import generate

        content.update(generate(data))
    manifest = {
        "version": data.get("version", 1),
        "producer": "design2allegro",
        "snapshot": snapshot.digest,
        "strict": True,
        "drc_ok": report.ok,
        "allegro_import_verified": False,
        "net_names": names,
        "references": refs,
        "pins": mapped_pins,
        "devices": device_info,
        "parts": partmap,
        "statistics": {k: len(data[k]) for k in ("parts", "pins", "nets")},
        "files": {
            name: hashlib.sha256(text.encode("utf-8")).hexdigest()
            for name, text in sorted(content.items())
        },
    }
    target = Path(output_dir).absolute()
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ElectricalError("symlink output path forbidden")
    if target.is_symlink():
        raise ElectricalError("symlink destination forbidden")
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".design2allegro-export-", dir=target.parent))
    try:
        for name, text in content.items():
            path = stage / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                text, encoding="ascii" if name.endswith((".tel", ".txt")) else "utf-8"
            )
        (stage / "manifest.json").write_text(
            canonical(manifest) + "\n", encoding="utf-8"
        )
        from .verify import verify_package

        verify_package(stage, expected=data)
        publish(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return manifest
