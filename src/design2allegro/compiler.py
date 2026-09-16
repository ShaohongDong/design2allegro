"""Expand declarative modules into a deterministic physical circuit."""

from collections import defaultdict

from .loader import fail
from .model import CompiledDesign, canonical
from .pin_data import conflict_matrix, pin_info, pin_types
from .rules import intersect


class UnionFind:
    def __init__(self):
        self.parent = {}
        self.size = {}

    def find(self, key):
        if key not in self.parent:
            self.parent[key] = key
            self.size[key] = 1
        root = key
        while self.parent[root] != root:
            root = self.parent[root]
        while key != root:
            parent = self.parent[key]
            self.parent[key] = root
            key = parent
        return root

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            if self.size[a] < self.size[b]:
                a, b = b, a
            self.parent[b] = a
            self.size[a] += self.size[b]


def compile_design(design):
    doc = design.document
    modules = doc["modules"]
    references = doc["references"]
    if len({v.upper() for v in references.values()}) != len(references):
        fail("case-insensitive reference collision", doc)
    visiting, visited = set(), set()

    def graph(name):
        if name not in modules:
            fail(f"unknown module {name}", doc)
        if name in visiting:
            fail(f"recursive module {name}", modules[name])
        if name in visited:
            return
        if len(visiting) >= 64:
            fail("module depth limit (64) exceeded", modules[name])
        visiting.add(name)
        module = modules[name]
        if set(module.get("parts", {})) & set(module.get("instances", {})):
            fail("part and instance names must be distinct", module)
        for instance in module.get("instances", {}).values():
            graph(instance["module"])
        visiting.remove(name)
        visited.add(name)

    for name in modules:
        graph(name)
    if doc["top"] not in modules:
        fail("unknown top module", doc)
    parts, pins, used_refs, hierarchy = {}, {}, set(), {}
    uf = UnionFind()
    records = []
    physical_nodes = {}
    max_instances = 100000
    instances_seen = 0

    def expand(name, path):
        nonlocal instances_seen
        instances_seen += 1
        if instances_seen > max_instances:
            fail("expanded instance limit exceeded", doc)
        if path.count("/") >= 64:
            fail("module depth limit (64) exceeded", doc)
        module = modules[name]
        local_parts, child_ports, ports = {}, {}, {}
        for port, config in sorted(module.get("ports", {}).items()):
            ports[port] = [("port", path, port, i) for i in range(int(config["width"]))]
            for node in ports[port]:
                uf.find(node)
        for local, config in sorted(module.get("parts", {}).items()):
            component = design.components.get(config["component"])
            if component is None:
                fail(f'unknown component {config["component"]}', config, path)
            full = "/".join(filter(None, [path, local]))
            if full not in references:
                fail(f"missing board reference for {full}", config)
            ref = references[full].upper()
            used_refs.add(full)
            hierarchy[full] = ref
            parts[ref] = {
                "ref": ref,
                "name": config["component"],
                "value": config.get("value", component.get("value", "")),
                "footprint": component["package"],
                "hierarchy": full.split("/"),
                "electrical": intersect(
                    component.get("electrical", {}), config.get("electrical", {})
                ),
                "pins": [],
                "source": [list(getattr(config, "source", ("<memory>", 0, 0)))],
            }
            local_parts[local] = (
                ref,
                component,
                {p["name"]: n for n, p in component["pins"].items()},
            )
            for number, pin in sorted(component["pins"].items()):
                key = ref + "." + number
                function = pin_types[pin["type"]]
                pins[key] = {
                    "id": key,
                    "ref": ref,
                    "num": number,
                    "name": pin["name"],
                    "func": int(function),
                    "drive": int(pin_info[function]["drive"]),
                    "min_rcv": int(pin_info[function]["min_rcv"]),
                    "do_erc": True,
                    "net": None,
                    "nc": False,
                    "electrical": pin.get("electrical", {}),
                }
                parts[ref]["pins"].append(key)
                node = ("pin", key)
                physical_nodes[node] = key
                uf.find(node)
        for local, config in sorted(module.get("instances", {}).items()):
            child_path = "/".join(filter(None, [path, local]))
            child_ports[local] = expand(config["module"], child_path)

        def endpoint(ep):
            if "part" in ep:
                if ep["part"] not in local_parts:
                    fail("unknown local part", ep, path)
                ref, component, names = local_parts[ep["part"]]
                if "group" in ep:
                    numbers = component.get("groups", {}).get(ep["group"])
                    if numbers is None:
                        fail("unknown pin group", ep, path)
                else:
                    # Endpoint pin is a logical name. Physical numbers are used only in library groups and rules.
                    if ep["pin"] not in names:
                        fail("unknown logical pin", ep, path)
                    numbers = [names[ep["pin"]]]
                return [("pin", ref + "." + n) for n in numbers]
            selected = ports
            if "instance" in ep:
                if ep["instance"] not in child_ports:
                    fail("unknown child instance", ep, path)
                selected = child_ports[ep["instance"]]
            if ep["port"] not in selected:
                fail("unknown port", ep, path)
            return selected[ep["port"]]

        occupied = set()
        for net_name, config in sorted(module.get("nets", {}).items()):
            ends = [endpoint(ep) for ep in config["endpoints"]]
            widths = {len(e) for e in ends}
            if len(widths) != 1:
                fail("bus width mismatch; no implicit broadcasting", config, path)
            for end in ends:
                for node in end:
                    if node in occupied:
                        fail(
                            f"endpoint repeated or assigned to multiple nets: {node}",
                            config,
                            path,
                        )
                    occupied.add(node)
            width = len(ends[0])
            for i in range(width):
                full = "/".join(filter(None, [path, net_name]))
                if width > 1:
                    full += f"[{i}]"
                head = ends[0][i]
                for end in ends[1:]:
                    uf.union(head, end[i])
                records.append((head, full, config.get("electrical", {})))
        for ep in module.get("nc", []):
            if "part" not in ep:
                fail("NC must name local physical pins or groups", ep, path)
            for node in endpoint(ep):
                if node in occupied:
                    fail("NC conflicts with a connection or another NC", ep, path)
                occupied.add(node)
                pins[physical_nodes[node]]["nc"] = True
        expected = {node for end in ports.values() for node in end}
        expected.update(
            node
            for child in child_ports.values()
            for end in child.values()
            for node in end
        )
        expected.update(
            ("pin", key)
            for ref, _, _ in local_parts.values()
            for key in parts[ref]["pins"]
        )
        missing = expected - occupied
        if missing:
            fail(
                f"unconnected endpoint (connect or explicitly declare physical NC): {min(missing, key=str)}",
                module,
                path,
            )
        return ports

    expand(doc["top"], "")
    if used_refs != set(references):
        fail(f"unused reference paths: {sorted(set(references) - used_refs)}", doc)
    grouped_records, grouped_pins = defaultdict(list), defaultdict(list)
    for node, name, metadata in records:
        grouped_records[uf.find(node)].append((name, metadata))
    for node, key in physical_nodes.items():
        if not pins[key]["nc"]:
            grouped_pins[uf.find(node)].append(key)
    nets, aliases = {}, {}
    for root, names in grouped_records.items():
        if not grouped_pins[root]:
            fail("network has no physical pins: " + names[0][0], doc)
        name = min((n for n, _ in names), key=lambda n: (n.count("/"), n))
        scopes = {}
        for candidate, _ in names:
            scope = candidate.rpartition("/")[0]
            if scope in scopes and scopes[scope] != candidate:
                fail(
                    f"distinct nets in the same scope are shorted: {scopes[scope]} and {candidate}",
                    doc,
                )
            scopes[scope] = candidate
        metadata = {}
        for alias, attrs in sorted(names):
            aliases[alias] = name
            metadata = intersect(metadata, attrs)
        keys = sorted(grouped_pins[root])
        nets[name] = {
            "name": name,
            "pins": keys,
            "drive": 2,
            "do_erc": True,
            "electrical": metadata,
        }
        for key in keys:
            pins[key]["net"] = name
    if set(nets) & set(parts):
        fail(
            f"net names collide with board references: {sorted(set(nets) & set(parts))}",
            doc,
        )
    count = max(int(t) for t in pin_types) + 1
    data = {
        "version": 1,
        "parts": parts,
        "pins": pins,
        "nets": nets,
        "matrix": [
            [int(conflict_matrix[a][b][0]) for b in range(count)] for a in range(count)
        ],
        "conflict_messages": [
            [str(conflict_matrix[a][b][1]) for b in range(count)] for a in range(count)
        ],
        "pin_types": {t.name: int(t) for t in pin_types},
        "hierarchy": hierarchy,
        "net_aliases": aliases,
        "inputs": design.inputs,
    }
    return CompiledDesign(
        canonical(data), canonical(design.rules), canonical(design.waivers)
    )
