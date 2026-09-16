import copy
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

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


@pytest.fixture
def project(tmp_path):
    shutil.copytree(EXAMPLES / "fpga_soc", tmp_path / "project")
    return tmp_path / "project" / "board.yaml"


def edit(path, fn):
    doc = yaml.safe_load(path.read_text())
    fn(doc)
    write_yaml(path, doc)


def test_hierarchy_bus_order_and_refs(project):
    c = compile_design(load_design(project))
    assert len(c.data["parts"]) == 2
    assert len(c.data["pins"]) == 20
    assert c.data["nets"]["DATA[0]"]["pins"] == ["U1.1", "U2.1"]
    assert c.data["nets"]["DATA[3]"]["pins"] == ["U1.4", "U2.4"]
    assert c.data["pins"]["U1.10"]["nc"]
    assert c.data["hierarchy"]["fpga/endpoint/chip"] == "U1"
    assert c.data["net_aliases"]["soc/endpoint/data[0]"] == "DATA[0]"
    edit(
        project, lambda d: d.update(modules=dict(reversed(list(d["modules"].items()))))
    )
    assert compile_design(load_design(project)).digest == c.digest


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda d: d.update(typo=1), "Additional properties"),
        (lambda d: d.update(version=True), "/version"),
        (lambda d: d.update(top="missing"), "unknown top"),
        (lambda d: d["references"].pop("soc/endpoint/chip"), "missing board reference"),
        (lambda d: d["references"].update({"unused": "R1"}), "unused reference"),
        (
            lambda d: d["references"].update({"soc/endpoint/chip": "u1"}),
            "reference collision",
        ),
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
                component="missing"
            ),
            "unknown component",
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
    ],
)
def test_invalid_designs(project, change, match):
    edit(project, change)
    with pytest.raises(ElectricalError, match=match):
        compile_design(load_design(project))


@pytest.mark.parametrize(
    "text,match",
    [
        ("version: 1\nversion: 1\n", "duplicate YAML key"),
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
        (
            lambda d: d["components"]["SYNTH_FPGA_SOC"]["pins"].update(
                {"11": {"name": "D0", "type": "INPUT"}}
            ),
            "logical pin",
        ),
        (
            lambda d: d["components"]["SYNTH_FPGA_SOC"]["groups"].update(
                DATA=["1", "1"]
            ),
            "pin group",
        ),
        (
            lambda d: d["components"]["SYNTH_FPGA_SOC"]["pins"].update(
                {11: {"name": "SPARE2", "type": "INPUT"}}
            ),
            "keys must be strings",
        ),
        (
            lambda d: d["components"]["SYNTH_FPGA_SOC"].update(package="bad package"),
            "does not match",
        ),
    ],
)
def test_invalid_library(project, change, match):
    edit(project.parent / "components.yaml", change)
    with pytest.raises(ElectricalError, match=match):
        load_design(project)


def test_deterministic_delivery_and_corruption(project, tmp_path):
    c = compile_design(load_design(project))
    target = tmp_path / "output"
    manifest = export_design(c, target)
    assert not manifest["allegro_import_verified"]
    assert verify_package(target) == {"parts": 2, "pins": 20, "nets": 9}
    before = {
        p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()
    }
    assert export_design(c, target) == manifest
    assert before == {
        p.relative_to(target): p.read_bytes() for p in target.rglob("*") if p.is_file()
    }
    (target / "design.tel").write_text("$END\n")
    with pytest.raises(NetlistFormatError, match="digest mismatch"):
        verify_package(target)


def test_ddr_error_blocks_and_preserves(project, tmp_path):
    c = compile_design(load_design(project))
    target = tmp_path / "output"
    export_design(c, target)
    before = (target / "manifest.json").read_bytes()
    edit(
        project.parent / "rules.yaml",
        lambda d: d["rules"][0]["params"]["memory"][0]["dq"].reverse(),
    )
    bad = compile_design(load_design(project))
    assert not bad.check().ok
    with pytest.raises(ElectricalError, match="blocked"):
        export_design(bad, target)
    assert (target / "manifest.json").read_bytes() == before


def test_output_protection(project, tmp_path):
    c = compile_design(load_design(project))
    out = tmp_path / "output"
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
    target = tmp_path / "output"
    assert main(["check", str(project), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"]
    assert main(["build", str(project), "-o", str(target), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["manifest"]["strict"]
    assert main(["verify", str(target), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["statistics"]["parts"] == 2
    edit(project, lambda d: d.update(top="absent"))
    assert main(["check", str(project), "--json"]) == 2
    assert not json.loads(capsys.readouterr().err)["ok"]
    assert main(["check", str(project.parent / "absent.yaml"), "--json"]) == 1
    assert json.loads(capsys.readouterr().err)["exit_code"] == 1
    assert main(["build", str(project), "--json"]) == 2
    assert json.loads(capsys.readouterr().err)["exit_code"] == 2


def test_handwritten_telesis_fixture():
    parts, nets = parse_netlist(
        "$PACKAGES\n'BGA2' ! 'TEST' ; U1\n$NETS\nVCC ; U1.A1\n$END\n"
    )
    assert parts == {"U1": {"package": "BGA2", "device": "TEST"}}
    assert nets == {"VCC": {"U1.A1"}}
    assert parse_device(
        "PACKAGE 'BGA2'\nCLASS IC\nPINCOUNT 2\nPINORDER main ,PWR,DATA\nFUNCTION main main ,A1,B2\nEND\n"
    ) == ("BGA2", {"A1": "PWR", "B2": "DATA"})


def test_erc_blocks(make_board, tmp_path):
    c = make_board(
        {"U1": {"1": "OUTPUT"}, "U2": {"1": "OUTPUT"}},
        {"CLASH": [("U1", "1"), ("U2", "1")]},
    )
    assert not c.check().ok
    with pytest.raises(ElectricalError):
        export_design(c, tmp_path / "blocked")
    assert not (tmp_path / "blocked").exists()


def test_no_legacy_runtime():
    import sys

    assert not any(
        name == "skidl" or name.startswith("skidl.") or name == "_skidl_native"
        for name in sys.modules
    )


def test_actual_ddr_wiring_swap(project, tmp_path, capsys):
    def change(doc):
        doc["modules"]["soc_endpoint"] = copy.deepcopy(doc["modules"]["endpoint"])
        doc["modules"]["soc_endpoint"]["nets"]["data"]["endpoints"][1][
            "group"
        ] = "SWAPPED"
        doc["modules"]["soc_wrapper"] = copy.deepcopy(doc["modules"]["wrapper"])
        doc["modules"]["soc_wrapper"]["instances"]["endpoint"][
            "module"
        ] = "soc_endpoint"
        doc["modules"]["board"]["instances"]["soc"]["module"] = "soc_wrapper"

    edit(project, change)
    edit(
        project.parent / "components.yaml",
        lambda d: d["components"]["SYNTH_FPGA_SOC"]["groups"].update(
            SWAPPED=["2", "1", "3", "4"]
        ),
    )
    c = compile_design(load_design(project))
    assert c.data["nets"]["DATA[0]"]["pins"] == ["U1.1", "U2.2"]
    assert not c.check().ok
    output = tmp_path / "blocked"
    assert main(["build", str(project), "-o", str(output), "--json"]) == 2
    assert not output.exists()
    assert any(
        d["rule"] == "DDR" and d["status"] == "FAIL"
        for d in json.loads(capsys.readouterr().out)["diagnostics"]
    )


def test_hierarchical_short_is_not_silent(tmp_path):
    library = {
        "version": 1,
        "components": {
            "ONE": {"package": "ONE", "pins": {"1": {"name": "P", "type": "PASSIVE"}}}
        },
    }
    doc = {
        "version": 1,
        "libraries": ["parts.yaml"],
        "top": "board",
        "references": {"child/chip": "U1"},
        "modules": {
            "leaf": {
                "ports": {"a": {"width": 1}, "b": {"width": 1}},
                "parts": {"chip": {"component": "ONE"}},
                "nets": {
                    "SHORT": {
                        "endpoints": [
                            {"port": "a"},
                            {"port": "b"},
                            {"part": "chip", "pin": "P"},
                        ]
                    }
                },
            },
            "board": {
                "instances": {"child": {"module": "leaf"}},
                "nets": {
                    "A": {"endpoints": [{"instance": "child", "port": "a"}]},
                    "B": {"endpoints": [{"instance": "child", "port": "b"}]},
                },
            },
        },
    }
    write_yaml(tmp_path / "parts.yaml", library)
    write_yaml(tmp_path / "board.yaml", doc)
    with pytest.raises(ElectricalError, match="distinct nets"):
        compile_design(load_design(tmp_path / "board.yaml"))


def test_readback_detects_changed_connectivity_even_with_updated_hash(
    project, tmp_path
):
    import hashlib

    c = compile_design(load_design(project))
    out = tmp_path / "out"
    export_design(c, out)
    tel = out / "design.tel"
    # U2 endpoints terminate records rather than continuation lines.
    text = (
        tel.read_text()
        .replace("U2.1\n", "U2.TEMP\n")
        .replace("U2.2\n", "U2.1\n")
        .replace("U2.TEMP\n", "U2.2\n")
    )
    assert text != tel.read_text()
    tel.write_text(text)
    manifest = json.loads((out / "manifest.json").read_text())
    manifest["files"]["design.tel"] = hashlib.sha256(tel.read_bytes()).hexdigest()
    (out / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(NetlistFormatError, match="connectivity mismatch"):
        verify_package(out)


def test_external_rules_and_waivers(project):
    edit(
        project.parent / "rules.yaml",
        lambda d: d["rules"].append(
            {"id": "SPARE", "kind": "required", "scope": ["U1.10"]}
        ),
    )
    assert not compile_design(load_design(project)).check().ok
    edit(project, lambda d: d.update(waivers="waivers.yaml"))
    write_yaml(
        project.parent / "waivers.yaml",
        [
            {
                "rule": "SPARE",
                "object": "U1.10",
                "reason": "Reserved terminal intentionally NC",
                "owner": "board-team",
            }
        ],
    )
    assert compile_design(load_design(project)).check().ok
    edit(project.parent / "waivers.yaml", lambda w: w[0].update(expires="2000-01-01"))
    assert not compile_design(load_design(project)).check().ok


def test_integral_yaml_bus_width(project):
    edit(project, lambda d: d["modules"]["endpoint"]["ports"]["data"].update(width=4.0))
    assert compile_design(load_design(project)).check().ok


def test_net_reference_collision(make_board):
    with pytest.raises(ElectricalError, match="collide with board references"):
        make_board({"U1": {"1": "PASSIVE"}}, {"U1": [("U1", "1")]})
