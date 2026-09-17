"""Pure topology and traversal contracts, independent of layout and visibility."""

from test_browser import browser  # noqa: F401
from test_pin_graph import graph_page  # noqa: F401


def circuit():
    # R forms an automatic path to U. U can branch through A/B and rejoin at T.
    assignments = {
        "R": ["IN", "MID"],
        "U": ["MID", "LEFT", "RIGHT", "SPARE", None],
        "A": ["LEFT", "JOIN"],
        "B": ["RIGHT", "JOIN"],
        "T": ["JOIN", "GND"],
        "D": ["SPARE", "OUT"],
        "Z": ["OUT", "IN"],
    }
    parts, pins, nets = {}, {}, {}
    for ref, connections in assignments.items():
        ids = []
        for i, net in enumerate(connections):
            identity = f"{ref}.{i+1}"
            ids.append(identity)
            pins[identity] = dict(
                id=identity,
                key="pin:" + identity,
                ref=ref,
                num=str(i + 1),
                name=f"P{i+1}",
                reference=ref,
                net=net,
                nc=net is None,
            )
            if net:
                nets.setdefault(
                    net, dict(name=net, key="net:" + net, pins=[], aliases=[])
                )["pins"].append(identity)
        parts[ref] = dict(
            key="part:" + ref,
            pins=ids,
            assembly="dnp" if ref == "D" else "fitted",
            hierarchy=["board", ref],
        )
    return dict(parts=parts, pins=pins, nets=nets)


def trace(page, pkg, root="R.1", choices=None, overrides=None):
    return page.evaluate(
        """o=>{
      const t=ReviewGraphModel.trace(o.pkg,o.root,o.choices,o.overrides);
      return {pins:[...t.pins].sort(),nets:[...t.nets].sort(),crosses:[...t.transitions.values()]};
    }""",
        dict(pkg=pkg, root=root, choices=choices or {}, overrides=overrides or {}),
    )


def test_auto_two_pin_dnp_nc_and_rail_boundaries(graph_page):
    page, _ = graph_page
    pkg = circuit()
    t = trace(page, pkg)
    assert set(t["pins"]) == {"R.1", "R.2", "U.1", "Z.1", "Z.2", "D.2"}
    assert "D.1" not in t["pins"]  # DNP doesn't cross automatically.
    assert trace(page, pkg, root="U.5")["pins"] == ["U.5"]
    assert trace(page, pkg, root="T.2")["pins"] == ["T.2"]
    assert len(trace(page, pkg, root="T.2", overrides={"GND": "signal"})["pins"]) > 1
    manual = trace(page, pkg, choices={"D.2": ["D.1"]})
    assert "D.1" in manual["pins"] and "U.4" in manual["pins"]
    invalid = trace(page, pkg, choices={"U.1": ["A.1", "U.5", "missing"]})
    assert invalid == t  # Can't cross to another device, NC, or nonexistent pin.


def test_multiselect_reconvergence_removal_and_cycles(graph_page):
    page, _ = graph_page
    pkg = circuit()
    both = trace(page, pkg, choices={"U.1": ["U.2", "U.3"]})
    assert {"A.1", "A.2", "B.1", "B.2", "T.1", "T.2"} <= set(both["pins"])
    left = trace(page, pkg, choices={"U.1": ["U.2"]})
    assert set(left["pins"]) == set(
        both["pins"]
    )  # right branch still reached through JOIN.
    none = trace(page, pkg)
    assert "T.1" not in none["pins"]
    # A manually closed loop terminates and retains all unique relationships.
    loop = trace(page, pkg, choices={"U.1": ["U.4"], "D.1": ["D.2"]})
    assert len(loop["pins"]) == len(set(loop["pins"]))
    assert {"D.1", "D.2", "Z.1", "Z.2"} <= set(loop["pins"])
    assert {"IN", "MID", "SPARE", "OUT"} == set(loop["nets"])


def test_topology_preserves_identity_and_collapsed_membership(graph_page):
    page, _ = graph_page
    pkg = circuit()
    result = page.evaluate(
        """pkg=>{
      const full=ReviewGraphModel.topology(pkg);
      const folded=ReviewGraphModel.topology(pkg,{collapsed:new Set(['board'])});
      const chain=ReviewGraphModel.topology(pkg,{root:'R.1',onlyTrace:true});
      return {
        fullPins:full.nodes.filter(n=>n.classes.split(' ').includes('pin')).map(n=>n.data.pinId),
        foldedPins:folded.nodes.filter(n=>n.classes==='module').flatMap(n=>n.data.pins),
        netPins:full.edges.filter(e=>e.classes==='wire').flatMap(e=>e.data.pins),
        chainPins:chain.nodes.filter(n=>n.classes.split(' ').includes('pin')).map(n=>n.data.pinId),
        crosses:full.edges.filter(e=>e.classes==='transition').every(e=>!e.data.netKey),
        unique:new Set(full.nodes.map(n=>n.data.id).concat(full.edges.map(e=>e.data.id))).size===full.nodes.length+full.edges.length
      };
    }""",
        pkg,
    )
    assert sorted(result["fullPins"]) == sorted(pkg["pins"])
    assert sorted(result["foldedPins"]) == sorted(pkg["pins"])
    assert sorted(result["netPins"]) == sorted(
        k for k, p in pkg["pins"].items() if p["net"] not in (None, "GND")
    )
    assert sorted(result["chainPins"]) == trace(page, pkg)["pins"]
    assert result["crosses"] and result["unique"]


def test_junction_geometry_net_identity_and_collinear_union(graph_page):
    page, _ = graph_page

    def dots(paths, anchors=None):
        return page.evaluate(
            "(data)=>ReviewGraphModel.junctions(data.wires,data.anchors)",
            {
                "wires": [
                    {"netKey": net, "points": [{"x": x, "y": y} for x, y in points]}
                    for net, points in paths
                ],
                "anchors": anchors or [],
            },
        )

    h = ("net:A", [(-50, 0), (50, 0)])
    v = ("net:A", [(0, -50), (0, 50)])
    t = ("net:A", [(0, 0), (0, 50)])
    expected = [{"netKey": "net:A", "x": 0, "y": 0}]
    assert dots([h, t]) == expected
    assert dots([h, v]) == expected
    assert dots([h, h, v, v]) == expected
    assert dots([("net:A", [(-50, 0), (0, 0), (0, 50)])]) == []
    assert dots([h, ("net:B", v[1])]) == []
    assert dots([h, (None, v[1])]) == []
    assert dots([h, ("net:A", [(-25, 0), (25, 0)])]) == []
    assert dots(
        [("net:A", [(-50, 0), (50, 0)]), ("net:A", [(-25, 0), (25, 0), (25, 40)])]
    ) == [{"netKey": "net:A", "x": 25, "y": 0}]
    assert dots([h, t], [{"netKey": "net:A", "x": 0, "y": 0}]) == []
    assert dots([h, t], [{"netKey": "net:B", "x": 0, "y": 0}]) == expected
    assert dots([h, ("net:A", [(0, 0.000000001), (0, 50)])]) == expected
    assert dots([h, ("net:A", [(0, 1), (0, 50)])]) == []
    assert dots([("net:A", [(0, 0), (0, 0), (10, 10)])]) == []


def test_many_disjoint_networks_do_not_create_junctions(graph_page):
    page, _ = graph_page
    assert page.evaluate("""()=>{
      const wires=Array.from({length:10000},(_,i)=>({netKey:'net:'+i,
        points:[{x:0,y:i},{x:100,y:i},{x:100,y:i+20}]}));
      return ReviewGraphModel.junctions(wires).length;
    }""") == 0
