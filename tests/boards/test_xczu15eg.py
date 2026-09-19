"""Board electrical regressions, distinct from compiler synthetic fixtures."""

import csv
import json
import re
import shutil
from pathlib import Path

import pytest

from design2allegro import compile_design, export_design, load_design
from design2allegro.model import ElectricalError
from design2allegro.verify import verify_package

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / "schematics/xczu15eg_minimal"


@pytest.fixture(scope="module")
def circuit():
    return compile_design(load_design(BOARD / "board.circuit"))


def test_complete_physical_inventory(circuit):
    assert circuit.check().ok
    pins = circuit.data["pins"]
    assert len(pins) == 3150
    assert sum(p["ref"] == "fpga/soc" for p in pins.values()) == 1156
    assert sum(p["ref"] == "storage/emmc" for p in pins.values()) == 153
    assert all(bool(p["net"]) != bool(p["nc"]) for p in pins.values())
    assert sum(p["nc"] for p in pins.values()) == 571


def test_fpga_against_manufacturer_and_vivado(circuit):
    text = (BOARD / "evidence/xczu15egffvb1156pkg.csv").read_text()
    official = {
        r["Pin"]: r["Pin Name"]
        for r in csv.DictReader(text[text.index("Pin,Pin Name,") :].splitlines())
        if re.fullmatch(r"[A-Z]+[0-9]+", r.get("Pin", ""))
    }
    vivado = {
        r["ball"]: r["pin_func"]
        for r in csv.DictReader(
            (BOARD / "evidence/xczu15eg_ffvb1156_vivado.tsv").open(), delimiter="\t"
        )
    }
    assert len(official) == len(vivado) == 1156
    for ball, name in vivado.items():
        assert re.sub(r"_50[0-5]$", "", name) == re.sub(
            r"_50[0-5]$", "", official[ball]
        )
    actual = {
        p["num"]: p["name"]
        for p in circuit.data["pins"].values()
        if p["ref"] == "fpga/soc"
    }
    assert set(actual) == set(official)
    for ball, name in actual.items():
        assert name in (vivado[ball], vivado[ball] + "_" + ball)


def test_reserved_emmc_and_unused_transceivers(circuit):
    for pin in circuit.data["pins"].values():
        if pin["ref"] == "storage/emmc" and pin["name"].startswith(("RFU", "NC")):
            assert pin["nc"] and not pin["net"]
        if pin["ref"] == "fpga/soc" and pin["name"].startswith(
            ("MGTAV", "MGTVCCAUX", "PS_MGTRAV", "MGTYRX", "PS_MGTRRX", "MGTRREF")
        ):
            assert pin["net"] == "GND"


def test_uart_and_reset_separation(circuit):
    p = circuit.data["pins"]
    assert p["fpga/soc.PS_MIO43_501"]["net"] == "UART_TX"
    assert p["fpga/soc.PS_MIO42_501"]["net"] == "UART_RX"
    assert (
        p["clock_reset/pl_supervisor.RESET_N"]["net"]
        != p["pl_ddr4/memory0.RESET_N"]["net"]
    )
    assert p["power/ddr_pg_pull.B"]["net"] == "IO_3V3"
    for ref in ["clock_reset/good_core_pg", "power/ddr_en_vpp"]:
        assert p[ref + ".K"]["num"] == "3"
        assert p[ref + ".NC"]["num"] == "2"


@pytest.mark.parametrize(
    "filename,old,new,rule",
    [
        ("ps_ddr4.circuit", "memory0.DQ0", "memory0.DQ1", "PS_DQ0"),
        ("debug.circuit", "uart.P2", "uart.P3", "UART_TX"),
    ],
)
def test_signal_swaps_are_rejected(tmp_path, filename, old, new, rule):
    shutil.copytree(BOARD, tmp_path / "board")
    path = tmp_path / "board" / filename
    text = re.sub(r"\b" + re.escape(old) + r"\b", "__SWAP__", path.read_text())
    text = re.sub(r"\b" + re.escape(new) + r"\b", old, text).replace("__SWAP__", new)
    path.write_text(text)
    report = compile_design(load_design(tmp_path / "board/board.circuit")).check()
    assert not report.ok
    assert any(
        d["rule"] == rule and d["status"] == "FAIL" for d in report.data["diagnostics"]
    )


def test_final_physical_contract(tmp_path):
    shutil.copytree(BOARD, tmp_path / "board")
    compiled = compile_design(load_design(tmp_path / "board/board.circuit"))
    export_design(compiled, tmp_path / "package")
    verify_package(tmp_path / "package")


def test_rail_short_is_rejected(tmp_path):
    shutil.copytree(BOARD, tmp_path / "board")
    path = tmp_path / "board/board.circuit"
    text = path.read_text()
    endpoints = re.search(r"    net IO_1V8 = ([^;]+);\n", text).group(1)
    text = re.sub(r"    net IO_1V8 = [^;]+;\n", "", text)
    text = text.replace("net IO_3V3 = ", "net IO_3V3 = " + endpoints + ", ", 1)
    path.write_text(text)
    with pytest.raises(
        ElectricalError, match="distinct nets in the same scope are shorted"
    ):
        compile_design(load_design(path))


def test_all_fpga_supply_balls(circuit):
    expected = {
        "VCCINT": "CORE_0V85",
        "VCCINT_IO": "CORE_0V85",
        "VCCBRAM": "CORE_0V85",
        "VCC_PSINTLP": "CORE_0V85",
        "VCC_PSINTFP": "CORE_0V85",
        "VCC_PSINTFP_DDR": "CORE_0V85",
        "VCCAUX": "AUX_1V8",
        "VCCAUX_IO": "AUX_1V8",
        "VCC_PSAUX": "AUX_1V8",
        "VCC_PSPLL": "PSPLL_1V2",
        "VCC_PSDDR_PLL": "fpga/PSDDR_PLL_1V8",
        "VCC_PSADC": "fpga/PSADC_1V8",
        "VCCADC": "fpga/ADC_1V8",
        "VCC_PSBATT": "AUX_1V8",
    }
    table = {
        r["ball"]: r["pin_func"]
        for r in csv.DictReader(
            (BOARD / "evidence/xczu15eg_ffvb1156_vivado.tsv").open(), delimiter="\t"
        )
    }
    for p in circuit.data["pins"].values():
        if p["ref"] != "fpga/soc":
            continue
        name = table[p["num"]]
        if name.startswith("GND"):
            assert p["net"] == "GND"
        if not name.startswith("VCC"):
            continue
        if name.startswith("VCCO_PSDDR") or name in ("VCCO_64", "VCCO_65"):
            rail = "DDR_1V2"
        elif name == "VCCO_PSIO3_503":
            rail = "IO_3V3"
        elif name.startswith("VCCO"):
            rail = "IO_1V8"
        else:
            rail = expected[name]
        assert p["net"] == rail, (p["num"], name, p["net"], rail)


def test_vivado_constraints_match_physical_board(circuit):
    pins = {
        p["num"]: p for p in circuit.data["pins"].values() if p["ref"] == "fpga/soc"
    }
    assignments = re.findall(
        r"PACKAGE_PIN (\w+) \[get_ports \{([^}]+)\}\]",
        (BOARD / "tools/pl_ddr4.xdc").read_text(),
    )
    assert len(assignments) == 74
    for ball, port in assignments:
        if port.startswith("ddr_dqs_"):
            m = re.fullmatch(r"ddr_dqs_([pn])\[(\d+)\]", port)
            net = f"PL_DQS{m[2]}_{m[1].upper()}"
        elif "[" in port:
            m = re.fullmatch(r"ddr_(\w+)\[(\d+)\]", port)
            stem = "A" if m[1] == "addr" else m[1].upper()
            net = f"PL_{stem}{m[2]}"
        else:
            net = {
                "refclk_p": "PL_REF_P",
                "refclk_n": "PL_REF_N",
                "reset_n": "PL_SYS_RESET_N",
                "ddr_bg": "PL_BG0",
            }.get(port, "PL_" + port.removeprefix("ddr_").upper())
        assert pins[ball]["net"] == net, (ball, port, pins[ball]["net"], net)
