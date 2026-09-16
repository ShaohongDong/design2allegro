"""Official physical inventory remains independent of generated annotation."""

import json
import shutil
from pathlib import Path

import pytest
import yaml
from conftest import write_yaml

from design2allegro import ElectricalError, compile_design, export_design, load_design

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "schematics/nucleo_l432kc"
EXPECTED = json.loads((ROOT / "tests/fixtures/nucleo_l432kc.json").read_text())
WARNINGS = {
    ("ERC.DRIVE", n)
    for n in ("AVDD", "NetC15_2", "NetSB11_1", "NetSB13_1", "V5", "VDD", "VIN")
} | {("ERC.SINGLE", n) for n in ("T_JTDI", "T_JTDO", "T_SWO")}


def compile_board(path=PROJECT):
    return compile_design(load_design(path / "board.yaml"))


def functional_parts(data):
    return {"/".join(part["hierarchy"]): part for part in data["parts"].values()}


def physical_pins(data):
    return {
        "/".join(data["parts"][pin["ref"]]["hierarchy"]) + "." + pin["num"]: pin
        for pin in data["pins"].values()
    }


def test_complete_official_inventory():
    data = compile_board().data
    parts = functional_parts(data)
    pins = physical_pins(data)
    endpoints = {pin["id"]: name for name, pin in pins.items()}
    assert {
        name: sorted(endpoints[p] for p in net["pins"])
        for name, net in data["nets"].items()
    } == EXPECTED["nets"]
    assert sorted(name for name, pin in pins.items() if pin["nc"]) == EXPECTED["nc"]
    assert set(parts) == set(EXPECTED["parts"])
    for name, part in parts.items():
        assert (
            sorted(data["pins"][p]["num"] for p in part["pins"])
            == EXPECTED["parts"][name]["pins"]
        )
        assert part["footprint"] == EXPECTED["parts"][name]["package"]
        assert "reference" not in part
    for name in ("target/target_mcu.33", "power/target_regulator.0"):
        assert pins[name]["net"] == "GND"
    target = parts["target/target_mcu"]
    assert {
        data["pins"][p]["num"]: data["pins"][p]["name"] for p in target["pins"]
    } == EXPECTED["target_pinout"]
    assert len(data["parts"]) == 89
    assert len(data["pins"]) == 312 and len(data["nets"]) == 82


def test_strict_attribute_gate_preserves_electrical_results(tmp_path):
    board = compile_board()
    report = board.check().data
    missing = [d for d in report["diagnostics"] if d["rule"] == "PROPERTY.REQUIRED"]
    assert missing and not report["ok"]
    assert report["coverage"]["unscoped_pin_count"] == 0
    assert {
        (d["rule"], d["object"])
        for d in report["diagnostics"]
        if d["status"] != "PASS" and d["rule"] != "PROPERTY.REQUIRED"
    } == WARNINGS
    assert all(d["severity"] == "ERROR" for d in missing)
    out = tmp_path / "existing"
    out.mkdir()
    (out / "keep").write_text("preserve")
    with pytest.raises(ElectricalError, match="missing required property"):
        export_design(board, out)
    assert (out / "keep").read_text() == "preserve"
    assert not (PROJECT / "design.lock.json").exists()


def test_default_assembly_and_conductive_paths():
    data = compile_board().data

    parts = functional_parts(data)
    pins = physical_pins(data)

    def part(path):
        return parts[path]

    def pin(path):
        return pins[path]

    parent = {n: n for n in data["nets"]}

    def find(n):
        if parent[n] != n:
            parent[n] = find(parent[n])
        return parent[n]

    def join(a, b):
        parent[find(pin(a)["net"])] = find(pin(b)["net"])

    for ref, expected in EXPECTED["assembly"].items():
        assert (
            part(ref)["electrical"][
                "initial_state" if expected in ("open", "closed") else "assembly"
            ]
            == expected
        )
        if expected == "closed":
            join(ref + ".1", ref + ".2")
    join("power/current_measurement_jumper.1", "power/current_measurement_jumper.2")
    join("target/analog_supply_bead.1", "target/analog_supply_bead.2")
    join("interfaces/arduino_right.4", "interfaces/arduino_right.5")
    for a, b in [
        ("power/target_regulator.4", "target/target_mcu.1"),
        ("power/target_regulator.4", "target/target_mcu.17"),
        ("power/target_regulator.4", "target/target_mcu.5"),
        ("target/target_mcu.16", "target/target_mcu.33"),
        ("target/target_mcu.32", "target/target_mcu.33"),
        ("target/target_mcu.8", "stlink/debug_mcu.13"),
        ("target/target_mcu.25", "stlink/debug_mcu.12"),
        ("target/target_mcu.4", "stlink/debug_mcu.18"),
        ("target/target_mcu.2", "target/rtc_crystal.1"),
        ("target/target_mcu.3", "target/rtc_crystal.2"),
        ("interfaces/arduino_left.7", "interfaces/arduino_right.8"),
        ("interfaces/arduino_left.8", "interfaces/arduino_right.7"),
        ("interfaces/arduino_right.5", "target/target_mcu.33"),
    ]:
        assert find(pin(a)["net"]) == find(pin(b)["net"])
    for a, b in [
        ("interfaces/arduino_right.10", "target/target_mcu.2"),
        ("interfaces/arduino_right.11", "target/target_mcu.3"),
        ("target/target_mcu.6", "stlink/resistor_mco.2"),
    ]:
        assert find(pin(a)["net"]) != find(pin(b)["net"])
    assert (
        pin("power/current_measurement_jumper.1")["net"]
        != pin("power/current_measurement_jumper.2")["net"]
    )
    for ref in (
        "stlink/capacitor_mco",
        "stlink/resistor_link_2",
        "interfaces/debug_programming_header",
    ):
        assert part(ref)["assembly"] == "dnp"
    assert data["accessories"][0]["quantity"] == 1


@pytest.fixture
def project(tmp_path):
    shutil.copytree(PROJECT, tmp_path / "board")
    return tmp_path / "board"


def change_connections(doc, ref, first, second=None, disconnect=False):
    module_name, part_name = ref.split("/")
    module = doc["modules"][module_name]
    a, b = first, second
    for net in module["nets"].values():
        for ep in list(net["endpoints"]):
            if ep.get("part") != part_name:
                continue
            if ep.get("pin") == a:
                if disconnect:
                    net["endpoints"].remove(ep)
                    module["nc"].append(ep)
                else:
                    ep["pin"] = b
            elif ep.get("pin") == b:
                ep["pin"] = a


@pytest.mark.parametrize(
    "ref,a,b",
    [
        ("target/target_mcu", "PA13", "PA14"),
        ("interfaces/usb_connector", "DM", "DP"),
        ("stlink/debug_mcu", "PA2", "PA3"),
        ("target/target_mcu", "VDD_17", None),
        ("target/target_mcu", "EP_GND", None),
    ],
)
def test_connection_faults_still_detected(project, ref, a, b):
    path = project / "board.yaml"
    doc = yaml.safe_load(path.read_text())
    change_connections(doc, ref, a, b, disconnect=b is None)
    write_yaml(path, doc)
    report = compile_board(project).check().data
    assert any(
        d["status"] == "FAIL"
        and d["severity"] == "ERROR"
        and d["rule"] != "PROPERTY.REQUIRED"
        for d in report["diagnostics"]
    )


@pytest.mark.parametrize(
    "ref,field,value",
    [
        ("target/jumper_link", "initial_state", "open"),
        ("stlink/resistor_usb_dp", "resistance", "100 ohm"),
        ("stlink/resistor_link_2", "assembly", "fitted"),
    ],
)
def test_assembly_and_specification_faults(project, ref, field, value):
    path = project / "board.yaml"
    doc = yaml.safe_load(path.read_text())
    module_name, part_name = ref.split("/")
    part = doc["modules"][module_name]["parts"][part_name]
    if field == "assembly":
        part[field] = value
    else:
        part["properties"][field] = value
    write_yaml(path, doc)
    if ref == "stlink/resistor_usb_dp":
        with pytest.raises(
            ElectricalError, match="fixed device specification conflict"
        ):
            compile_board(project)
    else:
        report = compile_board(project).check().data
        assert any(
            d["status"] == "FAIL"
            and d["severity"] == "ERROR"
            and d["rule"] != "PROPERTY.REQUIRED"
            for d in report["diagnostics"]
        )
