from copy import deepcopy


def rule(protocol, ends, models=None, **params):
    return {
        "version": 1,
        "models": models or {},
        "rules": [
            {
                "id": "INTERFACE",
                "kind": "interface",
                "scope": ["U1"],
                "params": dict(protocol=protocol, endpoints=ends, **params),
            }
        ],
    }


def status(board, rules):
    report = board.check(rules)
    return next(
        d["status"] for d in report.data["diagnostics"] if d["rule"] == "INTERFACE"
    )


def test_uart(make_board):
    f = make_board(
        {r: {"TX": "OUTPUT", "RX": "INPUT"} for r in ("U1", "U2")},
        {"A": [("U1", "TX"), ("U2", "RX")], "B": [("U2", "TX"), ("U1", "RX")]},
    )
    ends = [{"signals": {"tx": r + ".TX", "rx": r + ".RX"}} for r in ("U1", "U2")]
    r = rule("uart", ends)
    assert f.check(r).ok
    ends[1]["signals"]["rx"] = "U2.TX"
    assert status(f, r) == "FAIL"
    del ends[1]["signals"]["rx"]
    assert status(f, r) == "UNKNOWN"


def test_spi(make_board):
    parts = {
        "U1": {
            "SCK": "OUTPUT",
            "MOSI": "OUTPUT",
            "MISO": "INPUT",
            "CS1": "OUTPUT",
            "CS2": "OUTPUT",
        }
    }
    parts.update(
        {
            r: {"SCK": "INPUT", "MOSI": "INPUT", "MISO": "TRISTATE", "CS": "INPUT"}
            for r in ("U2", "U3")
        }
    )
    nets = {s: [(r, s) for r in parts] for s in ("SCK", "MOSI", "MISO")}
    nets.update(
        {"CS1": [("U1", "CS1"), ("U2", "CS")], "CS2": [("U1", "CS2"), ("U3", "CS")]}
    )
    f = make_board(parts, nets)
    ends = [
        {
            "role": "controller",
            "signals": {s.lower(): "U1." + s for s in ("SCK", "MOSI", "MISO")},
            "chip_selects": {"a": "U1.CS1", "b": "U1.CS2"},
        }
    ]
    ends += [
        {
            "id": i,
            "role": "target",
            "signals": {s.lower(): r + "." + s for s in ("SCK", "MOSI", "MISO", "CS")},
        }
        for i, r in [("a", "U2"), ("b", "U3")]
    ]
    models = {
        "pins": {r + ".MISO": {"tri_state_when_deselected": True} for r in ("U2", "U3")}
    }
    r = rule("spi", ends, models)
    assert f.check(r).ok
    models["pins"]["U2.MISO"] = {}
    assert status(f, r) == "UNKNOWN"
    models["pins"]["U2.MISO"] = {"tri_state_when_deselected": False}
    assert status(f, r) == "FAIL"


def test_i2c(make_board):
    parts = {r: {"SDA": "OPENCOLL", "SCL": "OPENCOLL"} for r in ("U1", "U2")}
    parts.update({r: {"1": "PASSIVE", "2": "PASSIVE"} for r in ("R1", "R2")})
    parts["P1"] = {"1": "PWROUT"}
    nets = {
        "SDA": [("U1", "SDA"), ("U2", "SDA"), ("R1", "1")],
        "SCL": [("U1", "SCL"), ("U2", "SCL"), ("R2", "1")],
        "VCC": [("P1", "1"), ("R1", "2"), ("R2", "2")],
    }
    f = make_board(parts, nets)
    ends = [
        {
            "role": role,
            "address": addr,
            "signals": {"sda": r + ".SDA", "scl": r + ".SCL"},
        }
        for r, role, addr in [("U1", "controller", 0), ("U2", "target", 80)]
    ]
    models = {
        "parts": {
            r: {"role": "resistor", "resistance": "4.7 kohm"} for r in ("R1", "R2")
        },
        "nets": {"VCC": {"role": "power"}},
        "pins": {
            r + "." + s: {"drive_mode": "open_drain"}
            for r in ("U1", "U2")
            for s in ("SDA", "SCL")
        },
    }
    pulls = {
        s: {"direction": "up", "rail": "VCC", "min": "1 kohm", "max": "10 kohm"}
        for s in ("sda", "scl")
    }
    r = rule("i2c", ends, models, pulls=pulls)
    assert f.check(r).ok
    models["parts"]["R1"]["resistance"] = "20 kohm"
    assert status(f, r) == "FAIL"
    del models["parts"]["R1"]["resistance"]
    assert status(f, r) == "UNKNOWN"
    models["parts"]["R1"]["resistance"] = "4.7 kohm"
    ends.append(deepcopy(ends[1]))
    assert status(f, r) == "FAIL"


def test_jtag(make_board):
    parts = {"U1": {"TDI": "OUTPUT", "TDO": "INPUT", "TCK": "OUTPUT", "TMS": "OUTPUT"}}
    parts.update(
        {
            r: {"TDI": "INPUT", "TDO": "OUTPUT", "TCK": "INPUT", "TMS": "INPUT"}
            for r in ("U2", "U3")
        }
    )
    nets = {s: [(r, s) for r in parts] for s in ("TCK", "TMS")}
    nets.update(
        {
            "FIRST": [("U1", "TDI"), ("U2", "TDI")],
            "MID": [("U2", "TDO"), ("U3", "TDI")],
            "LAST": [("U3", "TDO"), ("U1", "TDO")],
        }
    )
    f = make_board(parts, nets)
    ends = [
        {
            "role": role,
            "signals": {s.lower(): r + "." + s for s in ("TDI", "TDO", "TCK", "TMS")},
        }
        for r, role in [("U1", "controller"), ("U2", "target"), ("U3", "target")]
    ]
    r = rule("jtag", ends)
    assert f.check(r).ok
    ends[1], ends[2] = ends[2], ends[1]
    assert status(f, r) == "FAIL"


def test_level_shifter(make_board):
    f = make_board(
        {
            "U1": {"TX": "OUTPUT"},
            "U2": {"RX": "INPUT"},
            "U3": {"A": "INPUT", "B": "OUTPUT"},
        },
        {"LOW": [("U1", "TX"), ("U3", "A")], "HIGH": [("U3", "B"), ("U2", "RX")]},
    )
    r = {
        "version": 1,
        "models": {
            "parts": {"U3": {"role": "level_shifter", "channels": [["U3.A", "U3.B"]]}},
            "pins": {"U3.A": {"domain": "1V8"}, "U3.B": {"domain": "3V3"}},
        },
        "rules": [
            {
                "id": "PATH",
                "kind": "path",
                "scope": ["U1.TX"],
                "params": {
                    "target": "U2.RX",
                    "via": [
                        {
                            "pins": ["U3.A", "U3.B"],
                            "role": "level_shifter",
                            "input_domain": "1V8",
                            "output_domain": "3V3",
                        }
                    ],
                },
            }
        ],
    }
    assert f.check(r).ok
    r["rules"][0]["params"]["via"][0]["output_domain"] = "1V8"
    assert not f.check(r).ok
