"""Final netlist contracts use physical readback and block publication on failure."""

import copy
import hashlib
import json

import pytest
from conftest import write_circuit

from design2allegro import compile_design, export_design, load_design
from design2allegro.cli import main
from design2allegro.expectations import FILENAME, validate_expectations
from design2allegro.model import CompiledDesign, ElectricalError, canonical
from design2allegro.syntax import parse
from design2allegro.verify import NetlistFormatError, verify_package


@pytest.fixture
def project(make_board, tmp_path):
    make_board(
        {
            "A": {"1": "PASSIVE", "2": "PASSIVE", "3": "PASSIVE"},
            "B": {"1": "PASSIVE", "2": "PASSIVE"},
        },
        {"X": [("A", "1"), ("B", "1")], "Y": [("A", "2"), ("B", "2")]},
        nc=[("A", "3")],
    )
    expected = {
        "version": 1,
        "board_id": "test-board",
        "parts": {
            "U1": {"package": "PKG_A", "pins": ["1", "2", "3"]},
            "U2": {"package": "PKG_B", "pins": ["1", "2"]},
        },
        "nets": {"X": ["U1.1", "U2.1"], "Y": ["U1.2", "U2.2"]},
        "nc": ["U1.3"],
    }
    (tmp_path / FILENAME).write_text(json.dumps(expected))
    path = tmp_path / "board.circuit"
    doc = parse(path.read_text())
    doc["netlist_expectations"] = FILENAME
    write_circuit(path, doc)
    return path, expected


def compile_project(path):
    return compile_design(load_design(path, library_root=path.parent / "catalogs"))


def contents(path):
    return {
        p.relative_to(path).as_posix(): p.read_bytes()
        for p in path.rglob("*")
        if p.is_file()
    }


def test_roundtrip_frozen_contract_and_provenance(project, tmp_path):
    path, expected = project
    compiled = compile_project(path)
    assert str(tmp_path / FILENAME) in compiled.data["inputs"]
    # Export must use the loaded snapshot, even if its original source disappears.
    (tmp_path / FILENAME).unlink()
    output = tmp_path / "out"
    result = export_design(compiled, output)
    assert FILENAME in result["files"]
    assert json.loads((output / FILENAME).read_text()) == expected
    assert verify_package(output) == {"parts": 2, "pins": 5, "nets": 2}
    assert main(["verify", str(output), "--json"]) == 0


@pytest.mark.parametrize(
    "fault", ["connection", "missing_net", "part", "pin", "package", "nc"]
)
def test_contract_failure_preserves_package_and_lock(project, tmp_path, fault):
    path, expected = project
    output = tmp_path / "out"
    export_design(compile_project(path), output)
    before = contents(output)
    lock = (tmp_path / "design.lock.json").read_bytes()
    if fault == "connection":
        expected["nets"]["X"][0], expected["nets"]["Y"][0] = "U1.2", "U1.1"
    elif fault == "missing_net":
        expected["nets"]["X"] += expected["nets"].pop("Y")
    elif fault == "part":
        expected["parts"]["U3"] = {"package": "EXTRA", "pins": ["1"]}
        expected["nc"].append("U3.1")
    elif fault == "pin":
        expected["parts"]["U1"]["pins"].append("4")
        expected["nc"].append("U1.4")
    elif fault == "package":
        expected["parts"]["U1"]["package"] = "WRONG"
    else:
        expected["nc"] = ["U1.1"]
        expected["nets"]["X"][0] = "U1.3"
    (tmp_path / FILENAME).write_text(json.dumps(expected))
    with pytest.raises(NetlistFormatError, match="final netlist expectations failed"):
        export_design(compile_project(path), output)
    assert contents(output) == before
    assert (tmp_path / "design.lock.json").read_bytes() == lock
    assert not (tmp_path / ".design.transaction.json").exists()


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "json",
        "duplicate",
        "field",
        "board",
        "overlap",
        "incomplete",
        "absolute",
    ],
)
def test_invalid_source_contract(project, tmp_path, fault, capsys):
    path, expected = project
    contract = tmp_path / FILENAME
    if fault == "missing":
        contract.unlink()
    elif fault == "json":
        contract.write_text("{")
    elif fault == "duplicate":
        contract.write_text('{"version":1,"version":1}')
    elif fault == "absolute":
        path.write_text(path.read_text().replace(FILENAME, str(contract)))
    else:
        if fault == "field":
            expected["typo"] = True
        elif fault == "board":
            expected["board_id"] = "other"
        elif fault == "overlap":
            expected["nc"].append("U1.1")
        else:
            expected["nc"] = []
        contract.write_text(json.dumps(expected))
    with pytest.raises(ElectricalError):
        compile_project(path)
    assert main(["build", str(path), "-o", str(tmp_path / "out"), "--json"]) == 2
    error = json.loads(capsys.readouterr().err)
    assert error["ok"] is False
    assert "netlist" in error["error"]
    assert not (tmp_path / "out").exists()
    assert not (tmp_path / "design.lock.json").exists()


def rehash(output):
    manifest = json.loads((output / "manifest.json").read_text())
    for name in manifest["files"]:
        manifest["files"][name] = hashlib.sha256(
            (output / name).read_bytes()
        ).hexdigest()
    (output / "manifest.json").write_text(json.dumps(manifest))


def test_rehashed_wrong_netlist_is_checked_against_contract(project, tmp_path):
    path, _ = project
    output = tmp_path / "out"
    export_design(compile_project(path), output)
    tel = next(output.glob("*.tel"))
    text = (
        tel.read_text()
        .replace("U1.1", "TEMP")
        .replace("U1.2", "U1.1")
        .replace("TEMP", "U1.2")
    )
    tel.write_text(text)
    rehash(output)
    with pytest.raises(
        NetlistFormatError, match=r"net X: missing=\['U1.1'\], extra=\['U1.2'\]"
    ):
        verify_package(output)


def test_consistently_wrong_compiler_graph_is_blocked(project, tmp_path):
    path, _ = project
    compiled = compile_project(path)
    data = compiled.data
    data["nets"]["X"]["pins"] = ["A.2", "B.1"]
    data["nets"]["Y"]["pins"] = ["A.1", "B.2"]
    data["pins"]["A.1"]["net"] = "Y"
    data["pins"]["A.2"]["net"] = "X"
    wrong = CompiledDesign(
        canonical(data),
        compiled.rules_json,
        compiled.waivers_json,
        compiled.design_path,
    )
    with pytest.raises(NetlistFormatError, match="final netlist expectations failed"):
        export_design(wrong, tmp_path / "out")
    assert not (tmp_path / "design.lock.json").exists()


@pytest.mark.parametrize("fault", ["missing", "changed", "duplicate"])
def test_packaged_contract_cannot_be_silently_dropped_or_changed(
    project, tmp_path, fault
):
    path, _ = project
    output = tmp_path / "out"
    export_design(compile_project(path), output)
    file = output / FILENAME
    if fault == "missing":
        file.unlink()
        manifest = json.loads((output / "manifest.json").read_text())
        del manifest["files"][FILENAME]
        (output / "manifest.json").write_text(json.dumps(manifest))
    elif fault == "changed":
        data = json.loads(file.read_text())
        data["parts"]["U1"]["package"] = "CHANGED"
        file.write_text(json.dumps(data))
    else:
        file.write_text(
            file.read_text().replace('"version":1', '"version":1,"version":1')
        )
    rehash(output)
    with pytest.raises(NetlistFormatError, match="expectations"):
        verify_package(output)


def test_expectation_order_is_irrelevant(project, tmp_path):
    path, expected = project
    changed = copy.deepcopy(expected)
    changed["parts"]["U1"]["pins"].reverse()
    changed["nets"]["X"].reverse()
    assert validate_expectations(changed, "test-board") == changed
    (tmp_path / FILENAME).write_text(json.dumps(changed))
    export_design(compile_project(path), tmp_path / "out")
    assert verify_package(tmp_path / "out")["pins"] == 5
