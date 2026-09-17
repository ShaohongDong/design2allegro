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


def assert_endpoints(page):
    failures = page.evaluate("""() => cy.edges().not('.lead').map(e => {
      const a=e.sourceEndpoint(), b=e.targetEndpoint();
      const p=e.source().position(), q=e.target().position();
      return {id:e.id(), error: Math.max(Math.hypot(a.x-p.x,a.y-p.y),Math.hypot(b.x-q.x,b.y-q.y))};
    }).filter(x => !Number.isFinite(x.error) || x.error > 0.1)""")
    assert failures == []


def test_categories_connectivity_drag_and_pin_review(graph_page):
    page, server = graph_page
    assert page.evaluate('cy.nodes(".pin").length') == len(server.package["pins"])
    assert page.evaluate(
        'new Set(cy.nodes(".part").map(n=>n.data("image"))).size'
    ) == len(REQUIRED)
    assert page.evaluate('cy.nodes(".nc").length') > 0
    assert page.evaluate('cy.nodes(".nc").connectedEdges().not(".lead").length') == 0
    # Independent inventory check: each connected pin occurs once in actual wires.
    memberships = page.evaluate('cy.edges().not(".lead").flatMap(e=>e.data("pins"))')
    assert sorted(memberships) == sorted(
        k for k, p in server.package["pins"].items() if not p["nc"]
    )
    assert (
        page.evaluate(
            'cy.edges(".wire").filter(e=>e.data("netKey")==="net:SELF").length'
        )
        == 1
    )
    assert (
        page.evaluate('cy.nodes(".junction").filter(n=>n.id()==="net:BUS").length') == 1
    )
    assert (
        page.evaluate(
            'cy.edges(".wire").filter(e=>["net:GND","net:AGND","net:VDD"].includes(e.data("netKey"))).length'
        )
        == 0
    )
    assert_endpoints(page)
    # Move a high pin count body and validate every attachment and wire afterwards.
    page.evaluate('() => { cy.getElementById("part:ic").position({x:200,y:200}); }')
    assert page.evaluate(
        'cy.nodes(".pin").filter(n=>n.data("owner")==="part:ic").every(n=>Math.abs(n.position("x")-200-n.data("dx"))<0.01 && Math.abs(n.position("y")-200-n.data("dy"))<0.01)'
    )
    assert_endpoints(page)
    page.evaluate('selectObject("pin:ic.P2")')
    expect(page.locator("#detail")).to_contain_text("物理焊盘")
    page.locator("#review-status").select_option("issue")
    expect(page.locator("#save-state")).to_contain_text("已保存")
    assert server.store.read()["entries"]["pin:ic.P2"]["status"] == "issue"
    # Physical click on the independent pin, not a programmatic tap event.
    page.evaluate('() => { cy.stop(true); cy.fit(cy.getElementById("part:ic"), 80); }')
    point = page.evaluate('cy.getElementById("pin:ic.P3").renderedPosition()')
    box = page.locator("#graph").bounding_box()
    page.mouse.click(box["x"] + point["x"], box["y"] + point["y"])
    expect(page.locator("#detail .detail-path")).to_have_text("ic.P3")
    page.locator("#layout").click()
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert_endpoints(page)
    assert page.evaluate("""() => cy.edges('.lead').every(e => {
      const a=e.sourceEndpoint(), b=e.targetEndpoint();
      const n=e.source(),pin=e.target(),d=pin.data('direction');
      const distance=n.data('symbol')?18:20;
      return (['W','E'].includes(d)?Math.abs(a.y-b.y)<0.1:Math.abs(a.x-b.x)<0.1)
        && Math.abs(Math.hypot(a.x-b.x,a.y-b.y)-distance)<0.1;
    })""")


def test_rail_rules_overrides_storage_and_clicks(graph_page):
    page, server = graph_page
    checks = [
        ("GND", [], {}, "ground"),
        ("AGND", [], {}, "ground"),
        ("GND_SENSE", [], {}, "signal"),
        ("ENABLE_VDD", [], {}, "signal"),
        ("GND", ["VCC"], {}, "signal"),
        ("rail", ["mod/VDD"], {}, "power"),
        ("VCC", [], {"role": "signal"}, "signal"),
        ("custom", [], {"role": "ground"}, "ground"),
        ("VDD", [], {}, "power"),
        ("+5V", [], {}, "power"),
        ("-12V", [], {}, "power"),
    ]
    for name, aliases, electrical, expected in checks:
        result = page.evaluate(
            "(n)=>ReviewGraphModel.classify(n,{})",
            {"name": name, "aliases": aliases, "electrical": electrical},
        )
        assert result["role"] == expected
    page.evaluate('selectObject("net:VDD")')
    page.locator("#net-display-role").select_option("signal")
    assert (
        page.evaluate('cy.nodes(".rail").filter(n=>n.data("key")==="net:VDD").length')
        == 0
    )
    page.reload()
    expect(page.locator("#save-state")).to_contain_text("已载入")
    page.evaluate('selectObject("net:VDD")')
    expect(page.locator("#net-display-role")).to_have_value("signal")
    assert server.store.read()["entries"] == {}
    page.locator("#net-display-role").select_option("auto")
    expect(page.locator("#graph-loading")).to_be_hidden()
    page.evaluate('() => { cy.stop(true); cy.fit(cy.getElementById("part:ic"), 100); }')
    point = page.evaluate(
        'cy.nodes(".rail").filter(n=>n.data("owner")==="part:ic" && n.data("key")==="net:GND")[0].renderedPosition()'
    )
    box = page.locator("#graph").bounding_box()
    page.mouse.click(box["x"] + point["x"], box["y"] + point["y"])
    expect(page.locator("#detail h1")).to_have_text("GND")
    assert page.locator(".endpoint").count() == len(
        server.package["nets"]["GND"]["pins"]
    )
    page.evaluate(
        '() => { Storage.prototype.setItem = () => { throw new Error("full"); }; }'
    )
    page.locator("#net-display-role").select_option("signal")
    expect(page.locator("#display-warning")).to_contain_text("未持久化")
    assert (
        page.evaluate("ReviewGraphModel.classify(pkg.nets.GND,railOverrides).role")
        == "signal"
    )


@pytest.mark.parametrize("width,height", [(1440, 900), (1920, 1080)])
def test_dense_pin_visuals(graph_page, width, height):
    page, _ = graph_page
    page.set_viewport_size({"width": width, "height": height})
    page.evaluate(
        '() => { selectObject("part:ic"); cy.stop(true); cy.fit(cy.getElementById("part:ic").union(cy.nodes().filter(n=>n.data("owner")==="part:ic")),55); }'
    )
    page.wait_for_function('cy.nodes(".part").every(n=>n.backgrounding()===false)')
    assert page.evaluate("document.documentElement.scrollWidth") == width
    # Names/physical numbers have distinct measured rendered bounds on each side.
    assert page.evaluate("""() => {
      for (const side of ['left','right']) {
        const pins=cy.nodes('.pin.'+side).filter(n=>n.data('owner')==='part:ic').sort((a,b)=>a.position('y')-b.position('y'));
        for(let i=1;i<pins.length;i++) if(pins[i-1].renderedBoundingBox().y2>=pins[i].renderedBoundingBox().y1) return false;
      }
      return true;
    }""")
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ARTIFACT / f"pins-{width}.png"))
    page.locator("#restore").click()
    expect(page.locator("#graph-loading")).to_be_hidden()
    page.evaluate("() => { cy.fit(undefined, 40); }")
    page.screenshot(path=str(ARTIFACT / f"categories-{width}.png"))


def test_ten_thousand_pins_remain_searchable(browser, tmp_path):
    output = synthetic_package(tmp_path / "large", large=True)
    with serve(output, tmp_path / "state") as server:
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.add_init_script("""window.reviewBusyTicks=0;
          setInterval(()=>{const el=document.getElementById('graph-loading');
            if(el && !el.hidden) window.reviewBusyTicks++;},20);""")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        started = time.monotonic()
        page.goto(server.url)
        expect(page.locator("#save-state")).to_contain_text("已载入", timeout=30000)
        expect(page.locator("#graph-loading")).to_be_hidden(timeout=30000)
        load_ms = (time.monotonic() - started) * 1000
        assert page.evaluate('cy.nodes(".pin").length') == 10000
        assert page.evaluate('cy.edges(".wire").length') == 5000
        metrics = page.evaluate("({...graphMetrics})")
        assert metrics["layout"] == "elk-layered"
        assert metrics["failedRoutes"] == 0
        assert metrics["conflicts"] == 0
        assert page.evaluate("reviewBusyTicks") > 10
        started = time.monotonic()
        page.locator("#search").fill("chip99")
        expect(page.locator("#list-count")).to_have_text("1 个结果", timeout=10000)
        page.locator(".object-row").click()
        expect(page.locator("#detail")).to_contain_text("chip99")
        metrics.update(load_ms=load_ms, locate_ms=(time.monotonic() - started) * 1000)
        ARTIFACT.mkdir(parents=True, exist_ok=True)
        (ARTIFACT / "10000-pins-metrics.json").write_text(json.dumps(metrics, indent=2))
        assert not errors
        context.close()


def test_display_settings_are_isolated_and_read_failure_is_nonfatal(graph_page):
    page, server = graph_page
    page.evaluate("""() => {
      localStorage.setItem('design2allegro.display:'+JSON.stringify([pkg.board_id,'another-fingerprint']),JSON.stringify({VDD:'signal'}));
      localStorage.setItem('design2allegro.display:'+JSON.stringify(['another-board',pkg.fingerprint]),JSON.stringify({VDD:'signal'}));
    }""")
    page.reload()
    expect(page.locator("#save-state")).to_contain_text("已载入")
    assert (
        page.evaluate('cy.nodes(".rail").filter(n=>n.data("key")==="net:VDD").length')
        == 8
    )
    page.add_init_script(
        'Storage.prototype.getItem = () => { throw new Error("unavailable"); };'
    )
    page.reload()
    expect(page.locator("#save-state")).to_contain_text("已载入")
    expect(page.locator("#display-warning")).to_contain_text("无法读取")
    assert server.store.read()["entries"] == {}


def assert_ground_directions(page):
    assert page.evaluate("""()=>cy.nodes('.ground').every(n=>{
      const pin=n.connectedEdges('.rail-wire')[0].source();
      return n.data('rotation')===ReviewGraphModel.groundAppearance(pin.position(),n.position()).rotation;
    })""")


def test_ground_direction_vectors_and_attachment_updates(graph_page):
    page, _ = graph_page
    for x, y, side, rotation in [
        (-65, 0, -1, 90),
        (65, 0, 1, 270),
        (0, -65, 1, 180),
        (0, 65, 1, 0),
        (0, 0, -1, 90),
        (0, 0, 1, 270),
        (65, 65, 1, 315),
    ]:
        result = page.evaluate(
            "([x,y,side]) => ReviewGraphModel.groundAppearance({x:0,y:0},{x,y},side)",
            [x, y, side],
        )
        assert result["rotation"] == rotation
        svg = unquote(result["image"].split(",", 1)[1])
        assert 'viewBox="0 0 48 48"' in svg
        assert f"rotate({rotation} 24 24)" in svg
    assert_ground_directions(page)
    # Exercise upper and lower attachments through the same drag/layout update path.
    for dy, rotation in [(-65, 180), (65, 0)]:
        actual = page.evaluate(
            """([dy]) => {
          const rail=cy.nodes('.ground').filter(n=>n.data('owner')==='part:ic')[0];
          const pin=rail.connectedEdges('.rail-wire')[0].source();
          rail.data({dx:pin.data('dx'),dy:pin.data('dy')+dy});
          positionAttachments('part:ic');
          return rail.data('rotation');
        }""",
            [dy],
        )
        assert actual == rotation
        assert_endpoints(page)
    page.locator("#layout").click()
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert_endpoints(page)
    page.evaluate(
        '() => { cy.getElementById("part:resistor").position({x:200,y:300}); }'
    )
    assert_ground_directions(page)
    assert_endpoints(page)


@pytest.mark.parametrize("width,height", [(1440, 900), (1920, 1080)])
def test_ground_rotation_visuals_and_role_switch(graph_page, width, height):
    page, _ = graph_page
    page.set_viewport_size({"width": width, "height": height})
    page.evaluate('selectObject("net:BUS")')
    page.locator("#net-display-role").select_option("ground")
    expect(page.locator("#graph-loading")).to_be_hidden()
    assert_ground_directions(page)
    page.locator("#net-display-role").select_option("power")
    assert page.evaluate(
        'cy.nodes(".power").filter(n=>n.data("key")==="net:BUS").every(n=>n.data("image")===ReviewGraphModel.image("power"))'
    )
    page.locator("#net-display-role").select_option("ground")
    page.evaluate("""() => {
      manuallyHidden=new Set(Object.values(pkg.parts).filter(p=>!['resistor','capacitor'].includes(p.id)).map(p=>p.key));
      buildGraph();
    }""")
    expect(page.locator("#graph-loading")).to_be_hidden()
    page.evaluate("""() => {
      cy.getElementById('part:resistor').position({x:0,y:0});
      cy.getElementById('part:capacitor').position({x:0,y:180});
      cy.fit(undefined,90);
    }""")
    page.wait_for_function('cy.nodes(".ground").every(n=>n.backgrounding()===false)')
    assert page.evaluate(
        'cy.nodes(".ground").every(n=>n.style("text-rotation")==="none" && Number.isFinite(parseFloat(n.style("text-margin-x"))) && Number.isFinite(parseFloat(n.style("text-margin-y"))))'
    )
    assert_endpoints(page)
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ARTIFACT / f"ground-rotation-{width}.png"))
