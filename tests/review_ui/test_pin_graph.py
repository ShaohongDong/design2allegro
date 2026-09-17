"""Pin-level visual acceptance on generated, electrically verified packages."""

import json
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import unquote

import pytest
from playwright.sync_api import expect
from test_browser import browser  # noqa: F401 -- shared Chromium fixture

from design2allegro import compile_design, export_design, load_design
from design2allegro.formatting import dumps
from design2allegro.properties import REQUIRED
from design2allegro.review import ReviewServer

ARTIFACT = Path(__file__).resolve().parents[2] / "build/parser/review-ui"


def synthetic_package(root, *, large=False):
    root.mkdir(parents=True)
    properties = {
        "resistance": "10 kohm",
        "tolerance": "1 %",
        "power_rating": "1 W",
        "capacitance": "100 nF",
        "voltage_rating": "16 V",
        "dielectric": "X7R",
        "polarized": False,
        "inductance": "10 uH",
        "current_rating": "1 A",
        "dc_resistance": "1 ohm",
        "impedance": "100 ohm",
        "impedance_frequency": "100 MHz",
        "frequency": "8 MHz",
        "load_capacitance": "10 pF",
        "frequency_tolerance": "10 ppm",
        "type": "synthetic",
        "color": "red",
        "manufacturer": "Synthetic",
        "mpn": "REVIEW_TEST",
        "supply_min": "0 V",
        "supply_max": "5 V",
        "output_voltage": "3.3 V",
        "positions": 16,
        "pitch": "2.54 mm",
        "initial_state": "open",
    }
    counts = {category: 2 for category in REQUIRED}
    counts.update(ic=32, connector=16, transistor=3, regulator=3, testpoint=1)
    if large:
        counts = {f"chip{i}": 100 for i in range(100)}
    devices, parts, nets, nc = {}, {}, {}, []
    for i, (name, count) in enumerate(counts.items()):
        category = "ic" if large else name
        pin_names = [f"P{n}" for n in range(1, count + 1)]
        devices[name] = {
            "category": category,
            "prefix": "U",
            "pins": {p: {"type": "PASSIVE"} for p in pin_names},
            "packages": {
                "test": {
                    "allegro": "SYNTHETIC",
                    "pads": {str(n): p for n, p in enumerate(pin_names, 1)},
                }
            },
            "properties": {k: properties[k] for k in REQUIRED[category]},
        }
        parts[name] = {
            "id": name,
            "device": name,
            "package": "test",
            "assembly": "dnp" if name == "capacitor" else "fitted",
        }
        for n, pin in enumerate(pin_names, 1):
            endpoint = {"part": name, "pin": pin}
            if large:
                # Ten thousand pins, with meaningful point-to-point signal edges.
                net = f"N{i // 2}_{n}"
            elif name == "ic":
                net = {
                    1: "BUS",
                    2: "BUS",
                    3: "GND",
                    4: "VDD",
                    5: "SELF",
                    6: "SELF",
                    7: "ONLY",
                }.get(n)
                if net is None:
                    nc.append(endpoint)
                    continue
            elif n == 1:
                net = "BUS"
            elif n == 2:
                net = "AGND" if i % 3 == 0 else "VDD"
            else:
                nc.append(endpoint)
                continue
            nets.setdefault(net, {"endpoints": []})["endpoints"].append(endpoint)
    doc = {
        "version": 2,
        "id": "pin-graph-large" if large else "pin-graph",
        "name": "synthetic_pin_graph",
        "library": {"name": "test", "version": "1"},
        "top": "board",
        "modules": {"board": {"parts": parts, "nets": nets, "nc": nc}},
    }
    catalog = root / "catalogs/test"
    catalog.mkdir(parents=True)
    (catalog / "1.json").write_text(
        json.dumps({"version": 2, "name": "test", "revision": "1", "devices": devices})
    )
    source = root / "board.circuit"
    source.write_text(dumps(doc))
    output = root / "output"
    export_design(
        compile_design(load_design(source, library_root=root / "catalogs")), output
    )
    return output


@contextmanager
def serve(output, state):
    with ReviewServer(output, state_dir=state) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield server
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.fixture
def graph_page(browser, tmp_path):
    output = synthetic_package(tmp_path / "project")
    before = {
        p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()
    }
    with serve(output, tmp_path / "state") as server:
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(server.url)
        expect(page.locator("#save-state")).to_contain_text("已载入")
        expect(page.locator("#graph-loading")).to_be_hidden()
        yield page, server
        assert not errors
        context.close()
    assert {
        p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()
    } == before


def test_pin_inventory_connections_and_review(graph_page):
    page, server = graph_page
    assert page.evaluate('cy.nodes(".part").length') == 0
    assert sorted(page.evaluate('cy.nodes(".pin").map(n=>n.data("pinId"))')) == sorted(
        server.package["pins"]
    )
    # Every signal endpoint occurs exactly once in actual network edges.
    actual = page.evaluate('cy.edges(".wire").flatMap(e=>e.data("pins"))')
    expected = page.evaluate(
        'Object.values(pkg.pins).filter(p=>!p.nc && ReviewGraphModel.classify(pkg.nets[p.net],railOverrides).role==="signal").map(p=>p.id)'
    )
    assert sorted(actual) == sorted(expected)
    assert page.evaluate(
        'cy.edges(".wire").every(e=>e.data("pins").every(id=>"net:"+pkg.pins[id].net===e.data("netKey")))'
    )
    assert page.evaluate('cy.nodes(".pin").every(n=>n.grabbable())')
    assert page.evaluate('cy.nodes(".net").every(n=>!n.selectable())')
    key = page.evaluate('"pin:" + pkg.parts.ic.pins[0]')
    page.evaluate("(key)=>selectObject(key)", key)
    page.locator("#review-status").select_option("approved")
    expect(page.locator("#save-state")).to_contain_text("已保存")
    assert server.store.read()["entries"][key]["status"] == "approved"


def test_trace_controls_multiselect_and_clear(graph_page):
    page, server = graph_page
    root = server.package["parts"]["ic"]["pins"][0]
    page.evaluate('(id)=>selectObject("pin:"+id)', root)
    page.get_by_role("button", name="从此追踪", exact=True).click()
    expect(page.locator("#trace-summary")).to_contain_text("起点")
    page.get_by_role("button", name="仅看连接链", exact=True).click()
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert page.evaluate('cy.nodes(".pin").length') < len(server.package["pins"])
    # IC SELF and ONLY are disconnected until the user selects the IC exits.
    choices = [
        p
        for p in server.package["pins"].values()
        if p["ref"] == "ic" and p["net"] in ("SELF", "ONLY")
    ]
    first = choices[0]["id"]
    page.locator(f'.trace-exits input[value="{first}"]').check()
    page.locator("#apply-trace-exits").click()
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert page.evaluate("(id)=>currentChain.pins.has(id)", first)
    assert page.evaluate('cy.edges(".transition").length') > 0
    page.locator(f'.trace-exits input[value="{first}"]').uncheck()
    page.locator("#apply-trace-exits").click()
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert not page.evaluate("(id)=>currentChain.pins.has(id)", first)
    page.locator("#trace-clear").click()
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert page.evaluate('cy.nodes(".pin").length') == len(server.package["pins"])
    assert server.store.read()["entries"] == {}


def test_rail_roles_persistence_and_stops(graph_page):
    page, server = graph_page
    for name, aliases, electrical, expected in [
        ("GND", [], {}, "ground"),
        ("AGND", [], {}, "ground"),
        ("GND_SENSE", [], {}, "signal"),
        ("ENABLE_VDD", [], {}, "signal"),
        ("GND", ["VCC"], {}, "signal"),
        ("rail", ["mod/VDD"], {}, "power"),
        ("VCC", [], {"role": "signal"}, "signal"),
        ("custom", [], {"role": "ground"}, "ground"),
        ("+5V", [], {}, "power"),
        ("-12V", [], {}, "power"),
    ]:
        assert (
            page.evaluate(
                "(n)=>ReviewGraphModel.classify(n,{}).role",
                {"name": name, "aliases": aliases, "electrical": electrical},
            )
            == expected
        )
    root = server.package["nets"]["VDD"]["pins"][0]
    page.evaluate('(id)=>selectObject("pin:"+id)', root)
    page.get_by_role("button", name="从此追踪", exact=True).click()
    assert page.evaluate("currentChain.pins.size") == 1
    page.evaluate('selectObject("net:VDD")')
    page.locator("#net-display-role").select_option("signal")
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert page.evaluate("currentChain.pins.size") > 1
    assert page.evaluate('cy.getElementById("net:VDD").length') == 1
    page.reload()
    expect(page.locator("#save-state")).to_contain_text("已载入")
    page.evaluate('selectObject("net:VDD")')
    expect(page.locator("#net-display-role")).to_have_value("signal")
    assert page.evaluate("traceRoot") is None
    assert server.store.read()["entries"] == {}
    page.evaluate('()=>{Storage.prototype.setItem=()=>{throw new Error("full")};}')
    page.locator("#net-display-role").select_option("auto")
    expect(page.locator("#display-warning")).to_contain_text("未持久化")


@pytest.mark.parametrize("width,height", [(1280, 800), (1440, 900), (1920, 1080)])
def test_pin_visuals_and_readable_bounds(graph_page, width, height):
    page, _ = graph_page
    page.set_viewport_size({"width": width, "height": height})
    page.evaluate('selectObject("pin:"+pkg.parts.ic.pins[0])')
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert page.evaluate("document.documentElement.scrollWidth") == width
    assert page.locator("#graph").bounding_box()["width"] > 400
    # Labels use conservative measured character widths, inside independent cards.
    assert page.evaluate("""cy.nodes('.pin').every(n=>{
      const b=n.boundingBox({includeLabels:true,includeOverlays:false});
      return b.w <= n.width()+5 && b.h <= n.height()+5;
    })""")
    assert page.evaluate(
        """cy.nodes('.pin').filter(n=>!n.hasClass('compact')).every(n=>{
      const b=n.boundingBox({includeNodes:false,includeLabels:true,includeOverlays:false});
      return b.x1 >= n.position('x')-n.width()/2+50 && b.y2 <= n.position('y')+n.data('anchorY')-8;
    })"""
    )
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ARTIFACT / f"pin-chain-{width}.png"))


def test_ten_thousand_pins_remain_searchable(browser, tmp_path):
    output = synthetic_package(tmp_path / "large", large=True)
    with serve(output, tmp_path / "state") as server:
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.add_init_script(
            'window.busyTicks=0;setInterval(()=>{if(document.getElementById("graph-loading")?.hidden===false)window.busyTicks++},20)'
        )
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        started = time.monotonic()
        page.goto(server.url)
        expect(page.locator("#save-state")).to_contain_text("已载入", timeout=30000)
        expect(page.locator("#graph-loading")).to_be_hidden(timeout=30000)
        assert page.evaluate('cy.nodes(".pin").length') == 10000
        assert page.evaluate('cy.edges(".wire").length') == 5000
        metrics = page.evaluate("({...graphMetrics,busyTicks})")
        assert metrics["layout"] == "elk-pin-layered"
        assert metrics["busyTicks"] > 0
        metrics["load_ms"] = (time.monotonic() - started) * 1000
        started = time.monotonic()
        page.locator("#search").fill("chip99")
        expect(page.locator("#list-count")).to_have_text("1 个结果", timeout=10000)
        expect(page.locator("#graph-loading")).to_be_hidden(timeout=30000)
        assert page.evaluate('cy.nodes(".pin").length') == 100
        page.locator(".object-row").click()
        expect(page.locator("#detail")).to_contain_text("chip99")
        metrics["locate_ms"] = (time.monotonic() - started) * 1000
        ARTIFACT.mkdir(parents=True, exist_ok=True)
        (ARTIFACT / "10000-pins-metrics.json").write_text(json.dumps(metrics, indent=2))
        assert not errors
        context.close()


def test_display_settings_isolation_and_unavailable_storage(graph_page):
    page, _ = graph_page
    page.evaluate("""()=>{
      localStorage.setItem('design2allegro.display:'+JSON.stringify([pkg.board_id,'other']),JSON.stringify({VDD:'signal'}));
      localStorage.setItem('design2allegro.display:'+JSON.stringify(['other',pkg.fingerprint]),JSON.stringify({VDD:'signal'}));
    }""")
    page.reload()
    expect(page.locator("#save-state")).to_contain_text("已载入")
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert page.evaluate('cy.nodes(".power").length') > 0
    assert page.evaluate('cy.getElementById("net:VDD").length') == 0
    page.add_init_script(
        'Storage.prototype.getItem=()=>{throw new Error("unavailable")};'
    )
    page.reload()
    expect(page.locator("#save-state")).to_contain_text("已载入")
    expect(page.locator("#display-warning")).to_contain_text("无法读取")


def test_clear_exits_retains_other_branch_in_ui(graph_page):
    page, server = graph_page
    pins = server.package["parts"]["ic"]["pins"]
    root = pins[0]
    targets = [p for p in pins if server.package["pins"][p]["net"] in ("SELF", "ONLY")]
    page.evaluate('(id)=>selectObject("pin:"+id)', root)
    page.get_by_role("button", name="从此追踪", exact=True).click()
    for identity in targets:
        page.locator(f'.trace-exits input[value="{identity}"]').check()
    page.locator("#apply-trace-exits").click()
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert page.evaluate("(ids)=>ids.every(id=>currentChain.pins.has(id))", targets)
    # Remove one of the same-net exits: both SELF pins remain reachable.
    self_pins = [p for p in targets if server.package["pins"][p]["net"] == "SELF"]
    page.locator(f'.trace-exits input[value="{self_pins[0]}"]').uncheck()
    page.locator("#apply-trace-exits").click()
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert page.evaluate("(ids)=>ids.every(id=>currentChain.pins.has(id))", self_pins)
    # Auxiliary graph nodes must never become extra batch-review objects.
    page.evaluate("()=>{cy.nodes().select()}")
    page.wait_for_timeout(50)
    assert page.evaluate('[...selected].every(key=>key.startsWith("pin:"))')


def test_category_symbols_states_and_fallback(graph_page):
    page, server = graph_page
    assert page.evaluate("""cy.nodes('.pin').every(n=>
      n.data('category')===pkg.parts[pkg.pins[n.data('pinId')].ref].category &&
      n.style('background-opacity')==='0' && n.style('border-width')==='0px')""")
    images = page.evaluate("""()=>Object.fromEntries(Object.values(pkg.parts).map(p=>{
      const n=cy.getElementById('pin:'+p.pins[0]);return [p.category,n.data('image')];
    }))""")
    assert len(images) == 14
    assert len(set(images.values())) == 14
    assert all(value.startswith("data:image/svg+xml") for value in images.values())
    assert page.evaluate("""()=>{
      const options={width:210,height:86,anchorY:10};
      return ReviewSymbols.image({...options,category:'missing'})===ReviewSymbols.image({...options,category:'generic'});
    }""")
    key = "pin:" + server.package["parts"]["ic"]["pins"][0]
    page.evaluate("(key)=>selectObject(key)", key)
    before = page.evaluate('(key)=>cy.getElementById(key).data("image")', key)
    page.locator("#review-status").select_option("approved")
    expect(page.locator("#save-state")).to_contain_text("已保存")
    approved = page.evaluate('(key)=>cy.getElementById(key).data("image")', key)
    assert approved != before
    page.locator("#review-status").select_option("issue")
    expect(page.locator("#save-state")).to_contain_text("已保存")
    assert page.evaluate('(key)=>cy.getElementById(key).data("image")', key) not in (
        before,
        approved,
    )
    page.evaluate('()=>{cy.elements().removeClass("highlight chain");cy.zoom(.4)}')
    assert page.evaluate(
        'cy.nodes(".pin").every(n=>n.hasClass("compact") && n.data("image"))'
    )
    page.evaluate(
        "(key)=>{cy.getElementById(key).select();syncSelection();updateDetailLevel()}",
        key,
    )
    assert page.evaluate('(key)=>!cy.getElementById(key).hasClass("compact")', key)


def test_symbol_drag_keeps_rendered_wires_at_anchor(graph_page):
    page, server = graph_page
    key = "pin:" + server.package["parts"]["resistor"]["pins"][0]
    result = page.evaluate(
        """key=>{
      const n=cy.getElementById(key),before={...n.position()};
      n.emit('grab');n.position({x:before.x+83,y:before.y+47});n.emit('free');
      return {before,after:{...n.position()},routes:n.connectedEdges().map(e=>({
        source:{...e.source().position(),offset:e.source().data('anchorY')},
        target:{...e.target().position(),offset:e.target().data('anchorY')},
        points:[e.sourceEndpoint(),...(e.segmentPoints()||[]),e.targetEndpoint()]
      }))};
    }""",
        key,
    )
    assert result["after"] == {
        "x": result["before"]["x"] + 83,
        "y": result["before"]["y"] + 47,
    }
    for route in result["routes"]:
        for endpoint, point in [
            (route["source"], route["points"][0]),
            (route["target"], route["points"][-1]),
        ]:
            assert point["x"] == pytest.approx(endpoint["x"], abs=0.1)
            assert point["y"] == pytest.approx(
                endpoint["y"] + endpoint["offset"], abs=0.1
            )
        for a, b in zip(route["points"], route["points"][1:]):
            assert abs(a["x"] - b["x"]) < 0.1 or abs(a["y"] - b["y"]) < 0.1
    page.locator("#layout").click()
    expect(page.locator("#graph-loading")).to_be_hidden()
