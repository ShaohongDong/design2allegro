"""Annotation history, strict typed specifications and transactional delivery."""

import copy
import csv
import fcntl
import hashlib
import json
import os
from pathlib import Path

import pytest
import yaml
from conftest import write_yaml

from design2allegro import ElectricalError, compile_design, export_design, load_design
from design2allegro.annotation import annotate, read_lock
from design2allegro.model import CompiledDesign, canonical
from design2allegro.properties import normalize
from design2allegro.verify import NetlistFormatError, verify_package


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "project"
    p.mkdir()
    doc = {
        "version": 2,
        "id": "passive-demo",
        "name": "passive_demo",
        "library": {"name": "standard", "version": "1"},
        "top": "board",
        "modules": {"board": {"parts": {}, "nc": []}},
    }
    for name, identity in [("pullup", "stable-first"), ("series", "stable-second")]:
        doc["modules"]["board"]["parts"][name] = {
            "id": identity,
            "identity_namespace": "",
            "device": "generic.resistor",
            "package": "resistor_0603",
            "assembly": "fitted",
            "properties": {
                "resistance": "10 kohm",
                "tolerance": "1 %",
                "power_rating": "0.1 W",
            },
        }
        doc["modules"]["board"]["nc"] += [
            {"part": name, "pin": pin} for pin in ["A", "B"]
        ]
    write_yaml(p / "board.yaml", doc)
    return p / "board.yaml"


def edit(project, fn):
    d = yaml.safe_load(project.read_text())
    fn(d)
    write_yaml(project, d)


def build(project, out):
    return export_design(compile_design(load_design(project)), out)


def refs(out):
    return json.loads((out / "references.json").read_text())


def files(out):
    return {
        p.relative_to(out).as_posix(): p.read_bytes()
        for p in out.rglob("*")
        if p.is_file()
    }


def test_auto_refs_rename_reorder_move_and_edit(project, tmp_path):
    out = tmp_path / "out"
    build(project, out)
    before = refs(out)
    assert before == {"stable-first": "R1", "stable-second": "R2"}

    def change(d):
        m = d["modules"]["board"]
        m["parts"]["renamed"] = m["parts"].pop("pullup")
        for ep in m["nc"]:
            if ep["part"] == "pullup":
                ep["part"] = "renamed"
        m["parts"]["renamed"]["properties"]["resistance"] = "22 kohm"
        # Explicit immutable namespace preserves identity even across module moves.
        d["modules"]["leaf"] = {
            "parts": {"moved": m["parts"].pop("renamed")},
            "nc": [{"part": "moved", "pin": p} for p in ["A", "B"]],
        }
        m["nc"] = [ep for ep in m["nc"] if ep["part"] != "renamed"]
        m["instances"] = {"new_module": {"id": "new-module", "module": "leaf"}}

    edit(project, change)
    build(project, out)
    assert refs(out) == before
    edit(
        project, lambda d: d.update(modules=dict(reversed(list(d["modules"].items()))))
    )
    build(project, out)
    assert refs(out) == before


def test_deletion_addition_and_prefix_change(project, tmp_path):
    out = tmp_path / "out"
    build(project, out)

    def remove(d):
        m = d["modules"]["board"]
        m["parts"].pop("pullup")
        m["nc"] = [ep for ep in m["nc"] if ep["part"] != "pullup"]

    edit(project, remove)
    build(project, out)

    def add(d):
        m = d["modules"]["board"]
        m["parts"]["new"] = copy.deepcopy(m["parts"]["series"])
        m["parts"]["new"]["id"] = "new-id"
        m["nc"] += [{"part": "new", "pin": p} for p in ["A", "B"]]

    edit(project, add)
    build(project, out)
    assert refs(out) == {"stable-second": "R2", "new-id": "R3"}

    def capacitor(d):
        p = d["modules"]["board"]["parts"]["series"]
        p.update(
            device="generic.capacitor",
            package="capacitor_0603",
            properties={
                "capacitance": "100 nF",
                "tolerance": "10 %",
                "voltage_rating": "16 V",
                "dielectric": "X7R",
                "polarized": False,
            },
        )

    edit(project, capacitor)
    build(project, out)
    assert refs(out)["stable-second"] == "C1"
    lock = json.loads((project.parent / "design.lock.json").read_text())
    assert lock["assignments"]["stable-first"] == "R1" and "R2" in lock["retired"]


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("resistance", "10 V", "unit"),
        ("tolerance", "101 %", "range"),
        ("power_rating", "0 W", "range"),
        ("power_rating", "NaN W", "unit"),
        ("tolerance", "0.1 pF", "dimension"),
        ("bogus", "1 V", "unknown property"),
    ],
)
def test_bad_properties_located(project, field, value, match):
    edit(
        project,
        lambda d: d["modules"]["board"]["parts"]["pullup"]["properties"].update(
            {field: value}
        ),
    )
    with pytest.raises(ElectricalError, match=match) as exc:
        compile_design(load_design(project))
    assert str(project) in str(exc.value)


def test_missing_properties_fail_even_dnp_and_unwaivable(project, tmp_path):
    def change(d):
        p = d["modules"]["board"]["parts"]["pullup"]
        p["properties"].pop("power_rating")
        p["assembly"] = "dnp"
        d["waivers"] = [
            {
                "rule": "PROPERTY.REQUIRED",
                "object": "stable-first",
                "owner": "test",
                "reason": "cannot waive required procurement data",
            }
        ]

    edit(project, change)
    c = compile_design(load_design(project))
    assert not c.check().ok
    with pytest.raises(ElectricalError, match="power_rating"):
        export_design(c, tmp_path / "out")
    assert not (project.parent / "design.lock.json").exists()


def test_units_bom_grouping_and_accessories(project, tmp_path):
    edit(
        project,
        lambda d: d["modules"]["board"]["parts"]["series"]["properties"].update(
            resistance="10000 ohm", power_rating="100 mW"
        ),
    )
    out = tmp_path / "out"
    build(project, out)
    rows = list(csv.DictReader((out / "BOM.csv").open()))
    assert len(rows) == 1 and rows[0]["Quantity"] == "2"
    edit(
        project,
        lambda d: d["modules"]["board"]["parts"]["series"]["properties"].update(
            power_rating="0.25 W"
        ),
    )
    edit(
        project,
        lambda d: d.update(
            accessories=[
                {
                    "id": "hat",
                    "description": "Removable shunt",
                    "quantity": 1,
                    "assembly": "fitted",
                }
            ]
        ),
    )
    build(project, out)
    rows = list(csv.DictReader((out / "BOM.csv").open()))
    assert len(rows) == 3
    assert verify_package(out)["parts"] == 2
    assert normalize("tolerance", "0.25 pF") == {
        "dimension": "capacitance",
        "value": "0.00000000000025",
    }


@pytest.mark.parametrize("fault", ["corrupt", "duplicate", "wrong_board", "missing"])
def test_lock_errors_preserve_output(project, tmp_path, fault):
    out = tmp_path / "out"
    build(project, out)
    before = files(out)
    lock = project.parent / "design.lock.json"
    if fault == "missing":
        lock.unlink()
    elif fault == "corrupt":
        lock.write_text("{bad")
    else:
        d = json.loads(lock.read_text())
        if fault == "duplicate":
            d["assignments"]["stable-second"] = "R1"
        else:
            d["board_id"] = "another-board"
        lock.write_text(json.dumps(d))
    with pytest.raises(ElectricalError):
        build(project, out)
    assert files(out) == before


def test_same_design_concurrent_build_rejected(project, tmp_path):
    fd = os.open(project.parent, os.O_RDONLY)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ElectricalError, match="another build"):
            build(project, tmp_path / "out")
    finally:
        os.close(fd)


def test_publish_failure_preserves_lock_and_output(project, tmp_path, monkeypatch):
    import design2allegro.telesis as t

    out = tmp_path / "out"
    build(project, out)
    before = files(out)
    lock = (project.parent / "design.lock.json").read_bytes()
    actual = t.publish

    def fail(stage, target):
        if target == out:
            raise OSError("injected publish failure")
        return actual(stage, target)

    monkeypatch.setattr(t, "publish", fail)
    with pytest.raises(OSError, match="injected"):
        build(project, out)
    assert (
        files(out) == before
        and (project.parent / "design.lock.json").read_bytes() == lock
    )


def test_lock_commit_failure_rolls_back(project, tmp_path, monkeypatch):
    import design2allegro.annotation as a

    out = tmp_path / "out"
    build(project, out)
    before = files(out)
    lock = (project.parent / "design.lock.json").read_bytes()
    edit(
        project,
        lambda d: d["modules"]["board"]["parts"]["series"].update(id="new-series"),
    )
    actual = a.atomic_json

    def fail(path, data):
        if path.name == "design.lock.json":
            raise OSError("injected lock failure")
        return actual(path, data)

    monkeypatch.setattr(a, "atomic_json", fail)
    with pytest.raises(OSError, match="injected"):
        build(project, out)
    assert (
        files(out) == before
        and (project.parent / "design.lock.json").read_bytes() == lock
    )
    assert not (project.parent / ".design.transaction.json").exists()


def test_interrupted_commit_recovers_forward(project, tmp_path, monkeypatch):
    import design2allegro.annotation as a

    out = tmp_path / "out"
    build(project, out)
    edit(
        project,
        lambda d: d["modules"]["board"]["parts"]["series"].update(id="new-series"),
    )
    actual = a.atomic_json

    def crash(path, data):
        if path.name == "design.lock.json":
            raise KeyboardInterrupt()
        return actual(path, data)

    with monkeypatch.context() as m:
        m.setattr(a, "atomic_json", crash)
        with pytest.raises(KeyboardInterrupt):
            build(project, out)
    assert (project.parent / ".design.transaction.json").exists()
    build(project, out)
    assert refs(out)["new-series"] == "R3"
    assert not (project.parent / ".design.transaction.json").exists()
    assert verify_package(out)["parts"] == 2


@pytest.mark.parametrize(
    "name",
    [
        "components.json",
        "BOM.md",
        "BOM.csv",
        "PINOUT.md",
        "FOOTPRINTS.md",
        "references.json",
    ],
)
def test_artifact_tampering_even_with_rehashed_manifest(project, tmp_path, name):
    out = tmp_path / "out"
    build(project, out)
    p = out / name
    p.write_text(p.read_text() + "tampered\n")
    m = json.loads((out / "manifest.json").read_text())
    m["files"][name] = hashlib.sha256(p.read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(NetlistFormatError, match="artifact"):
        verify_package(out)


def test_old_delivery_readonly_verification(project, tmp_path):
    from design2allegro.telesis import export

    c = compile_design(load_design(project))
    annotated, _ = annotate(
        c, read_lock(project.parent / "design.lock.json", c.data["board_id"])
    )
    # Materialize a genuine v1 physical-key snapshot to retain the reader contract.
    d = annotated.data
    mapping = {k: p["reference"] for k, p in d["parts"].items()}
    mapping.update(
        {
            k: d["parts"][v["ref"]]["reference"] + "." + v["num"]
            for k, v in d["pins"].items()
        }
    )

    def remap(v):
        if isinstance(v, dict):
            return {mapping.get(k, k): remap(x) for k, x in v.items()}
        if isinstance(v, list):
            return [remap(x) for x in v]
        return mapping.get(v, v) if isinstance(v, str) else v

    d = remap(d)
    d["version"] = 1
    for p in d["parts"].values():
        p.pop("reference")
    old = CompiledDesign(canonical(d))
    out = tmp_path / "old"
    export(
        old,
        out,
        {
            "version": 1,
            "parts": {k: {"package": p["footprint"]} for k, p in d["parts"].items()},
        },
        filename="design.tel",
    )
    assert verify_package(out)["parts"] == 2
    build(project, out)
    assert (out / "passive_demo.tel").exists() and not (out / "design.tel").exists()


def test_catalogue_revision_is_pinned(project, tmp_path, monkeypatch):
    import shutil

    root = Path(__file__).resolve().parents[2]
    shared = tmp_path / "shared"
    shutil.copytree(root / "src/design2allegro/libraries", shared)
    monkeypatch.setenv("DESIGN2ALLEGRO_LIBRARY_ROOT", str(shared))
    out = tmp_path / "out"
    build(project, out)
    before = files(out)
    library = shared / "standard/1.json"
    library.write_text(library.read_text() + "\n")
    with pytest.raises(ElectricalError, match="without a version change"):
        build(project, out)
    assert files(out) == before
    newer = json.loads(library.read_text())
    newer["revision"] = "2"
    (shared / "standard/2.json").write_text(json.dumps(newer))
    edit(project, lambda d: d["library"].update(version="2"))
    build(project, out)
    assert refs(out) == {"stable-first": "R1", "stable-second": "R2"}


def test_fixed_model_inheritance_and_conflict(project, tmp_path, monkeypatch):
    import shutil

    root = Path(__file__).resolve().parents[2]
    shared = tmp_path / "shared"
    shutil.copytree(root / "src/design2allegro/libraries", shared)
    monkeypatch.setenv("DESIGN2ALLEGRO_LIBRARY_ROOT", str(shared))
    p = shared / "standard/1.json"
    d = json.loads(p.read_text())
    d["devices"]["generic.resistor"]["properties"] = {
        "resistance": "10 kohm",
        "tolerance": "1 %",
        "power_rating": "0.1 W",
    }
    p.write_text(json.dumps(d))
    edit(project, lambda d: d["modules"]["board"]["parts"]["series"].pop("properties"))
    c = compile_design(load_design(project))
    assert c.check().ok
    assert c.data["parts"]["stable-second"]["properties"]["power_rating"] == "0.1 W"
    edit(
        project,
        lambda d: d["modules"]["board"]["parts"]["pullup"]["properties"].update(
            power_rating="0.25 W"
        ),
    )
    with pytest.raises(ElectricalError, match="fixed device specification conflict"):
        compile_design(load_design(project))


def test_capacitor_voltage_and_tolerance_separate_bom(project, tmp_path):
    def change(d):
        for p in d["modules"]["board"]["parts"].values():
            p.update(
                device="generic.capacitor",
                package="capacitor_0603",
                properties={
                    "capacitance": "100 nF",
                    "voltage_rating": "16 V",
                    "tolerance": "10 %",
                    "dielectric": "X7R",
                    "polarized": False,
                },
            )
        d["modules"]["board"]["parts"]["series"]["properties"][
            "voltage_rating"
        ] = "25 V"

    edit(project, change)
    out = tmp_path / "out"
    build(project, out)
    assert len(list(csv.DictReader((out / "BOM.csv").open()))) == 2
    edit(
        project,
        lambda d: d["modules"]["board"]["parts"]["series"]["properties"].update(
            voltage_rating="16 V", tolerance="5 %"
        ),
    )
    build(project, out)
    assert len(list(csv.DictReader((out / "BOM.csv").open()))) == 2
