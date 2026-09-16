"""Official MB1180 physical-net inventory and L432KC assembly acceptance."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from conftest import write_yaml

from design2allegro import ElectricalError, compile_design, export_design, load_design
from design2allegro.cli import main
from design2allegro.verify import verify_package

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "schematics/nucleo_l432kc"
EXPECTED = json.loads((ROOT / "tests/fixtures/nucleo_l432kc.json").read_text())
WARNINGS = {
    ("ERC.DRIVE", name)
    for name in ("AVDD", "NetC15_2", "NetSB11_1", "NetSB13_1", "V5", "VDD", "VIN")
} | {("ERC.SINGLE", name) for name in ("T_JTDI", "T_JTDO", "T_SWO")}


def compile_board(path=PROJECT):
    return compile_design(load_design(path / "board.yaml"))


def files(path):
    return {
        p.relative_to(path).as_posix(): p.read_bytes()
        for p in path.rglob("*")
        if p.is_file()
    }


def test_complete_official_inventory():
    board = compile_board()
    data = board.data
    assert {name: net["pins"] for name, net in data["nets"].items()} == EXPECTED["nets"]
    assert sorted(p for p, pin in data["pins"].items() if pin["nc"]) == EXPECTED["nc"]
    assert set(data["parts"]) == set(EXPECTED["parts"])
    for ref, part in data["parts"].items():
        expected = EXPECTED["parts"][ref]
        assert sorted(data["pins"][p]["num"] for p in part["pins"]) == expected["pins"]
        assert part["value"] == expected["value"]
        assert part["footprint"] == expected["package"]
    assert {
        data["pins"][p]["num"]: data["pins"][p]["name"]
        for p in data["parts"]["U2"]["pins"]
    } == EXPECTED["target_pinout"]
    assert data["pins"]["U2.33"]["net"] == "GND"
    assert data["pins"]["U3.0"]["net"] == "GND"
    assert len(data["pins"]) == 312
    assert len(data["nets"]) == 82


def test_check_coverage_and_documented_warnings():
    report = compile_board().check()
    assert report.ok
    assert report.data["coverage"]["unscoped_pin_count"] == 0
    warnings = [d for d in report.data["diagnostics"] if d["status"] != "PASS"]
    assert {(d["rule"], d["object"]) for d in warnings} == WARNINGS
    assert all(d["status"] == "FAIL" and d["severity"] == "WARNING" for d in warnings)
    assert json.loads(compile_board().waivers_json) == []


def test_default_assembly_and_conductive_paths():
    data = compile_board().data
    parent = {name: name for name in data["nets"]}

    def find(net):
        if parent[net] != net:
            parent[net] = find(parent[net])
        return parent[net]

    def join(a, b):
        parent[find(data["pins"][a]["net"])] = find(data["pins"][b]["net"])

    for ref, expected in EXPECTED["assembly"].items():
        e = data["parts"][ref]["electrical"]
        assert e["initial_state" if ref.startswith("SB") else "assembly"] == expected
        if ref.startswith("SB") and expected == "closed":
            join(ref + ".1", ref + ".2")
    assert data["parts"]["JP1"]["electrical"]["initial_state"] == "closed"
    join("JP1.1", "JP1.2")
    join("L1.1", "L1.2")
    assert data["parts"]["CN3"]["electrical"]["demo_shunt"] == {
        "pins": ["4", "5"],
        "initial_state": "closed",
        "removable": True,
    }
    join("CN3.4", "CN3.5")
    for a, b in [
        ("U3.4", "U2.1"),
        ("U3.4", "U2.17"),
        ("U3.4", "U2.5"),
        ("U2.16", "U2.33"),
        ("U2.32", "U2.33"),
        ("U2.8", "U5.13"),
        ("U2.25", "U5.12"),
        ("U2.4", "U5.18"),
        ("U2.2", "X1.1"),
        ("U2.3", "X1.2"),
        ("CN4.7", "CN3.8"),
        ("CN4.8", "CN3.7"),
        ("CN3.5", "U2.33"),
    ]:
        assert find(data["pins"][a]["net"]) == find(data["pins"][b]["net"])
    for a, b in [("CN3.10", "U2.2"), ("CN3.11", "U2.3"), ("U2.6", "R5.2")]:
        assert find(data["pins"][a]["net"]) != find(data["pins"][b]["net"])
    # PCB nets on either side of a fitted jumper remain separate.
    assert data["pins"]["JP1.1"]["net"] != data["pins"]["JP1.2"]["net"]
    for ref in ("C3", "R13", "CN2"):
        assert data["parts"][ref]["electrical"]["assembly"] == "dnp"
    assert data["pins"]["C3.1"]["net"] == "MCO"
    assert data["pins"]["CN2.1"]["net"] == "STM_JTMS"


@pytest.fixture
def project(tmp_path):
    target = tmp_path / "nucleo_l432kc"
    shutil.copytree(PROJECT, target)
    return target


def change_connections(project, ref, first, second=None, disconnect=False):
    path = project / "board.yaml"
    doc = yaml.safe_load(path.read_text())
    components = yaml.safe_load((project / "components.yaml").read_text())["components"]
    names = components[ref]["pins"]
    first_name = names[first]["name"]
    second_name = names[second]["name"] if second else None
    for module in doc["modules"].values():
        for net in module.get("nets", {}).values():
            for ep in list(net["endpoints"]):
                if ep.get("part") != ref:
                    continue
                if ep.get("pin") == first_name:
                    if disconnect:
                        net["endpoints"].remove(ep)
                        module["nc"].append(ep)
                    else:
                        ep["pin"] = second_name
                elif ep.get("pin") == second_name:
                    ep["pin"] = first_name
    write_yaml(path, doc)


@pytest.mark.parametrize(
    "fault",
    ["swd", "usb", "uart", "supply", "ground", "bridge", "short", "resistor", "dnp"],
)
def test_faults_block_export_without_replacing_package(project, tmp_path, fault):
    out = tmp_path / "output"
    export_design(compile_board(project), out)
    before = files(out)
    if fault in ("swd", "usb", "uart"):
        ref, a, b = {
            "swd": ("U2", "23", "24"),
            "usb": ("CN1", "2", "3"),
            "uart": ("U5", "12", "13"),
        }[fault]
        change_connections(project, ref, a, b)
    elif fault in ("supply", "ground"):
        change_connections(
            project, "U2", "17" if fault == "supply" else "33", disconnect=True
        )
    elif fault == "short":
        # Incorrectly put both sides of the open SB4 on the MCO network.
        path = project / "board.yaml"
        doc = yaml.safe_load(path.read_text())
        target = doc["modules"]["target"]
        ep = next(
            e for e in target["nets"]["NetSB4_2"]["endpoints"] if e.get("part") == "SB4"
        )
        target["nets"]["NetSB4_2"]["endpoints"].remove(ep)
        target["nets"]["MCO"]["endpoints"].append(ep)
        write_yaml(path, doc)
    else:
        path = project / "components.yaml"
        doc = yaml.safe_load(path.read_text())
        ref, key, value = {
            "bridge": ("SB5", "initial_state", "open"),
            "resistor": ("R1", "resistance", "100 ohm"),
            "dnp": ("R13", "assembly", "fitted"),
        }[fault]
        doc["components"][ref]["electrical"][key] = value
        write_yaml(path, doc)
    board = compile_board(project)
    assert not board.check().ok
    with pytest.raises(ElectricalError, match="DRC blocked"):
        export_design(board, out)
    assert main(["build", str(project / "board.yaml"), "-o", str(out), "--json"]) == 2
    assert files(out) == before


def test_board_named_deterministic_package(tmp_path):
    out = tmp_path / "arbitrary_output_name"
    board = compile_board()
    export_design(board, out)
    assert (out / "nucleo_l432kc.tel").is_file()
    assert not (out / "design.tel").exists()
    assert verify_package(out) == {"parts": 89, "pins": 312, "nets": 82}
    before = files(out)
    export_design(board, out)
    assert files(out) == before
