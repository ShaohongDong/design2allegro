"""Browser acceptance for the generic review tool using synthetic circuits."""

import json
import shutil
import threading
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

from design2allegro import compile_design, export_design, load_design
from design2allegro.review import ReviewServer


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def app(tmp_path):
    project = tmp_path / "project"
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "fixtures/parameterized", project
    )
    common = project / "common.circuit"
    common.write_text(
        common.read_text().replace(
            "    group MID",
            """    part spare using resistor { id = "spare"; assembly = dnp; properties { resistance = 1 kohm; } }
    nc spare.A, spare.B;
    group MID""",
        )
    )
    output = tmp_path / "output"
    export_design(compile_design(load_design(project / "board.circuit")), output)
    with ReviewServer(output, state_dir=tmp_path / "state") as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        yield server
        server.shutdown()
        thread.join(timeout=5)


@pytest.fixture
def page(browser, app):
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(app.url)
    expect(page.locator("#save-state")).to_contain_text("已载入")
    yield page
    assert not errors
    context.close()


def choose(page, key):
    page.locator(f'[data-key="{key}"]').click()
    expect(page.locator("#review-status")).to_be_visible()


def test_graph_details_search_filters_and_cross_probe(page, app):
    expect(page.locator("#inventory")).to_contain_text("6 元件")
    assert page.evaluate('cy.nodes(".part").length') == 6
    page.locator("#search").fill("spare")
    expect(page.locator("#list-count")).to_have_text("2 个结果")
    expect(page.locator("#graph-count")).to_contain_text("隐藏")
    page.locator("#restore").click()
    page.locator("#assembly-filter").select_option("dnp")
    expect(page.locator("#list-count")).to_have_text("2 个结果")
    choose(page, "part:sense-stable/spare")
    expect(page.locator("#detail")).to_contain_text("NC · 明确不连接")
    page.locator('[data-tab="nets"]').click()
    choose(page, "net:OUT")
    expect(page.locator("#detail")).to_contain_text("Allegro 名称")
    expect(page.locator(".endpoint")).to_have_count(2)
    page.locator(".endpoint .link").first.click()
    expect(page.locator("#detail")).to_contain_text("物理焊盘")
    page.locator("#collapse").click()
    assert page.evaluate('cy.nodes(".module").length') == 2
    assert page.evaluate('cy.nodes(".part").length') == 0
    assert page.evaluate('cy.nodes(".port").length') == 6
    assert page.evaluate('cy.nodes(".rail").length') == 2
    assert page.evaluate(
        'cy.nodes(".ground").every(n=>n.data("rotation")===90 || n.data("rotation")===270)'
    )
    assert sorted(
        page.evaluate('cy.edges().not(".lead").flatMap(e=>e.data("pins"))')
    ) == sorted(k for k, pin in app.package["pins"].items() if not pin["nc"])
    page.locator("#restore").click()
    assert page.evaluate('cy.nodes(".part").length') == 6
    page.locator('[data-tab="diagnostics"]').click()
    page.locator("#diagnostic-filter").select_option("all")
    page.locator(".object-row").first.click()
    expect(page.locator("#detail")).to_contain_text("检查证据")


def test_autosave_batch_restart_and_plain_text(page, app):
    key = "part:sense-stable/upper"
    choose(page, key)
    page.locator("#review-status").select_option("issue")
    page.locator("#note").fill("<img src=x onerror=alert(1)> 核对额定值")
    expect(page.locator("#save-state")).to_contain_text("已保存")
    assert app.store.read()["entries"][key]["status"] == "issue"
    page.reload()
    expect(page.locator("#save-state")).to_contain_text("已载入")
    choose(page, key)
    expect(page.locator("#note")).to_have_value(
        "<img src=x onerror=alert(1)> 核对额定值"
    )
    page.locator("#select-page").click()
    page.locator("#batch-status").select_option("approved")
    page.locator("#batch-apply").click()
    expect(page.locator("#save-state")).to_contain_text("已保存")
    assert (
        sum(e["status"] == "approved" for e in app.store.read()["entries"].values())
        == 6
    )
    page.locator("#status-filter").select_option("approved")
    expect(page.locator("#list-count")).to_have_text("6 个结果")


def test_import_export_preview_and_cancel(page, app, tmp_path):
    choose(page, "part:sense-stable/upper")
    page.locator("#note").fill("已核查")
    expect(page.locator("#save-state")).to_contain_text("已保存")
    with page.expect_download() as info:
        page.locator("#export").click()
    dest = tmp_path / "export.json"
    info.value.save_as(dest)
    data = json.loads(dest.read_text())
    assert data == app.store.read()
    data["entries"] = {}
    dest.write_text(json.dumps(data))
    page.locator("#import-file").set_input_files(dest)
    expect(page.locator("#import-dialog")).to_be_visible()
    expect(page.locator("#import-summary")).to_contain_text("清除 1 条")
    page.locator("#cancel-import").click()
    assert app.store.read()["entries"]
    page.locator("#import-file").set_input_files(dest)
    expect(page.locator("#import-dialog")).to_be_visible()
    page.locator("#confirm-import").click()
    expect(page.locator("#save-state")).to_contain_text("导入已保存")
    assert not app.store.read()["entries"]
    data["fingerprint"] = "different"
    dest.write_text(json.dumps(data))
    page.locator("#import-file").set_input_files(dest)
    expect(page.locator("#error")).to_contain_text("different board or delivery")


def test_save_failure_retry_and_conflicting_tabs(page, app):
    key = "part:sense-stable/upper"
    choose(page, key)

    def fail(route):
        if route.request.method == "PATCH":
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"error":"disk full"}',
            )
        else:
            route.continue_()

    page.route("**/api/review", fail)
    page.locator("#note").fill("不能丢失的批注")
    expect(page.locator("#save-state")).to_contain_text("未保存")
    expect(page.locator("#note")).to_have_value("不能丢失的批注")
    assert not app.store.read()["entries"]
    page.unroute("**/api/review", fail)
    page.locator("#retry").click()
    expect(page.locator("#save-state")).to_contain_text("已保存")
    assert app.store.read()["entries"][key]["note"] == "不能丢失的批注"
    app.store.update(app.store.read()["revision"], {key: {"note": "另一标签页"}})
    page.locator("#note").fill("本地冲突草稿")
    expect(page.locator("#error")).to_contain_text("其他页面已更新")
    expect(page.locator("#note")).to_have_value("本地冲突草稿")
    assert app.store.read()["entries"][key]["note"] == "另一标签页"
    page.on("dialog", lambda dialog: dialog.accept())
    page.locator("#reload").click()
    expect(page.locator("#note")).to_have_value("另一标签页")


@pytest.mark.parametrize("width,height", [(1280, 800), (1440, 900), (1920, 1080)])
def test_viewports_drag_zoom_and_screenshot(page, app, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.locator("#fit").click()
    box = page.locator("#graph").bounding_box()
    assert box["width"] > 400 and box["height"] > 400
    assert page.evaluate("document.documentElement.scrollWidth") == width
    page.wait_for_function(
        'cy.nodes().length > 0 && document.getElementById("graph-loading").hidden'
    )
    page.keyboard.down("Shift")
    page.mouse.move(box["x"] + 3, box["y"] + 3)
    page.mouse.down()
    page.mouse.move(box["x"] + box["width"] - 3, box["y"] + box["height"] - 3, steps=10)
    page.mouse.up()
    page.keyboard.up("Shift")
    assert page.evaluate('cy.nodes(":selected").length') > 0
    expect(page.locator("#batch-apply")).to_be_enabled()
    page.locator("#clear-selection").click()
    pos = page.evaluate(
        'cy.getElementById("part:sense-stable/upper").renderedPosition()'
    )
    before = page.evaluate('cy.getElementById("part:sense-stable/upper").position()')
    page.mouse.move(box["x"] + pos["x"], box["y"] + pos["y"])
    page.mouse.down()
    page.mouse.move(box["x"] + pos["x"] + 50, box["y"] + pos["y"] + 35, steps=12)
    page.mouse.up()
    after = page.evaluate('cy.getElementById("part:sense-stable/upper").position()')
    assert abs(after["x"] - before["x"]) > 10
    zoom = page.evaluate("cy.zoom()")
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    page.mouse.wheel(0, -250)
    page.wait_for_function("(old)=>cy.zoom()>old", arg=zoom)
    choose(page, "part:sense-stable/upper")
    page.locator("#note").fill("核对规格与引脚映射；人工审查记录示例。")
    expect(page.locator("#save-state")).to_contain_text("已保存")
    artifact = Path(__file__).resolve().parents[2] / "build/parser/review-ui"
    artifact.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(artifact / f"review-{width}.png"))


def test_large_synthetic_graph_remains_searchable(browser, tmp_path):
    root = tmp_path / "large"
    root.mkdir()
    common = (
        Path(__file__).resolve().parents[1] / "fixtures/parameterized/common.circuit"
    )
    shutil.copy(common, root / "common.circuit")
    count = 600
    lines = [
        'circuit 2; include "common.circuit";',
        'board large { id = "large-review"; library = "standard@1"; top = board; }',
        "module board {",
    ]
    for i in range(count):
        lines.extend(
            [
                f'instance c{i}: divider {{ id = "cell-{i}"; }}',
                f"net I{i} = c{i}.IN; net O{i} = c{i}.OUT; net G{i} = c{i}.GND;",
            ]
        )
    lines.append("}")
    (root / "board.circuit").write_text("\n".join(lines))
    output = tmp_path / "output"
    export_design(compile_design(load_design(root / "board.circuit")), output)
    with ReviewServer(output, state_dir=tmp_path / "state") as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        try:
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(server.url)
            expect(page.locator("#save-state")).to_contain_text("已载入", timeout=20000)
            page.wait_for_function('document.getElementById("graph-loading").hidden')
            assert page.evaluate('cy.nodes(".part").length') == 1200
            assert page.evaluate('cy.nodes(".pin").length') == 2400
            assert page.evaluate('cy.edges(".wire").length') == 1200
            assert page.evaluate('cy.nodes(".rail").length') == 600
            expect(page.locator(".object-row")).to_have_count(60)
            page.locator("#search").fill("c599/hi")
            expect(page.locator("#list-count")).to_have_text("1 个结果")
            assert page.evaluate('cy.nodes(".part").length') == 1
            page.locator(".object-row").click()
            expect(page.locator("#detail")).to_contain_text("c599/hi")
            assert not errors
        finally:
            context.close()
            server.shutdown()
            thread.join(timeout=5)


def test_wheel_zoom_step_anchor_and_limits(page):
    expect(page.locator("#graph-loading")).to_be_hidden()
    page.evaluate("""() => {
      window.wheelEvents=0;
      cy.on('scrollzoom',()=>{window.wheelEvents++;});
      cy.zoom(1);
      cy.pan({x:0,y:0});
    }""")
    box = page.locator("#graph").bounding_box()
    point = {"x": box["width"] * 0.35, "y": box["height"] * 0.4}
    page.mouse.move(box["x"] + point["x"], box["y"] + point["y"])

    def wheel(delta):
        count = page.evaluate("window.wheelEvents")
        page.mouse.wheel(0, delta)
        page.wait_for_function("count => window.wheelEvents > count", arg=count)
        return page.evaluate("cy.zoom()")

    def model_point():
        return page.evaluate(
            "p => ({x:(p.x-cy.pan().x)/cy.zoom(),y:(p.y-cy.pan().y)/cy.zoom()})",
            point,
        )

    anchor = model_point()
    # A first wheel step should be visibly larger than the former ~1% change.
    assert 1.04 < wheel(-100) < 1.06
    assert model_point() == pytest.approx(anchor, abs=0.1)
    assert wheel(100) == pytest.approx(1, abs=0.001)
    assert model_point() == pytest.approx(anchor, abs=0.1)
    page.evaluate("() => { cy.zoom(2.999); }")
    assert wheel(-100) == pytest.approx(3)
    page.evaluate("() => { cy.zoom(0.005001); }")
    assert wheel(100) == pytest.approx(0.005)
