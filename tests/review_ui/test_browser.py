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
    kind = key.split(":", 1)[0]
    if kind in ("part", "net"):
        page.locator(f"#{kind}-picker").select_option(key)
    else:
        page.locator(f'#left-table tr[data-key="{key}"]').click()
    expect(page.locator("#review-status")).to_be_enabled()


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


def test_save_failure_retry_and_conflicting_tabs(page, app, tmp_path):
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
    with page.expect_download() as info:
        page.locator("#export").click()
    draft = tmp_path / "draft.json"
    info.value.save_as(draft)
    assert info.value.suggested_filename == "review-unsaved-draft.json"
    assert json.loads(draft.read_text())["entries"][key]["note"] == "本地冲突草稿"
    assert app.store.read()["entries"][key]["note"] == "另一标签页"
    page.on("dialog", lambda dialog: dialog.accept())
    page.locator("#reload").click()
    expect(page.locator("#note")).to_have_value("另一标签页")


def test_bidirectional_probe_nc_filters_and_history(page, app):
    expect(page.locator("#inventory")).to_contain_text("6 元件")
    page.locator("#module-filter").select_option("sense")
    expect(
        page.locator('#part-picker option[value^="part:sense-stable"]')
    ).to_have_count(3)
    page.locator("#module-filter").select_option("all")
    choose(page, "net:OUT")
    expect(page.locator("#right-count")).to_have_text("当前 2 / 总数 2")
    keys = page.locator("#right-table tbody tr").evaluate_all(
        "rows=>rows.map(r=>r.dataset.key)"
    )
    page.locator("#right-table tbody tr").first.click()
    expect(page.locator("#left-table tr.active")).to_have_attribute("data-key", keys[0])
    page.locator("#note").fill("切换前的引脚批注")
    page.locator("#right-table tbody tr").last.click()
    expect(page.locator("#note")).to_have_value("")
    expect(page.locator("#left-table tr.active")).to_have_attribute("data-key", keys[1])
    page.locator("#back").click()
    expect(page.locator("#note")).to_have_value("切换前的引脚批注")
    expect(page.locator("#save-state")).to_contain_text("已保存")
    assert app.store.read()["entries"][keys[0]]["note"] == "切换前的引脚批注"
    page.locator("#assembly-filter").select_option("dnp")
    choose(page, "part:sense-stable/spare")
    page.locator("#left-table tbody tr").first.click()
    expect(page.locator("#net-title")).to_have_text("NC · 明确不连接")
    expect(page.locator("#review-net")).to_be_disabled()
    page.locator("#current-details").click()
    expect(page.locator("#detail")).to_contain_text("NC · 明确不连接")
    page.locator("#close-detail").click()
    choose(page, "net:OUT")
    expect(page.locator("#left-table tr.active")).to_have_count(0)
    page.locator("#right-search").fill("no-such-endpoint")
    expect(page.locator("#right-count")).to_have_text("当前 0 / 总数 2")
    page.locator("#right-search").fill("")
    page.locator("#net-details").click()
    expect(page.locator("#detail")).to_contain_text("Allegro 名称")


def test_independent_states_batch_boundaries_and_plain_text(page, app):
    key = "part:sense-stable/upper"
    choose(page, key)
    page.locator("#review-status").select_option("issue")
    page.locator("#note").fill("<img src=x onerror=alert(1)> 核对额定值")
    expect(page.locator("#save-state")).to_contain_text("已保存")
    page.locator("#left-select").click()
    expect(page.locator("#selection-count")).to_have_text("左侧已选 2 个引脚")
    page.locator("#batch-apply").click()
    expect(page.locator("#save-state")).to_contain_text("已保存")
    entries = app.store.read()["entries"]
    assert entries[key]["status"] == "issue"
    assert sum(e["status"] == "approved" for e in entries.values()) == 2
    page.locator("#left-table tbody tr").first.click()
    page.locator("#left-select").click()
    page.locator("#right-select").click()
    expect(page.locator("#selection-count")).to_contain_text("右侧已选")
    expect(page.locator("#left-table input:checked")).to_have_count(0)
    page.locator("#right-search").fill("absent")
    expect(page.locator("#batch-apply")).to_be_disabled()
    page.reload()
    expect(page.locator("#save-state")).to_contain_text("已载入")
    choose(page, key)
    expect(page.locator("#note")).to_have_value(
        "<img src=x onerror=alert(1)> 核对额定值"
    )
    expect(page.locator("#review-status")).to_have_value("issue")
    page.locator("#current-details").click()
    expect(page.locator("#detail img")).to_have_count(0)


def test_next_pending_sorting_and_diagnostics(page):
    choose(page, "part:sense-stable/upper")
    page.locator("#left-status").select_option("pending")
    page.locator("#left-table tbody tr").first.click()
    first = page.locator("#left-table tr.active").get_attribute("data-key")
    page.locator("#review-status").select_option("approved")
    page.locator("#next-pending").click()
    assert page.locator("#left-table tr.active").get_attribute("data-key") != first
    page.locator("#next-pending").click()
    expect(page.locator("#navigation-message")).to_contain_text("已无下一待审项")
    page.locator("#left-table th button").first.click()
    expect(page.locator('#left-table th[aria-sort="descending"]')).to_have_count(1)
    page.locator("#diagnostics").click()
    page.locator("#diagnostic-filter").select_option("all")
    page.locator("#checks-list button").first.click()
    expect(page.locator("#detail")).to_contain_text("检查证据")


@pytest.mark.parametrize("width,height", [(1280, 800), (1440, 900), (1920, 1080)])
def test_table_viewports_and_no_graph_assets(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    choose(page, "net:OUT")
    page.locator("#right-table tbody tr").first.click()
    for side in ("left", "right"):
        box = page.locator(f"#{side}-scroll").bounding_box()
        assert box["height"] > 100 and box["width"] > 450
    assert page.evaluate("document.documentElement.scrollWidth") == width
    assert page.evaluate("document.documentElement.scrollHeight") == height
    resources = page.evaluate("performance.getEntriesByType('resource').map(r=>r.name)")
    assert not any(
        any(x in url for x in ("graph", "elk", "cytoscape")) for url in resources
    )
    artifact = Path(__file__).resolve().parents[2] / "build/parser/review-ui"
    artifact.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(artifact / f"table-review-{width}.png"))


def test_ten_thousand_pins_paging_and_shared_net(browser, tmp_path):
    root = tmp_path / "large"
    root.mkdir()
    shutil.copy(
        Path(__file__).resolve().parents[1] / "fixtures/parameterized/common.circuit",
        root / "common.circuit",
    )
    lines = [
        'circuit 2; include "common.circuit";',
        'board large { id = "large-review"; library = "standard@1"; top = board; }',
        "module board {",
    ]
    for i in range(2500):
        lines.append(f'instance c{i}: divider {{ id = "cell-{i}"; }}')
        lines.append(f"net I{i} = c{i}.IN; net O{i} = c{i}.OUT;")
    lines.append("net GND = " + ", ".join(f"c{i}.GND" for i in range(2500)) + "; }")
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
            expect(page.locator("#inventory")).to_contain_text("10000 引脚")
            choose(page, "net:GND")
            expect(page.locator("#right-count")).to_have_text("当前 2500 / 总数 2500")
            expect(page.locator("#right-table tbody tr")).to_have_count(60)
            first = page.locator("#right-table tbody tr").first.get_attribute(
                "data-key"
            )
            page.locator("#right-next").click()
            assert (
                page.locator("#right-table tbody tr").first.get_attribute("data-key")
                != first
            )
            page.locator("#back").click()
            assert (
                page.locator("#right-table tbody tr").first.get_attribute("data-key")
                == first
            )
            page.locator("#right-search").fill("c2499")
            expect(page.locator("#right-count")).to_have_text("当前 1 / 总数 2500")
            page.locator("#right-table tbody tr").click()
            expect(page.locator("#left-table tr.active")).to_have_count(1)
            assert not errors
        finally:
            context.close()
            server.shutdown()
            thread.join(timeout=5)


def test_same_net_physical_pins_are_not_merged(browser, tmp_path):
    root = tmp_path / "same-net"
    root.mkdir()
    source = root / "board.circuit"
    source.write_text("""circuit 2;
board demo { id = "same-net"; library = "standard@1"; top = board; }
template resistor { device = "generic.resistor"; package = "resistor_0603"; assembly = fitted; properties { tolerance = 1 %; power_rating = 0.1 W; } }
module board {
    part fitted using resistor { id = "fitted"; properties { resistance = 1 kohm; } }
    part spare using resistor { id = "spare"; assembly = dnp; properties { resistance = 2 kohm; } }
    net COMMON = fitted.A, fitted.B, spare.A, spare.B;
}
""")
    output = tmp_path / "output"
    export_design(compile_design(load_design(source)), output)
    with ReviewServer(output, state_dir=tmp_path / "state") as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        context = browser.new_context()
        try:
            page = context.new_page()
            page.goto(server.url)
            expect(page.locator("#save-state")).to_contain_text("已载入")
            choose(page, "net:COMMON")
            rows = page.locator("#right-table tbody tr[data-key]")
            expect(rows).to_have_count(4)
            keys = rows.evaluate_all("xs=>xs.map(x=>x.dataset.key)")
            assert len(set(keys)) == 4
            assert page.locator("#right-table tbody").inner_text().count("DNP") == 2
            page.locator("#right-select").click()
            page.locator("#batch-apply").click()
            expect(page.locator("#save-state")).to_contain_text("已保存")
            entries = server.store.read()["entries"]
            assert set(entries) == set(keys)
        finally:
            context.close()
            server.shutdown()
            thread.join(timeout=5)
