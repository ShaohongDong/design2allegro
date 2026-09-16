import json
from copy import deepcopy

import pytest

from design2allegro.model import CompiledDesign, ElectricalError, canonical
from design2allegro.rules import RuleSet, intersect, quantity


@pytest.fixture
def board(make_board):
    return make_board(
        {ref: {str(i): "PASSIVE" for i in range(1, 17)} for ref in ("U1", "U2")},
        {"N" + str(i): [("U1", str(i)), ("U2", str(i))] for i in range(1, 17)},
    )


def rule(kind, scope, params=None, models=None, **kw):
    return {
        "version": 1,
        "models": models or {},
        "rules": [dict(id="CHECK", kind=kind, scope=scope, params=params or {}, **kw)],
    }


def status(board, rules):
    return next(
        d for d in board.check(rules).data["diagnostics"] if d["rule"] == "CHECK"
    )["status"]


@pytest.mark.parametrize(
    "kind,params,models",
    [
        ("required", {}, {}),
        ("connected", {"targets": ["U2.1"]}, {}),
        ("isolated", {"targets": ["U2.2"]}, {}),
        ("capability", {"capability": "clock"}, {"capabilities": ["clock"]}),
        ("attribute", {"name": "bank", "equals": "B0"}, {"bank": "B0"}),
        ("state", {"active_level": "low", "source": "U2.1"}, {"active_level": "low"}),
        (
            "bank",
            {"bank": "B0", "standards": ["LVCMOS18"], "vcco": "1.8 V"},
            {
                "bank": "B0",
                "io_standard": "LVCMOS18",
                "vcco_min": "1.7 V",
                "vcco_max": "1.9 V",
            },
        ),
    ],
)
def test_simple_rules_and_unknown(board, kind, params, models):
    r = rule(kind, ["U1.1"], params, {"pins": {"U1.1": models}})
    assert status(board, r) == "PASS"
    if models:
        r["models"] = {}
        assert status(board, r) == "UNKNOWN"
    else:
        r["rules"][0]["scope"] = []
        assert status(board, r) == "UNKNOWN"


def test_negative_connections_and_nc(board):
    assert status(board, rule("no_connect", ["U1.1"])) == "FAIL"
    assert status(board, rule("connected", ["U1.1"], {"targets": ["U2.2"]})) == "FAIL"
    assert status(board, rule("isolated", ["U1.1"], {"targets": ["U2.1"]})) == "FAIL"


def test_voltage_boundaries(board):
    models = {
        "pins": {
            "U1.1": {
                "reference": "GND",
                "input_min": "0 V",
                "input_max": "3.6 V",
                "vih_min": "2 V",
                "vil_max": ".8 V",
            },
            "U2.1": {
                "reference": "GND",
                "output_min": "0 V",
                "output_max": "3.3 V",
                "voh_min": "2.4 V",
                "vol_max": ".4 V",
            },
        }
    }
    r = rule("voltage", ["U1.1"], {"source": "U2.1"}, models)
    assert status(board, r) == "PASS"
    models["pins"]["U2.1"]["output_max"] = "3.7 V"
    assert status(board, r) == "FAIL"
    models["pins"]["U2.1"]["output_max"] = "3.6 V"
    assert status(board, r) == "PASS"
    del models["pins"]["U1.1"]["vih_min"]
    assert status(board, r) == "UNKNOWN"


def test_power_domains(board):
    models = {
        "nets": {
            "N1": {"voltage_min": "1.7 V", "voltage_max": "1.9 V", "domain": "CORE"}
        },
        "pins": {
            "U1.1": {
                "power_role": "load",
                "domain": "CORE",
                "voltage_min": "1.6 V",
                "voltage_max": "2 V",
            },
            "U2.1": {
                "power_role": "source",
                "domain": "CORE",
                "voltage_min": "1.6 V",
                "voltage_max": "2 V",
            },
        },
    }
    r = rule("power", ["N1"], models=models)
    assert status(board, r) == "PASS"
    models["pins"]["U1.1"]["domain"] = "IO"
    assert status(board, r) == "FAIL"
    models["pins"]["U1.1"]["domain"] = "CORE"
    models["pins"]["U1.1"]["power_role"] = "source"
    assert status(board, r) == "UNKNOWN"
    r["rules"][0]["params"]["allowed_sources"] = ["U1.1", "U2.1"]
    assert status(board, r) == "PASS"


def test_differential(board):
    models = {
        "pins": {
            "U1.1": {"pair": "P0", "polarity": "P"},
            "U1.2": {"pair": "P0", "polarity": "N"},
        }
    }
    r = rule(
        "differential", ["U1.1"], {"peer": "U1.2", "targets": ["U2.1", "U2.2"]}, models
    )
    assert status(board, r) == "PASS"
    r["rules"][0]["params"]["targets"].reverse()
    assert status(board, r) == "FAIL"
    r["rules"][0]["params"]["allow_swap"] = True
    assert status(board, r) == "PASS"


def test_ddr(board):
    a = {
        "dq": ["U1." + str(i) for i in range(1, 9)],
        "dqs_p": "U1.9",
        "dqs_n": "U1.10",
        "dm": "U1.11",
    }
    b = {
        "dq": ["U2." + str(i) for i in range(1, 9)],
        "dqs_p": "U2.9",
        "dqs_n": "U2.10",
        "dm": "U2.11",
    }
    r = rule(
        "ddr",
        ["U1"],
        {"controller": [a], "memory": [b], "control_pairs": [["U1.12", "U2.12"]]},
    )
    assert status(board, r) == "PASS"
    b["dq"][0], b["dq"][1] = b["dq"][1], b["dq"][0]
    assert status(board, r) == "FAIL"
    r["rules"][0]["params"]["bit_maps"] = {"0": [1, 0, 2, 3, 4, 5, 6, 7]}
    assert status(board, r) == "PASS"
    b["dqs_p"] = "U2.12"
    assert status(board, r) == "FAIL"


def test_waiver_and_strict_unknown(board):
    r = rule("no_connect", ["U1.1"])
    assert not board.check(r).ok
    w = [
        {
            "rule": "CHECK",
            "object": "U1.1",
            "reason": "documented test point",
            "owner": "test",
        }
    ]
    report = board.check(r, w)
    assert report.ok
    assert "WAIVED" in report.markdown()
    w[0]["expires"] = "2000-01-01"
    assert not board.check(r, w).ok
    w[0].pop("expires")
    w[0]["object"] = "*"
    assert not board.check(r, w).ok
    assert board.check().ok
    r = rule("required", [], required=False)
    assert board.check(r).ok
    assert (
        status(board, rule("required", ["U1.1"], applicable=False)) == "NOT_APPLICABLE"
    )


def test_rules_order_and_validation(board):
    r = rule("required", ["U1.1"])
    r["rules"].append(
        dict(id="SECOND", kind="isolated", scope=["U1.1"], params={"targets": ["U2.2"]})
    )
    a = board.check(r).data["diagnostics"]
    r["rules"].reverse()
    assert board.check(r).data["diagnostics"] == a
    r["rules"][0]["scope"] = ["U9.1"]
    assert not board.check(r).ok

    r = rule("capability", ["U1.1"], {"capability": "clock"})
    assert not board.check(r).ok


def test_units_intersections(tmp_path):
    assert quantity("1800 mV", "voltage") == quantity("1.8 V", "voltage")
    with pytest.raises(ElectricalError):
        quantity("1 ohm", "voltage")
    with pytest.raises(ElectricalError):
        quantity(1.8, "voltage")
    a = {"dimension": "voltage", "min": "1 V", "max": "3 V"}
    b = {"dimension": "voltage", "min": "2 V", "max": "4 V"}
    assert (
        intersect(a, b)
        == intersect(b, a)
        == {"dimension": "voltage", "min": "2 V", "max": "3 V"}
    )
    with pytest.raises(ElectricalError):
        intersect(a, dict(b, min="4 V"))
    with pytest.raises(ElectricalError):
        intersect(["a"], ["b"])


def test_conflict_count(board):
    data = board.data
    for p in ("U1.1", "U2.1"):
        data["pins"][p]["func"] = data["pin_types"]["OUTPUT"]
    f = CompiledDesign(canonical(data))
    r = f.check(rule("required", ["U1.1"]))
    errors = [d for d in r.data["diagnostics"] if d["rule"] == "ERC.CONFLICT"]
    assert not r.ok and errors[0]["evidence"]["count"] == 1


def test_active_driver_and_tristate_arbitration(board):
    data = board.data
    for p in ("U1.1", "U2.1"):
        data["pins"][p]["func"] = data["pin_types"]["INPUT"]
    f = CompiledDesign(canonical(data))
    r = rule("drive", ["N1"])
    assert status(f, r) == "FAIL"
    data["pins"]["U1.1"]["func"] = data["pin_types"]["OUTPUT"]
    f = CompiledDesign(canonical(data))
    assert status(f, r) == "PASS"
    for p in ("U1.1", "U2.1"):
        data["pins"][p]["func"] = data["pin_types"]["TRISTATE"]
    f = CompiledDesign(canonical(data))
    assert status(f, r) == "UNKNOWN"
    r["rules"][0]["params"]["arbitration"] = ["U1.1", "U2.1"]
    assert status(f, r) == "PASS"
    r["rules"][0]["params"]["arbitration"] = ["U1.1"]
    assert status(f, r) == "FAIL"


def test_large_conflict_summary(make_board):
    snapshot = make_board(
        {"U1": {str(i): "OUTPUT" for i in range(10000)}},
        {"BAD": [("U1", str(i)) for i in range(10000)]},
    )
    report = snapshot.check(rule("required", ["U1.0"]))
    error = next(d for d in report.data["diagnostics"] if d["rule"] == "ERC.CONFLICT")
    assert error["evidence"]["count"] == 49995000
    assert len(error["evidence"]["examples"]) == 20
    assert not report.ok


@pytest.mark.parametrize("entity,obj", [("parts", "U1"), ("nets", "N1")])
def test_attributes_resolve_scoped_entity(board, entity, obj):
    rules = rule(
        "attribute",
        [obj],
        {"name": "test_attribute", "equals": "fitted"},
        {entity: {obj: {"test_attribute": "fitted"}}},
    )
    assert status(board, rules) == "PASS"
    rules["models"][entity][obj]["test_attribute"] = "dnp"
    assert status(board, rules) == "FAIL"
    rules["models"] = {}
    assert status(board, rules) == "UNKNOWN"
