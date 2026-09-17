"""Independent geometric and interaction acceptance for automatic routing."""

from pathlib import Path

import pytest
from playwright.sync_api import expect
from test_browser import browser, page  # noqa: F401


@pytest.fixture
def app(tmp_path):
    # Compile a real two-module circuit with a cross-module signal.
    import shutil
    import threading

    from design2allegro import compile_design, export_design, load_design
    from design2allegro.review import ReviewServer

    project = tmp_path / "project"
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "fixtures/parameterized", project
    )
    board = project / "board.circuit"
    board.write_text(
        board.read_text()
        .replace("net IN = sense.IN;", "net IN = sense.IN, other.IN;")
        .replace("net IN2 = other.IN;", "")
    )
    output = tmp_path / "output"
    export_design(compile_design(load_design(board)), output)
    with ReviewServer(output, state_dir=tmp_path / "state") as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server
        server.shutdown()
        thread.join(timeout=5)


from test_pin_graph import ARTIFACT, graph_page  # noqa: F401


def wait_layout(page):
    expect(page.locator("#graph-loading")).to_be_hidden(timeout=30000)
    assert page.evaluate("graphMetrics.layout") == "elk-layered"
    assert page.locator("#layout-warning").inner_text() == ""


def diagram(page):
    return page.evaluate("""() => {
      cy.nodes().removeClass('compact');
      const edges=cy.edges('.wire, .rail-wire').map(e=>{
        const a=e.source(),b=e.target();
        const side=n=>(n.hasClass('pin')||n.hasClass('port'))?({W:-1,E:1}[n.data('direction')]||0):0;
        return {id:e.id(),a:{...a.position()},b:{...b.position()},sa:side(a),sb:side(b),
          sourceDirection:a.data('direction'),targetDirection:b.data('direction'),
          ignore:[a,b].filter(n=>n.hasClass('net')||n.hasClass('rail')).map(n=>n.id())};
      });
      const obstacles=cy.nodes('.part, .module, .net, .rail').map(n=>{
        const p=n.position(),body=n.hasClass('part')||n.hasClass('module');
        const b=body?{x1:p.x-n.width()/2,x2:p.x+n.width()/2,y1:p.y-n.height()/2,y2:p.y+n.height()/2}:
          n.boundingBox({includeNodes:!n.hasClass('net'),includeLabels:true,includeOverlays:false,useCache:false});
        return {id:n.id(),...b};
      });
      const routes=cy.edges('.wire, .rail-wire').map(e=>({
        id:e.id(),net:e.data('netKey'),points:e.data('routePoints'),
        rendered:[e.sourceEndpoint(),...(e.segmentPoints()||[]),e.targetEndpoint()],
        failed:e.hasClass('route-failed')}));
      updateDetailLevel();
      return {snapshot:{edges,obstacles},routes};
    }""")


def near(a, b):
    return abs(a["x"] - b["x"]) < 0.1 and abs(a["y"] - b["y"]) < 0.1


def intersects(a, b, r):
    # Open rectangle intersection: a path on the clearance boundary is legal.
    if abs(a["x"] - b["x"]) < 0.1:
        return (
            r["x1"] + 0.1 < a["x"] < r["x2"] - 0.1
            and max(a["y"], b["y"]) > r["y1"] + 0.1
            and min(a["y"], b["y"]) < r["y2"] - 0.1
        )
    return (
        r["y1"] + 0.1 < a["y"] < r["y2"] - 0.1
        and max(a["x"], b["x"]) > r["x1"] + 0.1
        and min(a["x"], b["x"]) < r["x2"] - 0.1
    )


def assert_geometry(data):
    edges = {e["id"]: e for e in data["snapshot"]["edges"]}
    segments = []
    for route in data["routes"]:
        assert not route["failed"], route["id"]
        edge = edges[route["id"]]
        points = route["points"]
        assert near(points[0], edge["a"]) and near(points[-1], edge["b"])
        if edge["sa"]:
            assert abs(points[1]["y"] - points[0]["y"]) < 0.1
            assert (points[1]["x"] - points[0]["x"]) * edge["sa"] >= 27.9
        if edge["sb"]:
            assert abs(points[-2]["y"] - points[-1]["y"]) < 0.1
            assert (points[-2]["x"] - points[-1]["x"]) * edge["sb"] >= 27.9
        for points_to_check in [points, route["rendered"]]:
            for a, b in zip(points_to_check, points_to_check[1:]):
                assert abs(a["x"] - b["x"]) < 0.1 or abs(a["y"] - b["y"]) < 0.1, route
        for a, b in zip(points, points[1:]):
            for obstacle in data["snapshot"]["obstacles"]:
                if obstacle["id"] not in edge["ignore"]:
                    clearance = {
                        k: obstacle[k] + (12 if k in ("x2", "y2") else -12)
                        for k in ("x1", "y1", "x2", "y2")
                    }
                    assert not intersects(a, b, clearance), (
                        route["id"],
                        obstacle["id"],
                    )
            for net, c, d in segments:
                if net == route["net"]:
                    continue
                if abs(a["x"] - b["x"]) < 0.1 and abs(c["x"] - d["x"]) < 0.1:
                    assert (
                        abs(a["x"] - c["x"]) >= 0.1
                        or min(max(a["y"], b["y"]), max(c["y"], d["y"]))
                        <= max(min(a["y"], b["y"]), min(c["y"], d["y"])) + 0.1
                    )
                if abs(a["y"] - b["y"]) < 0.1 and abs(c["y"] - d["y"]) < 0.1:
                    assert (
                        abs(a["y"] - c["y"]) >= 0.1
                        or min(max(a["x"], b["x"]), max(c["x"], d["x"]))
                        <= max(min(a["x"], b["x"]), min(c["x"], d["x"])) + 0.1
                    )
            segments.append((route["net"], a, b))


def test_geometry_and_relayout_preserves_inventory(graph_page):
    page, _ = graph_page
    wait_layout(page)
    assert_geometry(diagram(page))
    geometry = page.evaluate(
        'cy.nodes().map(n=>({id:n.id(),p:{...n.position()},direction:n.data("direction")}))'
    )
    page.evaluate('selectObject("part:resistor")')
    assert geometry == page.evaluate(
        'cy.nodes().map(n=>({id:n.id(),p:{...n.position()},direction:n.data("direction")}))'
    )
    before = page.evaluate('cy.nodes(".part, .pin, .net").map(n=>n.id()).sort()')
    page.locator("#layout").click()
    wait_layout(page)
    assert before == page.evaluate(
        'cy.nodes(".part, .pin, .net").map(n=>n.id()).sort()'
    )
    assert_geometry(diagram(page))


@pytest.mark.parametrize("width", [1440, 1920])
def test_module_labels_and_inventory(page, app, width):
    page.set_viewport_size({"width": width, "height": 1080})
    wait_layout(page)
    assert page.evaluate('cy.nodes(".region").length') == 2
    assert page.evaluate('cy.nodes(".cross-terminal").length') > 0
    assert page.evaluate("""cy.edges('.wire').every(e=> {
      const a=e.source(),b=e.target();
      const group=n=>n.data('owner')?cy.getElementById(n.data('owner')).data('group'):n.data('group');
      return group(a)===group(b);
    })""")
    assert_geometry(diagram(page))
    key = page.evaluate('cy.nodes(".cross-terminal")[0].data("key")')
    page.evaluate("(key)=>selectObject(key)", key)
    wait_layout(page)
    expect(page.locator("#detail")).to_contain_text("跨模块连接")
    assert page.evaluate('cy.nodes(".cross-terminal.highlight").length') >= 2
    expect(page.locator(".endpoint")).to_have_count(
        len(app.package["nets"][key[4:]]["pins"])
    )
    page.locator("#collapse").click()
    wait_layout(page)
    assert_geometry(diagram(page))
    memberships = page.evaluate(
        'cy.edges(".wire, .rail-wire").flatMap(e=>e.data("pins"))'
    )
    assert sorted(memberships) == sorted(
        k for k, p in app.package["pins"].items() if not p["nc"]
    )
    page.locator("#restore").click()
    wait_layout(page)
    ARTIFACT.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(ARTIFACT / f"module-layout-{width}.png"))


def test_drag_preserves_position_and_relayout_recovers(graph_page):
    page, _ = graph_page
    wait_layout(page)
    # Move a body, retain its exact coordinates, then recover via explicit layout.
    choice = page.evaluate("""() => {
      const n=cy.getElementById('part:ic');
      return {id:n.id(),x:n.position('x')+170,y:n.position('y')+110};
    }""")
    page.evaluate(
        '(p)=>{const n=cy.getElementById(p.id);n.emit("grab");n.position({x:p.x,y:p.y});n.emit("free");}',
        choice,
    )
    # The scheduler is deliberately debounced; wait for its actual completion.
    page.wait_for_timeout(150)
    expect(page.locator("#graph-loading")).to_be_hidden(timeout=30000)
    assert page.evaluate(
        "(id)=>({...cy.getElementById(id).position()})", choice["id"]
    ) == {k: choice[k] for k in ("x", "y")}
    assert not page.evaluate('cy.edges(".route-pending").length')
    # Recovery handles user-created overlaps without moving unrelated bodies.
    page.locator("#layout").click()
    wait_layout(page)
    assert_geometry(diagram(page))


def test_worker_failure_retry_and_stale_results(page):
    wait_layout(page)
    before = page.evaluate('cy.nodes(".part").map(n=>({...n.position()}))')
    page.route("**/graph-worker.js", lambda route: route.abort())
    page.locator("#layout").click()
    expect(page.locator("#layout-warning")).to_contain_text("失败")
    assert before == page.evaluate('cy.nodes(".part").map(n=>({...n.position()}))')
    page.unroute("**/graph-worker.js")
    page.locator("#layout").click()
    page.locator("#collapse").click()
    page.locator("#restore").click()
    wait_layout(page)
    assert page.evaluate('cy.nodes(".part").length') == 4
    assert_geometry(diagram(page))


def test_moving_unconnected_obstacle_repairs_existing_wire(graph_page):
    page, _ = graph_page
    wait_layout(page)
    choice = page.evaluate("""() => {
      const boxes=cy.nodes('.part,.module,.net,.rail').map(n=>n.boundingBox({includeLabels:true,includeOverlays:false}));
      for(const e of cy.edges('.wire')) {
        const ps=e.data('routePoints');
        for(let i=1;i<ps.length;i++) {
          const a=ps[i-1],b=ps[i];
          if(Math.abs(a.x-b.x)+Math.abs(a.y-b.y)<200)continue;
          const x=(a.x+b.x)/2,y=(a.y+b.y)/2;
          if(boxes.some(r=>x+80>r.x1&&x-80<r.x2&&y+80>r.y1&&y-80<r.y2))continue;
          cy.add({data:{id:'test-obstacle',group:'',label:'Obstacle',width:40,height:40,image:ReviewGraphModel.image('generic')},classes:'part',position:{x:x+5000,y}});
          return {edge:e.id(),before:ps,x,y};
        }
      }
      throw new Error('No clear test corridor');
    }""")
    page.evaluate(
        '(p)=>{cy.getElementById("test-obstacle").position({x:p.x,y:p.y});}', choice
    )
    page.wait_for_timeout(150)
    wait_layout(page)
    assert (
        page.evaluate('(id)=>cy.getElementById(id).data("routePoints")', choice["edge"])
        != choice["before"]
    )
    assert_geometry(diagram(page))


def test_overlap_is_visible_and_does_not_silently_move_parts(graph_page):
    page, _ = graph_page
    wait_layout(page)
    positions = page.evaluate("""() => {
      const a=cy.getElementById('part:ic'),b=cy.getElementById('part:capacitor');
      b.position({...a.position()});
      return {a:{...a.position()},b:{...b.position()}};
    }""")
    page.wait_for_timeout(150)
    expect(page.locator("#graph-loading")).to_be_hidden(timeout=30000)
    expect(page.locator("#layout-warning")).to_contain_text("重叠")
    assert (
        page.evaluate('({...cy.getElementById("part:capacitor").position()})')
        == positions["b"]
    )
    assert (
        page.evaluate('({...cy.getElementById("part:ic").position()})')
        == positions["a"]
    )
    page.locator("#layout").click()
    wait_layout(page)
