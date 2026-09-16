"""Version 2 schema, hierarchy, shared libraries and delivery regressions."""

import copy
import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml
from conftest import write_yaml

from design2allegro import ElectricalError, compile_design, export_design, load_design
from design2allegro.cli import main
from design2allegro.verify import (
    NetlistFormatError,
    parse_device,
    parse_netlist,
    verify_package,
)

ROOT = Path(__file__).resolve().parents[2]
LEFT = "fpga/endpoint/chip"
RIGHT = "soc/endpoint/chip"


@pytest.fixture
def project(tmp_path, monkeypatch):
    shutil.copytree(
        ROOT / "tests/fixtures/fpga_soc",
        tmp_path / "project",
        ignore=shutil.ignore_patterns("design.lock.json", ".design.*"),
    )
    shutil.copytree(ROOT / "src/design2allegro/libraries", tmp_path / "catalogs")
    monkeypatch.setenv("DESIGN2ALLEGRO_LIBRARY_ROOT", str(tmp_path / "catalogs"))
    return tmp_path / "project/board.yaml"


def edit(path, fn):
    doc = yaml.safe_load(path.read_text())
    fn(doc)
    write_yaml(path, doc)


def edit_library(project, fn):
    p = project.parent.parent / "catalogs/standard/1.json"
    d = json.loads(p.read_text())
    fn(d["devices"]["synthetic.fpga_soc"])
    p.write_text(json.dumps(d))


def compiled(path):
    return compile_design(load_design(path))


def files(path):
    return {
        p.relative_to(path).as_posix(): p.read_bytes()
        for p in path.rglob("*")
        if p.is_file()
    }


def test_hierarchy_bus_order_and_identity(project):
    c = compiled(project)
    assert len(c.data["parts"]) == 2 and len(c.data["pins"]) == 20
    assert c.data["nets"]["DATA[0]"]["pins"] == [LEFT + ".D0", RIGHT + ".D0"]
    assert c.data["pins"][LEFT + ".SPARE"]["nc"]
    assert c.data["hierarchy"]["fpga/endpoint/chip"] == LEFT
    assert c.data["net_aliases"]["soc/endpoint/data[0]"] == "DATA[0]"
    assert all("reference" not in p for p in c.data["parts"].values())
    edit(
        project, lambda d: d.update(modules=dict(reversed(list(d["modules"].items()))))
    )
    assert compiled(project).digest == c.digest


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda d: d.update(typo=1), "Additional properties"),
        (lambda d: d.update(version=True), "version"),
        (lambda d: d.update(version=1), "retired"),
        (lambda d: d.update(references={"x": "U1"}), "Additional properties"),
        (lambda d: d.update(top="missing"), "unknown top"),
        (
            lambda d: d["modules"]["wrapper"]["instances"]["endpoint"].update(
                module="wrapper"
            ),
            "recursive",
        ),
        (
            lambda d: d["modules"]["wrapper"]["instances"]["endpoint"].update(
                module="missing"
            ),
            "unknown module",
        ),
        (
            lambda d: d["modules"]["endpoint"]["parts"]["chip"].update(
                device="missing"
            ),
            "unknown device",
        ),
        (
            lambda d: d["modules"]["endpoint"]["ports"]["data"].update(width=3),
            "width mismatch",
        ),
        (
            lambda d: d["modules"]["board"]["nets"].update(
                EXTRA=copy.deepcopy(d["modules"]["board"]["nets"]["DATA"])
            ),
            "multiple nets",
        ),
        (
            lambda d: d["modules"]["endpoint"]["nc"].append(
                {"part": "chip", "pin": "D0"}
            ),
            "NC conflicts",
        ),
        (lambda d: d["modules"]["endpoint"].update(nc=[]), "unconnected endpoint"),
        (
            lambda d: d["modules"]["endpoint"]["nets"]["clk"]["endpoints"][1].update(
                pin="MISSING"
            ),
            "unknown logical pin",
        ),
        (
            lambda d: d["modules"]["board"]["instances"]["soc"].update(id="fpga"),
            "duplicate module instance ID",
        ),
        (
            lambda d: d["modules"]["endpoint"]["parts"].update(
                copy=copy.deepcopy(d["modules"]["endpoint"]["parts"]["chip"])
            ),
            "duplicate stable identity",
        ),
        (lambda d: d["library"].update(version="missing"), "unavailable"),
    ],
)
def test_invalid_designs(project, change, match):
    edit(project, change)
    with pytest.raises(ElectricalError, match=match):
        compiled(project)


@pytest.mark.parametrize(
    "text,match",
    [
        ("version: 2\nversion: 2\n", "duplicate YAML key"),
        ("x: !!python/object/apply:os.system [echo unsafe]\n", "could not determine"),
        ("x: &x [1]\ny: *x\n", "aliases are not supported"),
        ("version: [\n", "line"),
    ],
)
def test_yaml_rejections(tmp_path, text, match):
    p = tmp_path / "bad.yaml"
    p.write_text(text)
    with pytest.raises(ElectricalError, match=match) as exc:
        load_design(p)
    assert str(p) in str(exc.value)


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda d: d["groups"].update(DATA=["D0", "D0"]), "pin group"),
        (lambda d: d["packages"]["bga10"]["pads"].update({"11": "D0"}), "exactly once"),
        (
            lambda d: d["packages"]["bga10"].update(allegro="bad package"),
            "package binding",
        ),
        (lambda d: d["pins"]["D0"].update(type="bad"), "not one of"),
        (lambda d: d.update(category="mystery"), "category"),
    ],
)
def test_invalid_library(project, change, match):
    edit_library(project, change)
    with pytest.raises(ElectricalError, match=match):
        compiled(project)


def test_deterministic_delivery_and_corruption(project, tmp_path):
    c = compiled(project)
    out = tmp_path / "out"
    m = export_design(c, out)
    assert not m["allegro_import_verified"] and m["version"] == 2
    assert verify_package(out) == {"parts": 2, "pins": 20, "nets": 9}
    before = files(out)
    assert export_design(c, out) == m
    assert files(out) == before
    assert {
        "components.json",
        "BOM.md",
        "BOM.csv",
        "PINOUT.md",
        "FOOTPRINTS.md",
        "references.json",
    } <= set(before)
    (out / "fpga_soc.tel").write_text("$END\n")
    with pytest.raises(NetlistFormatError, match="digest mismatch"):
        verify_package(out)


def test_ddr_error_blocks_and_preserves(project, tmp_path):
    out = tmp_path / "out"
    export_design(compiled(project), out)
    before = files(out)
    edit(
        project.parent / "rules.yaml",
        lambda d: d["rules"][0]["params"]["memory"][0]["dq"].reverse(),
    )
    assert not compiled(project).check().ok
    with pytest.raises(ElectricalError, match="blocked"):
        export_design(compiled(project), out)
    assert files(out) == before


def test_output_protection(project, tmp_path):
    out = tmp_path / "out"
    c = compiled(project)
    export_design(c, out)
    (out / "user.txt").write_text("keep")
    with pytest.raises(ElectricalError, match="unmanaged"):
        export_design(c, out)
    assert (out / "user.txt").read_text() == "keep"
    link = tmp_path / "link"
    link.symlink_to(out, target_is_directory=True)
    with pytest.raises(ElectricalError, match="symlink"):
        export_design(c, link)


def test_cli(project, tmp_path, capsys):
    out = tmp_path / "out"
    assert main(["check", str(project), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    assert not (project.parent / "design.lock.json").exists()
    assert main(["build", str(project), "-o", str(out), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["manifest"]["strict"]
    assert main(["verify", str(out), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["statistics"]["parts"] == 2
    edit(project, lambda d: d.update(top="absent"))
    assert main(["check", str(project), "--json"]) == 2
    capsys.readouterr()
    assert main(["check", str(project.parent / "absent.yaml"), "--json"]) == 1
    capsys.readouterr()
    assert main(["build", str(project), "--json"]) == 2


def test_handwritten_telesis_fixture():
    parts, nets = parse_netlist(
        "$PACKAGES\n'BGA2' ! 'TEST' ; U1\n$NETS\nVCC ; U1.A1\n$END\n"
    )
    assert parts == {"U1": {"package": "BGA2", "device": "TEST"}} and nets == {
        "VCC": {"U1.A1"}
    }
    assert parse_device(
        "PACKAGE 'BGA2'\nCLASS IC\nPINCOUNT 2\nPINORDER main ,PWR,DATA\nFUNCTION main main ,A1,B2\nEND\n"
    ) == ("BGA2", {"A1": "PWR", "B2": "DATA"})


def test_erc_blocks(make_board, tmp_path):
    c = make_board(
        {"U1": {"1": "OUTPUT"}, "U2": {"1": "OUTPUT"}},
        {"CLASH": [("U1", "1"), ("U2", "1")]},
    )
    with pytest.raises(ElectricalError):
        export_design(c, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()


def test_no_legacy_runtime():
    import sys

    assert not any(
        n == "skidl" or n.startswith("skidl.") or n == "_skidl_native"
        for n in sys.modules
    )


def test_actual_ddr_wiring_swap(project):
    edit_library(
        project, lambda d: d["groups"].update(SWAPPED=["D1", "D0", "D2", "D3"])
    )

    def change(d):
        d["modules"]["other_endpoint"] = copy.deepcopy(d["modules"]["endpoint"])
        d["modules"]["other_endpoint"]["nets"]["data"]["endpoints"][1][
            "group"
        ] = "SWAPPED"
        d["modules"]["other_wrapper"] = copy.deepcopy(d["modules"]["wrapper"])
        d["modules"]["other_wrapper"]["instances"]["endpoint"][
            "module"
        ] = "other_endpoint"
        d["modules"]["board"]["instances"]["soc"]["module"] = "other_wrapper"

    edit(project, change)
    c = compiled(project)
    assert c.data["nets"]["DATA[0]"]["pins"] == [LEFT + ".D0", RIGHT + ".D1"]
    assert not c.check().ok


def test_hierarchical_short_is_not_silent(project):
    def change(d):
        d["modules"]["endpoint"]["nets"]["clk"]["endpoints"].append({"port": "rst"})
        d["modules"]["endpoint"]["nets"]["rst"]["endpoints"].pop(0)

    edit(project, change)
    with pytest.raises(ElectricalError, match="distinct nets"):
        compiled(project)


def test_readback_detects_changed_connectivity_with_updated_hash(project, tmp_path):
    out = tmp_path / "out"
    export_design(compiled(project), out)
    tel = out / "fpga_soc.tel"
    tel.write_text(
        tel.read_text()
        .replace("U2.1\n", "U2.TEMP\n")
        .replace("U2.2\n", "U2.1\n")
        .replace("U2.TEMP\n", "U2.2\n")
    )
    m = json.loads((out / "manifest.json").read_text())
    m["files"][tel.name] = hashlib.sha256(tel.read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps(m))
    with pytest.raises(NetlistFormatError, match="connectivity mismatch"):
        verify_package(out)


def test_external_rules_and_waivers(project):
    edit(
        project.parent / "rules.yaml",
        lambda d: d["rules"].append(
            {"id": "SPARE", "kind": "required", "scope": [LEFT + ".SPARE"]}
        ),
    )
    assert not compiled(project).check().ok
    edit(project, lambda d: d.update(waivers="waivers.yaml"))
    write_yaml(
        project.parent / "waivers.yaml",
        [
            {
                "rule": "SPARE",
                "object": LEFT + ".SPARE",
                "reason": "Reserved NC",
                "owner": "board-team",
            }
        ],
    )
    assert compiled(project).check().ok
    edit(project.parent / "waivers.yaml", lambda d: d[0].update(expires="2000-01-01"))
    assert not compiled(project).check().ok


def test_integral_bus_width(project):
    edit(project, lambda d: d["modules"]["endpoint"]["ports"]["data"].update(width=4.0))
    assert compiled(project).check().ok


def test_board_name_is_explicit(project, tmp_path):
    edit(project, lambda d: d.update(name="renamed-board"))
    out = tmp_path / "unrelated"
    export_design(compiled(project), out)
    assert (out / "renamed-board.tel").is_file()
    edit(project, lambda d: d.update(name="../unsafe"))
    with pytest.raises(ElectricalError):
        compiled(project)
