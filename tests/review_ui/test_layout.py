"""Symbol envelopes, visible anchors, orthogonal paths and worker acceptance."""

import pytest
from playwright.sync_api import expect
from test_browser import app, browser, page  # noqa: F401
from test_pin_graph import graph_page  # noqa: F401


def wait_layout(page):
    expect(page.locator("#graph-loading")).to_be_hidden(timeout=30000)
    assert page.locator("#layout-warning").inner_text() == ""
    assert page.evaluate("graphMetrics.layout") == "elk-pin-layered"


def test_symbol_bounds_routes_and_repeatability(graph_page):
    page, _ = graph_page
    wait_layout(page)
    result = page.evaluate("""()=>({
      boxes:cy.nodes().not('.junction, .terminal').map(n=>{const b=n.data('box');return {id:n.id(),x:n.position('x')+(b?(b.x1+b.x2)/2:0),y:n.position('y')+(b?(b.y1+b.y2)/2:0),w:b?b.x2-b.x1:n.width(),h:b?b.y2-b.y1:n.height()}}),
      routes:cy.edges().map(e=>({points:e.data('routePoints'),rendered:[e.sourceEndpoint(),...(e.segmentPoints()||[]),e.targetEndpoint()],a:{p:e.source().position(),w:e.source().width(),h:e.source().height(),anchorY:e.source().data('anchorY')},b:{p:e.target().position(),w:e.target().width(),h:e.target().height(),anchorY:e.target().data('anchorY')}}))
    })""")
    boxes = result["boxes"]
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            assert (
                abs(a["x"] - b["x"]) >= (a["w"] + b["w"]) / 2
                or abs(a["y"] - b["y"]) >= (a["h"] + b["h"]) / 2
            )
    for route in result["routes"]:
        points = route["points"]
        for a, b in zip(points, points[1:]):
            assert abs(a["x"] - b["x"]) < 0.1 or abs(a["y"] - b["y"]) < 0.1
        for a, b in zip(route["rendered"], route["rendered"][1:]):
            assert abs(a["x"] - b["x"]) < 0.1 or abs(a["y"] - b["y"]) < 0.1
        for end, point in [(route["a"], points[0]), (route["b"], points[-1])]:
            dx, dy = abs(point["x"] - end["p"]["x"]), abs(point["y"] - end["p"]["y"])
            assert dx <= end["w"] / 2 + 0.1 and dy <= end["h"] / 2 + 0.1
            if "anchorY" in end:
                assert point["x"] == pytest.approx(end["p"]["x"], abs=0.1)
                assert point["y"] == pytest.approx(
                    end["p"]["y"] + end["anchorY"], abs=0.1
                )
            else:
                assert abs(dx - end["w"] / 2) < 0.1 or abs(dy - end["h"] / 2) < 0.1
    before = page.evaluate("cy.nodes().map(n=>({id:n.id(),p:n.position()}))")
    page.locator("#layout").click()
    wait_layout(page)
    assert page.evaluate("cy.nodes().map(n=>({id:n.id(),p:n.position()}))") == before


def test_worker_failure_cancel_and_latest_result(page):
    wait_layout(page)
    before = page.evaluate("cy.nodes().map(n=>({id:n.id(),p:n.position()}))")
    page.route("**/graph-worker.js", lambda route: route.abort())
    page.locator("#layout").click()
    expect(page.locator("#layout-warning")).to_contain_text("失败")
    assert page.evaluate("cy.nodes().map(n=>({id:n.id(),p:n.position()}))") == before
    page.unroute("**/graph-worker.js")
    page.evaluate('()=>{runLayout();document.getElementById("cancel-layout").click()}')
    expect(page.locator("#layout-warning")).to_contain_text("取消")
    assert page.evaluate("cy.nodes().map(n=>({id:n.id(),p:n.position()}))") == before
    page.evaluate(
        '()=>{runLayout();document.getElementById("collapse").click();document.getElementById("restore").click()}'
    )
    wait_layout(page)
    assert page.evaluate('cy.nodes(".pin").length') == 12


def test_fold_unfold_and_cross_module_inventory(page, app):
    wait_layout(page)
    pins = sorted(app.package["pins"])
    page.locator("#collapse").click()
    wait_layout(page)
    assert (
        sorted(page.evaluate('cy.nodes(".module").flatMap(n=>n.data("pins"))')) == pins
    )
    target = pins[0]
    page.evaluate('(id)=>selectObject("pin:"+id)', target)
    wait_layout(page)
    assert page.evaluate('(id)=>cy.getElementById("pin:"+id).length', target) == 1
    page.locator("#restore").click()
    wait_layout(page)
    assert sorted(page.evaluate('cy.nodes(".pin").map(n=>n.data("pinId"))')) == pins


def test_cross_module_network_remains_one_electrical_net(browser, tmp_path):
    import shutil
    from pathlib import Path

    from test_pin_graph import serve

    from design2allegro import compile_design, export_design, load_design

    project = tmp_path / "project"
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "fixtures/parameterized", project
    )
    source = project / "board.circuit"
    source.write_text(
        source.read_text()
        .replace("net IN = sense.IN;", "net IN = sense.IN, other.IN;")
        .replace("net IN2 = other.IN;", "")
    )
    output = tmp_path / "output"
    export_design(compile_design(load_design(source)), output)
    with serve(output, tmp_path / "state") as server:
        context = browser.new_context()
        p = context.new_page()
        p.goto(server.url)
        expect(p.locator("#save-state")).to_contain_text("已载入")
        wait_layout(p)
        assert p.evaluate("""()=>{
          const edges=cy.edges('.wire').filter(e=>e.data('netKey')==='net:IN');
          return edges.length===1 && edges[0].source().data('group')!==edges[0].target().data('group');
        }""")
        p.evaluate('selectObject("net:IN")')
        expect(p.locator("#detail")).to_contain_text("跨模块连接")
        context.close()


def test_junction_render_drag_state_and_click(graph_page):
    p, _ = graph_page
    p.evaluate("""()=>{
      graphPositioning=true;
      cy.elements().remove();
      cy.add([
        ...[['a',-100,0],['b',100,0],['c',0,0],['d',0,100]].map(([id,x,y])=>({
          data:{id,width:1,height:1,label:'',anchorY:0},position:{x,y},selectable:false})),
        {data:{id:'test-h',source:'a',target:'b',netKey:'net:BUS',label:''},classes:'wire'},
        {data:{id:'test-v',source:'c',target:'d',netKey:'net:BUS',label:''},classes:'wire'},
      ]);
      applyWirePath(cy.getElementById('test-h'),[{x:-100,y:0},{x:100,y:0}]);
      applyWirePath(cy.getElementById('test-v'),[{x:0,y:0},{x:0,y:100}]);
      graphPositioning=false;refreshJunctions();cy.fit(undefined,80);
    }""")
    assert p.evaluate(
        'cy.nodes(".junction").map(n=>({...n.position(),selectable:n.selectable(),grabbable:n.grabbable(),width:n.width()}))'
    ) == [{"x": 0, "y": 0, "selectable": False, "grabbable": False, "width": 7}]
    p.evaluate("""()=>{
      cy.edges('.wire').addClass('chain');refreshJunctions();
    }""")
    assert p.evaluate('cy.nodes(".junction")[0].hasClass("chain")')
    p.evaluate(
        '()=>{cy.edges(".wire").removeClass("chain").addClass("faded");refreshJunctions()}'
    )
    assert p.evaluate('cy.nodes(".junction")[0].style("opacity")') == "0.17"
    p.evaluate('()=>{cy.edges(".wire").removeClass("faded");refreshJunctions()}')
    point = p.evaluate('cy.nodes(".junction")[0].renderedPosition()')
    box = p.locator("#graph").bounding_box()
    p.mouse.click(box["x"] + point["x"], box["y"] + point["y"])
    expect(p.locator("#detail h1")).to_have_text("BUS")
    assert p.evaluate('cy.nodes(".junction")[0].hasClass("highlight")')
    assert p.evaluate("selected.size") == 0
    p.evaluate('()=>cy.getElementById("c").position({x:20,y:0})')
    p.wait_for_function("()=>junctionFrame===null")
    assert p.evaluate('cy.nodes(".junction").map(n=>({...n.position()}))') == [
        {"x": 10, "y": 0}
    ]
    p.evaluate('()=>cy.getElementById("c").position({x:20,y:40})')
    p.wait_for_function("()=>junctionFrame===null")
    assert p.evaluate('cy.nodes(".junction").length') == 0
    # A trace-crossing edge is excluded even if it carries misleading net metadata.
    p.evaluate("""()=>{
      cy.getElementById('test-v').removeClass('wire').addClass('transition');
      applyWirePath(cy.getElementById('test-v'),[{x:0,y:-100},{x:0,y:100}]);
      refreshJunctions();
    }""")
    assert p.evaluate('cy.nodes(".junction").length') == 0
    p.locator("#layout").click()
    wait_layout(p)
    assert p.evaluate('cy.nodes(".junction").length') > 0
    p.locator("#search").fill(p.evaluate('pkg.parts.ic.reference + ".1"'))
    expect(p.locator("#list-count")).to_have_text("1 个结果")
    wait_layout(p)
    # Remaining repeated pins already have an explicit net anchor; no stale BUS dots.
    assert p.evaluate('cy.nodes(".junction").length') == 0
