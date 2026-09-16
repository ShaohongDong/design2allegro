"""Declarative electrical DRC. No geometry and no inferred device specifications."""

import fnmatch
import itertools
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from .model import ElectricalError, canonical, digest

UNITS = {
    "V": ("voltage", 1),
    "mV": ("voltage", Decimal(".001")),
    "ohm": ("resistance", 1),
    "kohm": ("resistance", 1000),
    "Mohm": ("resistance", 1000000),
    "A": ("current", 1),
    "mA": ("current", Decimal(".001")),
}


def quantity(value, dimension):
    if not isinstance(value, str):
        raise ElectricalError("quantity needs explicit unit")
    match = re.fullmatch(
        r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(\w+)\s*", value
    )
    if not match or match[2] not in UNITS:
        raise ElectricalError("invalid quantity " + str(value))
    kind, scale = UNITS[match[2]]
    if kind != dimension:
        raise ElectricalError("wrong quantity dimension: " + value)
    return Decimal(match[1]) * scale


def intersect(a, b):
    """Merge declarations without load-order overrides."""
    if isinstance(a, dict) and isinstance(b, dict):
        out = dict(a)
        for key, value in b.items():
            if key in out:
                if key in ("min", "max"):
                    # Range objects always include an explicit dimension.
                    dim = a.get("dimension", b.get("dimension"))
                    av, bv = quantity(out[key], dim), quantity(value, dim)
                    out[key] = (
                        out[key] if (av >= bv if key == "min" else av <= bv) else value
                    )
                else:
                    out[key] = intersect(out[key], value)
            else:
                out[key] = value
        if "min" in out and "max" in out:
            if quantity(out["min"], out.get("dimension")) > quantity(
                out["max"], out.get("dimension")
            ):
                raise ElectricalError("empty constraint interval")
        return out
    if isinstance(a, list) and isinstance(b, list):
        left = {canonical(v): v for v in a}
        right = {canonical(v) for v in b}
        keys = sorted(set(left) & right)
        if not keys:
            raise ElectricalError("empty allowed-value intersection")
        return [left[k] for k in keys]
    if a != b:
        raise ElectricalError("conflicting declarations")
    return a


@dataclass(frozen=True)
class RuleSet:
    _json: str

    @classmethod
    def load(cls, value):
        if isinstance(value, cls):
            return value
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ElectricalError("rules require version 1")
        if set(value) - {"version", "models", "rules", "description"}:
            raise ElectricalError("unknown rule-set fields")
        rules = value.get("rules", [])
        if not isinstance(rules, list):
            raise ElectricalError("rules must be a list")
        ids = [r["id"] for r in rules]
        if len(ids) != len(set(ids)) or any(not i for i in ids):
            raise ElectricalError("duplicate/empty rule id")
        return cls(canonical(value))

    @property
    def data(self):
        return json.loads(self._json)


@dataclass(frozen=True)
class CheckReport:
    _json: str

    @property
    def data(self):
        return json.loads(self._json)

    @property
    def ok(self):
        return self.data["ok"]

    def markdown(self):
        d = self.data
        lines = [
            "# Electrical DRC",
            "",
            "Result: " + ("PASS" if d["ok"] else "BLOCKED"),
            "",
            "Snapshot: `" + d["snapshot"] + "`",
            "",
            "| Rule | Object | Status | Severity | Detail |",
            "|---|---|---|---|---|",
        ]
        for item in d["diagnostics"]:
            cells = [
                item["rule"],
                item["object"],
                item["status"],
                item["severity"],
                item["message"],
            ]
            lines.append(
                "| "
                + " | ".join(
                    str(c).replace("|", "\\|").replace("\n", " ") for c in cells
                )
                + " |"
            )
        lines += [
            "",
            "Coverage: `" + canonical(d["coverage"]) + "`",
            "",
            "Static electrical declarations only; physical, dynamic and Allegro import verification are not included.",
        ]
        return "\n".join(lines) + "\n"


class Unknown(Exception):
    pass


class Violation(Exception):
    pass


def require(condition, message):
    if not condition:
        raise Violation(message)


def need(obj, key):
    if key not in obj:
        raise Unknown("missing " + key)
    return obj[key]


PARAMS = {
    "required": set(),
    "no_connect": set(),
    "drive": {"arbitration", "pull"},
    "capability": {"capability"},
    "attribute": {"name", "equals", "allowed"},
    "connected": {"targets"},
    "isolated": {"targets"},
    "voltage": {"source", "logic"},
    "power": {"allowed_sources"},
    "pull": {"direction", "rail", "min", "max"},
    "state": {"active_level", "source", "pull", "initial_state"},
    "bank": {"bank", "standards", "vcco", "vref", "capability"},
    "differential": {"peer", "targets", "allow_swap"},
    "interface": {"protocol", "endpoints", "pulls"},
    "ddr": {"controller", "memory", "byte_map", "bit_maps", "control_pairs"},
    "path": {"via", "target"},
}


class Engine:
    def __init__(self, snapshot, rules):
        self.data = snapshot.data
        self.rules = rules
        self.diagnostics = []
        self.covered = set()
        self.pins = self.data["pins"]
        self.parts = self.data["parts"]
        self.nets = self.data["nets"]
        self.models = {
            kind: {key: dict(obj["electrical"]) for key, obj in self.data[kind].items()}
            for kind in ("pins", "parts", "nets")
        }
        for kind, objects in rules.get("models", {}).items():
            if kind not in self.models:
                raise ElectricalError("unknown model category " + kind)
            for key, value in objects.items():
                if key not in self.models[kind]:
                    raise ElectricalError("model references missing object " + key)
                self.models[kind][key] = intersect(self.models[kind][key], value)
        self.types = self.data["pin_types"]

    def emit(
        self, rule, obj, status, message="", severity="ERROR", required=True, **evidence
    ):
        part = self.parts.get(self.pins.get(obj, {}).get("ref", obj), {})
        self.diagnostics.append(
            dict(
                rule=rule,
                object=obj,
                status=status,
                severity=severity,
                required=required,
                message=message,
                evidence=evidence,
                hierarchy=part.get("hierarchy", []),
                source=part.get("source", []),
            )
        )

    def pin(self, key):
        if key not in self.pins:
            raise ElectricalError("unknown physical pin " + str(key))
        return self.pins[key]

    def net(self, key):
        return self.pin(key)["net"]

    def connected(self, a, b):
        return self.net(a) is not None and self.net(a) == self.net(b)

    def voltage(self, model, key):
        return quantity(need(model, key), "voltage")

    def erc(self):
        def conflicts(types, matrix):
            counts = Counter(types)
            return [
                (
                    a,
                    b,
                    (
                        counts[a] * (counts[a] - 1) // 2
                        if a == b
                        else counts[a] * counts[b]
                    ),
                )
                for a in sorted(counts)
                for b in sorted(counts)
                if a <= b and matrix[a][b] and (a != b or counts[a] > 1)
            ]

        matrix = self.data["matrix"]
        for key, pin in self.pins.items():
            if not pin["do_erc"]:
                continue
            if (
                pin["net"] is None
                and not pin["nc"]
                and pin["func"] != self.types["NOCONNECT"]
            ):
                self.emit("ERC.UNCONNECTED", key, "FAIL", "unconnected pin", "WARNING")
            if pin["net"] is not None and pin["func"] == self.types["NOCONNECT"]:
                self.emit("ERC.FORBIDDEN", key, "FAIL", "no-connect pin attached")
        for name, net in self.nets.items():
            if not net["do_erc"]:
                continue
            pins = [self.pins[k] for k in net["pins"] if self.pins[k]["do_erc"]]
            buckets = defaultdict(list)
            for p in pins:
                buckets[p["func"]].append(p["id"])
            for a, b, count in conflicts([p["func"] for p in pins], matrix):
                pairs = (
                    itertools.combinations(buckets[a], 2)
                    if a == b
                    else itertools.product(buckets[a], buckets[b])
                )
                message = (
                    self.data["conflict_messages"][a][b]
                    or "incompatible pin drive types"
                )
                self.emit(
                    "ERC.CONFLICT",
                    name,
                    "FAIL",
                    message,
                    "ERROR" if matrix[a][b] == 2 else "WARNING",
                    count=count,
                    examples=list(itertools.islice(pairs, 20)),
                    types=[a, b],
                )
            drive = max([net["drive"]] + [p["drive"] for p in pins])
            insufficient = [p["id"] for p in pins if p["min_rcv"] > drive]
            if insufficient:
                self.emit(
                    "ERC.DRIVE",
                    name,
                    "FAIL",
                    "insufficient drive",
                    "WARNING",
                    count=len(insufficient),
                    examples=insufficient[:20],
                )
            if len(net["pins"]) == 1:
                self.emit("ERC.SINGLE", name, "FAIL", "single-pin net", "WARNING")

    def pull(self, pin, params):
        direction = need(params, "direction")
        rail = need(params, "rail")
        if direction not in ("up", "down"):
            raise ElectricalError("pull direction must be up/down")
        if rail not in self.nets:
            raise ElectricalError("unknown pull rail " + rail)
        candidates = []
        for endpoint in self.nets.get(self.net(pin), {}).get("pins", []):
            part = self.parts[self.pins[endpoint]["ref"]]
            model = self.models["parts"][part["ref"]]
            if model.get("role") not in ("resistor", "pullup", "pulldown"):
                continue
            terminals = part["pins"]
            if len(terminals) != 2:
                raise Unknown("pull resistor requires two physical terminals")
            other = terminals[1] if terminals[0] == endpoint else terminals[0]
            other_net = self.net(other)
            other_role = self.models["nets"].get(other_net, {}).get("role")
            if (direction == "up" and other_role == "ground") or (
                direction == "down" and other_role == "power"
            ):
                raise Violation("opposing pull resistor " + part["ref"])
            if self.net(other) == rail:
                if model.get("role") in ("pullup", "pulldown"):
                    require(
                        model["role"]
                        == ("pullup" if direction == "up" else "pulldown"),
                        "opposing pull direction",
                    )
                rail_model = self.models["nets"][rail]
                require(
                    need(rail_model, "role")
                    == ("power" if direction == "up" else "ground"),
                    "incorrect pull reference",
                )
                r = quantity(need(model, "resistance"), "resistance")
                require(r > 0, "pull resistance must be positive")
                if "min" in params:
                    require(
                        r >= quantity(params["min"], "resistance"),
                        "pull resistance below minimum",
                    )
                if "max" in params:
                    require(
                        r <= quantity(params["max"], "resistance"),
                        "pull resistance above maximum",
                    )
                candidates.append(part["ref"])
        require(bool(candidates), "missing declared pull resistor to " + rail)
        return {"resistors": candidates}

    def evaluate(self, kind, obj, p):
        model = next(
            (models[obj] for models in self.models.values() if obj in models), {}
        )
        if kind == "required":
            pin = self.pin(obj)
            require(pin["net"] is not None, "required pin is floating or NC")
        elif kind == "no_connect":
            require(self.net(obj) is None, "reserved pin connected")
        elif kind == "capability":
            require(
                need(p, "capability") in need(model, "capabilities"),
                "pin lacks required capability",
            )
        elif kind == "attribute":
            actual = need(model, need(p, "name"))
            if "allowed" in p:
                require(actual in p["allowed"], "attribute outside allowed set")
            else:
                require(actual == need(p, "equals"), "attribute mismatch")
        elif kind in ("connected", "isolated"):
            targets = need(p, "targets")
            if not targets:
                raise ElectricalError("empty target list")
            for target in targets:
                require(
                    self.connected(obj, target) == (kind == "connected"),
                    "unexpected connection to " + target,
                )
        elif kind == "voltage":
            source = need(p, "source")
            sm = self.models["pins"][source]
            target = model
            require(
                need(sm, "reference") == need(target, "reference"),
                "different reference domains",
            )
            lo, hi = self.voltage(sm, "output_min"), self.voltage(sm, "output_max")
            require(lo <= hi, "invalid output voltage range")
            require(
                lo >= self.voltage(target, "input_min")
                and hi <= self.voltage(target, "input_max"),
                "input voltage limits exceeded",
            )
            if p.get("logic", True):
                require(
                    self.voltage(sm, "voh_min") >= self.voltage(target, "vih_min"),
                    "insufficient logic high",
                )
                require(
                    self.voltage(sm, "vol_max") <= self.voltage(target, "vil_max"),
                    "excessive logic low",
                )
            require(
                self.connected(obj, source),
                "source and sink are not directly connected",
            )
        elif kind == "drive":
            if obj not in self.nets:
                raise ElectricalError("drive scope must be a net")
            active = []
            push = []
            tri = []
            open_drain = []
            for key in self.nets[obj]["pins"]:
                pin = self.pins[key]
                func = pin["func"]
                pm = self.models["pins"][key]
                if func in (self.types["OUTPUT"], self.types["PWROUT"]):
                    mode = "output"
                elif func == self.types["TRISTATE"]:
                    mode = "tristate"
                elif func == self.types["OPENCOLL"]:
                    mode = "open_drain"
                elif func == self.types["OPENEMIT"]:
                    mode = "open_emitter"
                elif func == self.types["BIDIR"]:
                    mode = need(pm, "drive_mode")
                else:
                    mode = "input"
                if mode not in (
                    "input",
                    "output",
                    "tristate",
                    "open_drain",
                    "open_emitter",
                ):
                    raise ElectricalError("invalid drive_mode")
                if mode != "input":
                    active.append(key)
                if mode == "output":
                    push.append(key)
                if mode == "tristate":
                    tri.append(key)
                if mode in ("open_drain", "open_emitter"):
                    open_drain.append(key)
            require(bool(active), "no active driver on input network")
            require(
                len(push) <= 1 and not (push and (tri or open_drain)),
                "incompatible active drivers",
            )
            if len(tri) > 1:
                require(
                    set(need(p, "arbitration")) == set(tri),
                    "tristate arbitration does not cover exact drivers",
                )
            if open_drain:
                require(not tri, "open-drain and tristate drivers mixed")
                self.pull(open_drain[0], need(p, "pull"))
        elif kind == "power":
            net = self.nets.get(obj)
            if net is None:
                raise ElectricalError("unknown power net " + obj)
            nm = self.models["nets"][obj]
            lo, hi = self.voltage(nm, "voltage_min"), self.voltage(nm, "voltage_max")
            require(lo <= hi, "invalid power range")
            domain = need(nm, "domain")
            sources = []
            for key in net["pins"]:
                pm = self.models["pins"][key]
                role = need(pm, "power_role")
                require(need(pm, "domain") == domain, "power domain mismatch " + key)
                require(
                    lo >= self.voltage(pm, "voltage_min")
                    and hi <= self.voltage(pm, "voltage_max"),
                    "power voltage mismatch " + key,
                )
                if role == "source":
                    sources.append(key)
                elif role not in ("load", "passive", "ground"):
                    raise ElectricalError("invalid power role")
            require(bool(sources), "power net has no source")
            if len(sources) > 1:
                require(
                    set(sources) == set(need(p, "allowed_sources")),
                    "undeclared parallel power sources",
                )
        elif kind == "pull":
            return self.pull(obj, p)
        elif kind == "state":
            require(
                need(model, "active_level") == need(p, "active_level"),
                "reset/strap polarity mismatch",
            )
            self.pin(obj)
            if "source" in p:
                require(
                    self.connected(obj, p["source"]), "missing reset/clock/strap source"
                )
            if "pull" in p:
                self.pull(obj, p["pull"])
            if "initial_state" in p:
                require(
                    need(model, "initial_state") == p["initial_state"],
                    "startup state mismatch",
                )
        elif kind == "bank":
            require(need(model, "bank") == need(p, "bank"), "wrong FPGA bank")
            require(
                need(model, "io_standard") in need(p, "standards"),
                "unsupported I/O standard",
            )
            v = quantity(need(p, "vcco"), "voltage")
            require(
                self.voltage(model, "vcco_min") <= v <= self.voltage(model, "vcco_max"),
                "bank VCCO incompatible",
            )
            if "vref" in p:
                require(
                    quantity(p["vref"], "voltage") == self.voltage(model, "vref"),
                    "bank VREF incompatible",
                )
            if "capability" in p:
                require(
                    p["capability"] in need(model, "capabilities"),
                    "wrong FPGA pin purpose",
                )
        elif kind == "differential":
            peer = need(p, "peer")
            other = self.models["pins"].get(peer, {})
            require(
                need(model, "pair") == need(other, "pair"),
                "not a declared differential pair",
            )
            require(
                {need(model, "polarity"), need(other, "polarity")} == {"P", "N"},
                "invalid P/N pairing",
            )
            require(not self.connected(obj, peer), "differential pair shorted")
            if "targets" in p:
                targets = p["targets"]
                require(len(targets) == 2, "expected two target pins")
                straight = self.connected(obj, targets[0]) and self.connected(
                    peer, targets[1]
                )
                reverse = self.connected(obj, targets[1]) and self.connected(
                    peer, targets[0]
                )
                require(
                    straight or (p.get("allow_swap", False) and reverse),
                    "incorrect differential endpoint mapping",
                )
        elif kind == "interface":
            return self.interface(p)
        elif kind == "ddr":
            return self.ddr(p)
        elif kind == "path":
            # Explicit component-mediated path, never arbitrary graph traversal.
            current = obj
            for step in need(p, "via"):
                a, b = need(step, "pins")
                part = self.parts[self.pin(a)["ref"]]
                require(
                    self.pin(b)["ref"] == part["ref"],
                    "path terminals must belong to one part",
                )
                role = need(self.models["parts"][part["ref"]], "role")
                require(role == need(step, "role"), "unexpected intermediary role")
                require(
                    role in ("resistor", "jumper", "net_tie", "level_shifter"),
                    "unsupported intermediary",
                )
                require(self.connected(current, a), "broken component path")
                if role == "level_shifter":
                    pm = self.models["parts"][part["ref"]]
                    require(
                        [a, b] in need(pm, "channels"),
                        "undeclared level-shifter channel/direction",
                    )
                    require(
                        need(self.models["pins"][a], "domain")
                        == need(step, "input_domain"),
                        "wrong shifter input domain",
                    )
                    require(
                        need(self.models["pins"][b], "domain")
                        == need(step, "output_domain"),
                        "wrong shifter output domain",
                    )
                current = b
            require(
                self.connected(current, need(p, "target")), "path does not reach target"
            )
        else:
            raise ElectricalError("unknown rule kind " + kind)
        return {}

    def interface(self, p):
        protocol = need(p, "protocol").lower()
        ends = need(p, "endpoints")
        require(len(ends) >= 2, "interface needs at least two endpoints")

        def signal(e, name):
            key = need(need(e, "signals"), name)
            self.pin(key)
            return key

        def driver(key):
            require(
                self.pin(key)["func"]
                in (
                    self.types["OUTPUT"],
                    self.types["TRISTATE"],
                    self.types["OPENCOLL"],
                ),
                "expected output " + key,
            )

        def receiver(key):
            require(
                self.pin(key)["func"] in (self.types["INPUT"], self.types["BIDIR"]),
                "expected input " + key,
            )

        if protocol == "i2c":
            require(
                not self.connected(signal(ends[0], "sda"), signal(ends[0], "scl")),
                "I2C SDA and SCL shorted",
            )
            addresses = []
            for name in ("sda", "scl"):
                root = signal(ends[0], name)
                for e in ends:
                    pin = signal(e, name)
                    require(self.connected(root, pin), "I2C signal mapping mismatch")
                    require(
                        self.pin(pin)["func"]
                        in (self.types["OPENCOLL"], self.types["BIDIR"]),
                        "I2C pin type cannot be push-pull",
                    )
                    require(
                        need(self.models["pins"][pin], "drive_mode") == "open_drain",
                        "I2C requires declared open-drain mode",
                    )
                self.pull(root, need(need(p, "pulls"), name))
            for e in ends:
                role = need(e, "role")
                require(role in ("controller", "target"), "invalid I2C role")
                if role == "target":
                    addresses.append(need(e, "address"))
            require(
                len(addresses) == len(set(addresses)), "duplicate I2C target address"
            )
            require(
                any(e["role"] == "controller" for e in ends), "missing I2C controller"
            )
        elif protocol == "uart":
            require(len(ends) == 2, "UART requires two endpoints")
            for a, b in ((ends[0], ends[1]), (ends[1], ends[0])):
                tx, rx = signal(a, "tx"), signal(b, "rx")
                driver(tx)
                receiver(rx)
                require(self.connected(tx, rx), "UART TX/RX mapping mismatch")
        elif protocol == "spi":
            controllers = [e for e in ends if need(e, "role") == "controller"]
            require(len(controllers) == 1, "SPI needs one controller")
            c = controllers[0]
            csnets = []
            signal_nets = [self.net(signal(c, k)) for k in ("sck", "mosi", "miso")]
            require(
                len(set(signal_nets)) == 3 and None not in signal_nets,
                "SPI signals shorted or unconnected",
            )
            for target in ends:
                if target is c:
                    continue
                require(target["role"] == "target", "invalid SPI role")
                for name in ("sck", "mosi", "miso"):
                    a, b = signal(c, name), signal(target, name)
                    driver(b if name == "miso" else a)
                    receiver(a if name == "miso" else b)
                    require(self.connected(a, b), "SPI signal mapping mismatch " + name)
                cs = signal(target, "cs")
                source = need(need(c, "chip_selects"), need(target, "id"))
                driver(source)
                receiver(cs)
                require(self.connected(source, cs), "SPI chip-select mismatch")
                csnets.append(self.net(cs))
            require(len(csnets) == len(set(csnets)), "SPI targets share chip select")
            require(
                not set(csnets) & set(signal_nets),
                "SPI chip select shorted to data/clock",
            )
            if len(ends) > 2:
                for e in ends:
                    if e is not c:
                        require(
                            need(
                                self.models["pins"][signal(e, "miso")],
                                "tri_state_when_deselected",
                            )
                            is True,
                            "SPI target must release MISO",
                        )
        elif protocol == "jtag":
            c = ends[0]
            require(
                need(c, "role") == "controller",
                "first JTAG endpoint must be controller",
            )
            targets = ends[1:]
            require(
                all(need(e, "role") == "target" for e in targets),
                "invalid JTAG target role",
            )
            for name in ("tck", "tms"):
                source = signal(c, name)
                driver(source)
                for e in targets:
                    receiver(signal(e, name))
                    require(
                        self.connected(source, signal(e, name)), "broken JTAG " + name
                    )
            prev = signal(c, "tdi")
            driver(prev)
            for e in targets:
                receiver(signal(e, "tdi"))
                require(
                    self.connected(prev, signal(e, "tdi")), "broken JTAG serial chain"
                )
                prev = signal(e, "tdo")
                driver(prev)
            receiver(signal(c, "tdo"))
            require(self.connected(prev, signal(c, "tdo")), "broken JTAG return")
        else:
            raise ElectricalError("unsupported protocol " + protocol)
        return {"protocol": protocol, "endpoints": len(ends)}

    def ddr(self, p):
        a, b = need(p, "controller"), need(p, "memory")
        require(len(a) == len(b) and bool(a), "DDR group count mismatch")
        byte_map = p.get("byte_map", list(range(len(a))))
        require(
            sorted(byte_map) == list(range(len(a))), "DDR byte map is not a permutation"
        )
        for i, ga in enumerate(a):
            gb = b[byte_map[i]]
            da, db = need(ga, "dq"), need(gb, "dq")
            require(
                len(da) == len(db) and len(da) in (4, 8, 16), "DDR data width mismatch"
            )
            require(
                len(set(da)) == len(da) and len(set(db)) == len(db),
                "duplicate DDR physical DQ pin",
            )
            require(len({self.net(k) for k in da}) == len(da), "DDR DQ signals shorted")
            bit_map = p.get("bit_maps", {}).get(str(i), list(range(len(da))))
            require(
                sorted(bit_map) == list(range(len(da))),
                "DDR bit map is not a permutation",
            )
            for j, pin in enumerate(da):
                require(
                    self.connected(pin, db[bit_map[j]]),
                    "DDR DQ crosses declared group/bit mapping",
                )
            for name in ("dqs_p", "dqs_n"):
                require(
                    self.connected(need(ga, name), need(gb, name)),
                    "DDR strobe mapping mismatch",
                )
            require(not self.connected(ga["dqs_p"], ga["dqs_n"]), "DDR strobes shorted")
            if "dm" in ga or "dm" in gb:
                require(
                    self.connected(need(ga, "dm"), need(gb, "dm")),
                    "DDR DM mapping mismatch",
                )
        for source, target in p.get("control_pairs", []):
            require(self.connected(source, target), "DDR address/control mismatch")
        return {"groups": len(a)}

    def run(self):
        self.erc()
        for rule in sorted(self.rules.get("rules", []), key=lambda r: r["id"]):
            rid = rule["id"]
            required = rule.get("required", True)
            severity = rule.get("severity", "ERROR")
            if severity not in ("ERROR", "WARNING", "INFO"):
                raise ElectricalError("invalid severity")
            if not isinstance(required, bool) or not isinstance(
                rule.get("applicable", True), bool
            ):
                raise ElectricalError("required/applicable must be booleans")
            kind = rule.get("kind")
            if kind not in PARAMS:
                raise ElectricalError("unknown rule kind " + str(kind))
            params = rule.get("params", {})
            if not isinstance(params, dict) or set(params) - PARAMS[kind]:
                raise ElectricalError("unknown parameters for " + str(kind))
            if "scope" in rule and "selector" in rule:
                raise ElectricalError("choose scope or selector, not both")
            if set(rule) - {
                "id",
                "kind",
                "scope",
                "selector",
                "params",
                "required",
                "severity",
                "applicable",
                "source",
            }:
                raise ElectricalError("unknown rule fields " + rid)
            scope = rule.get("scope")
            if scope is None:
                selector = need(rule, "selector")
                kind = selector.get("entity", "pins")
                if kind not in self.models:
                    raise ElectricalError("invalid selector entity")
                scope = sorted(
                    k
                    for k in self.models[kind]
                    if fnmatch.fnmatchcase(k, need(selector, "pattern"))
                )
            if not isinstance(scope, list) or len(scope) != len(set(scope)):
                raise ElectricalError("scope must be a unique list")
            if not scope:
                self.emit(
                    rid,
                    "<scope>",
                    "UNKNOWN" if required else "NOT_APPLICABLE",
                    "selector matched zero objects",
                    severity,
                    required,
                )
            for obj in scope:
                if (
                    obj not in self.pins
                    and obj not in self.nets
                    and obj not in self.parts
                ):
                    raise ElectricalError("unknown scope object " + obj)
                self.covered.add(obj)
                if rule.get("applicable") is False:
                    self.emit(
                        rid,
                        obj,
                        "NOT_APPLICABLE",
                        "explicitly not applicable",
                        severity,
                        required,
                    )
                    continue
                try:
                    evidence = self.evaluate(rule["kind"], obj, rule.get("params", {}))
                    self.emit(
                        rid,
                        obj,
                        "PASS",
                        "electrical declaration satisfied",
                        severity,
                        required,
                        **evidence,
                    )
                except Unknown as exc:
                    self.emit(rid, obj, "UNKNOWN", str(exc), severity, required)
                except Violation as exc:
                    self.emit(rid, obj, "FAIL", str(exc), severity, required)


def check(snapshot, rules=None, waivers=None):
    data = {"version": 1, "rules": []}
    engine = None
    diagnostics = []
    try:
        data = RuleSet.load(rules).data if rules is not None else data
        engine = Engine(snapshot, data)
        engine.run()
        diagnostics = engine.diagnostics
    except Exception as exc:
        diagnostics = list(engine.diagnostics) if engine else []
        diagnostics.append(
            dict(
                rule="CONFIG.INVALID",
                object="<project>",
                status="FAIL",
                severity="ERROR",
                required=True,
                message=str(exc),
                evidence={},
            )
        )
    waiver_data = waivers or []
    used = set()
    for waiver in waiver_data:
        try:
            for key in ("rule", "object", "reason", "owner"):
                if not isinstance(waiver.get(key), str) or not waiver[key].strip():
                    raise ElectricalError("waiver missing " + key)
            if any(c in waiver["rule"] + waiver["object"] for c in "*?[]"):
                raise ElectricalError("wildcard waiver forbidden")
            if waiver["rule"].startswith(
                ("CONFIG.", "STRUCTURE.", "EXEC.", "COVERAGE.")
            ):
                raise ElectricalError("rule is not waivable")
            identity = (waiver["rule"], waiver["object"])
            if identity in used:
                raise ElectricalError("duplicate waiver")
            used.add(identity)
            if (
                "expires" in waiver
                and date.fromisoformat(waiver["expires"]) < date.today()
            ):
                raise ElectricalError("expired waiver")
            matches = [
                d
                for d in diagnostics
                if (d["rule"], d["object"]) == identity
                and d["status"] in ("FAIL", "UNKNOWN")
            ]
            if not matches:
                raise ElectricalError("waiver has no matching violation")
            for item in matches:
                item["original_status"] = item["status"]
                item["status"] = "WAIVED"
                item["waiver"] = waiver
        except Exception as exc:
            diagnostics.append(
                dict(
                    rule="CONFIG.WAIVER",
                    object="<project>",
                    status="FAIL",
                    severity="ERROR",
                    required=True,
                    message=str(exc),
                    evidence={},
                )
            )
    diagnostics.sort(
        key=lambda d: (
            d["rule"],
            d["object"],
            d["status"],
            canonical(d.get("evidence", {})),
        )
    )
    ok = not any(
        (d["status"] == "FAIL" and d["severity"] == "ERROR")
        or (d["status"] == "UNKNOWN" and d["required"])
        for d in diagnostics
    )
    declared = set(engine.covered) if engine else set()
    unmodeled = sorted(
        k for k, v in (engine.models["pins"].items() if engine else []) if not v
    )
    result = {
        "version": 1,
        "snapshot": snapshot.digest,
        "rules": digest(data),
        "waivers": digest(waiver_data),
        "ok": ok,
        "diagnostics": diagnostics,
        "coverage": {
            "status_counts": dict(Counter(d["status"] for d in diagnostics)),
            "scoped_objects": len(declared),
            "total_pins": len(snapshot.data["pins"]),
            "unmodeled_pin_count": len(unmodeled),
            "unmodeled_pins": unmodeled,
            "unscoped_pin_count": len(set(snapshot.data["pins"]) - declared),
        },
    }
    return CheckReport(canonical(result))
