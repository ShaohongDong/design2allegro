"""Review behavior on synthetic delivered circuits; never real board designs."""

import json
import shutil
import threading
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from design2allegro import ElectricalError, compile_design, export_design, load_design
from design2allegro.review import (
    ReviewConflict,
    ReviewServer,
    ReviewStore,
    load_package,
)
from design2allegro.verify import NetlistFormatError, verify_package


@pytest.fixture
def delivered(tmp_path):
    project = tmp_path / "project"
    shutil.copytree(
        Path(__file__).resolve().parents[1] / "fixtures/parameterized", project
    )
    output = tmp_path / "output"
    export_design(compile_design(load_design(project / "board.circuit")), output)
    return output


def snapshot(folder):
    return {
        str(p.relative_to(folder)): p.read_bytes()
        for p in folder.rglob("*")
        if p.is_file()
    }


def test_package_indexes_and_read_only(delivered, tmp_path):
    before = snapshot(delivered)
    data = load_package(delivered)
    assert data["statistics"] == {"parts": 4, "pins": 8, "nets": 6}
    assert len(data["objects"]) == 18
    assert data["parts"]["sense-stable/upper"]["path"] == "sense/hi"
    assert data["pins"]["sense-stable/upper.A"]["reference"].startswith("R")
    assert data["nets"]["OUT"]["allegro_name"] == "OUT"
    assert any(
        "net:OUT" in d["targets"] or "pin:sense-stable/upper.B" in d["targets"]
        for d in data["diagnostics"]
    )
    store = ReviewStore(data, delivered, tmp_path / "state")
    key = next(iter(data["objects"]))
    saved = store.update(
        0, {key: {"status": "issue", "note": "<script>plain text</script> 中文"}}
    )
    assert saved["revision"] == 1
    assert ReviewStore(data, delivered, tmp_path / "state").read() == saved
    assert snapshot(delivered) == before
    assert verify_package(delivered)["parts"] == 4


def test_encoded_nets_nc_dnp_and_repeated_net_pins(make_board, tmp_path):
    make_board(
        {
            "chip": {"1": "PASSIVE", "2": "PASSIVE", "3": "PASSIVE"},
            "spare": {"A": "PASSIVE"},
        },
        {"V_DD": [("chip", "1"), ("chip", "2"), ("spare", "A")]},
        nc=[("chip", "3")],
    )
    # Assembly remains a design attribute; editing the synthetic input needs no physical board.
    from conftest import write_circuit

    design = load_design(
        tmp_path / "board.circuit", library_root=tmp_path / "catalogs"
    ).document
    design["modules"]["board"]["parts"]["spare"]["assembly"] = "dnp"
    write_circuit(tmp_path / "board.circuit", design)
    output = tmp_path / "out"
    export_design(
        compile_design(
            load_design(tmp_path / "board.circuit", library_root=tmp_path / "catalogs")
        ),
        output,
    )
    data = load_package(output)
    assert data["nets"]["V_DD"]["allegro_name"] == "V_5FDD"
    assert data["pins"]["chip.3"]["nc"]
    assert data["pins"]["chip.3"]["type_name"] == "PASSIVE"
    assert data["parts"]["spare"]["assembly"] == "dnp"
    assert len(data["nets"]["V_DD"]["pins"]) == 3


def test_reject_invalid_and_legacy_deliveries(delivered):
    path = delivered / "circuit.json"
    path.write_text(path.read_text() + " ")
    with pytest.raises(NetlistFormatError, match="digest mismatch"):
        load_package(delivered)
    path = delivered / "manifest.json"
    data = json.loads(path.read_text())
    data["version"] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(ElectricalError, match="version 2"):
        load_package(delivered)


def test_snapshot_frozen_and_fingerprints_isolate_versions(delivered, tmp_path):
    data = load_package(delivered)
    copy = tmp_path / "copied"
    shutil.copytree(delivered, copy)
    assert load_package(copy)["fingerprint"] == data["fingerprint"]
    state = tmp_path / "state"
    old = ReviewStore(data, delivered, state)
    key = next(iter(data["objects"]))
    old.update(0, {key: {"status": "approved"}})
    changed = dict(data, fingerprint="a" * 64)
    new = ReviewStore(changed, delivered, state)
    assert not new.read()["entries"]
    with pytest.raises(ElectricalError, match="different board or delivery"):
        new.replace(0, old.read())
    (delivered / "circuit.json").write_text("{}")
    assert data["statistics"]["parts"] == 4


def test_revision_conflicts_and_atomic_failure(delivered, tmp_path, monkeypatch):
    import design2allegro.review as review

    data = load_package(delivered)
    a = ReviewStore(data, delivered, tmp_path / "state")
    b = ReviewStore(data, delivered, tmp_path / "state")
    key = next(iter(data["objects"]))
    saved = a.update(0, {key: {"status": "approved"}})
    with pytest.raises(ReviewConflict):
        b.update(0, {key: {"status": "issue"}})

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(review.os, "replace", fail)
    with pytest.raises(OSError, match="disk full"):
        b.update(1, {key: {"note": "unsaved"}})
    assert a.read() == saved
    assert not list(a.directory.glob(".review-*"))


@pytest.mark.parametrize(
    "change",
    [
        {"status": "bad"},
        {"note": 1},
        {"note": "x" * 20001},
        {"updated_at": "2026-01-01"},
        {},
    ],
)
def test_invalid_changes_do_not_save(delivered, tmp_path, change):
    store = ReviewStore(load_package(delivered), delivered, tmp_path / "state")
    with pytest.raises(ElectricalError):
        store.update(0, {"part:sense-stable/upper": change})
    assert store.read()["revision"] == 0


def test_import_preview_replacement_and_validation(delivered, tmp_path):
    store = ReviewStore(load_package(delivered), delivered, tmp_path / "state")
    empty = store.read()
    keys = list(store.objects)[:2]
    first = store.update(0, {key: {"status": "issue", "note": "check"} for key in keys})
    preview = store.preview(1, empty)
    assert preview["removed"] == sorted(keys) and len(preview["changed"]) == 2
    assert store.read() == first  # Preview never writes.
    assert store.replace(1, empty)["entries"] == {}
    with pytest.raises(ReviewConflict):
        store.replace(1, first)
    wrong = dict(first, entries={"part:missing": next(iter(first["entries"].values()))})
    with pytest.raises(ElectricalError, match="invalid review object"):
        store.preview(2, wrong)
    assert store.read()["revision"] == 2


def test_state_outside_delivery_and_xdg_default(delivered, tmp_path, monkeypatch):
    data = load_package(delivered)
    with pytest.raises(ElectricalError, match="outside"):
        ReviewStore(data, delivered, delivered / "notes")
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "user-state"))
    store = ReviewStore(data, delivered)
    assert tmp_path / "user-state" in store.path.parents
    store.path.write_text("bad json")
    with pytest.raises(ElectricalError, match="invalid review state"):
        ReviewStore(data, delivered)


def test_http_api_static_assets_and_conflicts(delivered, tmp_path):
    with ReviewServer(delivered, state_dir=tmp_path / "state") as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def call(path, method="GET", body=None, token=True, origin=None):
            headers = {"Content-Type": "application/json"}
            if token:
                headers["X-Review-Token"] = server.token
            if origin:
                headers["Origin"] = origin
            request = Request(
                server.url + path,
                method=method,
                data=json.dumps(body).encode() if body is not None else None,
                headers=headers,
            )
            return urlopen(request, timeout=5)

        try:
            with call("/api/package") as response:
                data = json.load(response)
            assert data["token"] == server.token
            for path in (
                "/",
                "/style.css",
                "/app.js",
                "/graph-model.js",
                "/graph-geometry.js",
                "/graph-routing.js",
                "/graph-symbols.js",
                "/graph.js",
                "/graph-worker.js",
                "/vendor/elk-api.js",
                "/vendor/elk-worker.min.js",
                "/vendor/LICENSE.elk",
                "/vendor/README.elk",
                "/vendor/cytoscape.min.js",
                "/vendor/LICENSE.cytoscape",
            ):
                with call(path) as response:
                    assert response.status == 200 and response.read()
                    if path.endswith(".wasm"):
                        assert response.headers.get_content_type() == "application/wasm"
                    if path == "/":
                        csp = response.headers["Content-Security-Policy"]
                        assert "'wasm-unsafe-eval'" in csp
                        assert "'unsafe-eval'" not in csp
            key = next(iter(data["objects"]))
            body = {"revision": 0, "changes": {key: {"status": "approved"}}}
            for options in ({"token": False}, {"origin": "https://other.invalid"}):
                with pytest.raises(HTTPError) as exc:
                    call("/api/review", "PATCH", body, **options)
                assert exc.value.code == 403
            with call("/api/review", "PATCH", body) as response:
                assert json.load(response)["revision"] == 1
            with pytest.raises(HTTPError) as exc:
                call("/api/review", "PATCH", body)
            assert exc.value.code == 409
            with call("/api/review/export") as response:
                assert "attachment" in response.headers["Content-Disposition"]
                saved = json.load(response)
            with call(
                "/api/review/import/preview", "POST", {"revision": 1, "record": saved}
            ) as response:
                assert json.load(response)["changed"] == []
            with call(
                "/api/review/import", "POST", {"revision": 1, "record": saved}
            ) as response:
                assert json.load(response)["revision"] == 2
            for path in ("/manifest.json", "/../pyproject.toml", "/api/absent"):
                with pytest.raises(HTTPError) as exc:
                    call(path)
                assert exc.value.code == 404
            with call("/api/package") as response:
                assert json.load(response) == data
        finally:
            server.shutdown()
            thread.join(timeout=5)
