"""Read-only delivery inspection and independently persisted human review."""

import copy
import fcntl
import hashlib
import json
import os
import secrets
import tempfile
import threading
import webbrowser
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import urlsplit

from .model import ElectricalError, canonical, digest
from .verify import verify_package

STATUSES = {"pending", "approved", "issue"}
MAX_BODY = 8 * 1024 * 1024
STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/style.css": ("style.css", "text/css; charset=utf-8"),
    "/vendor/cytoscape.min.js": (
        "vendor/cytoscape.min.js",
        "text/javascript; charset=utf-8",
    ),
    "/vendor/LICENSE.cytoscape": (
        "vendor/LICENSE.cytoscape",
        "text/plain; charset=utf-8",
    ),
}


class ReviewConflict(ElectricalError):
    """Another browser or process has saved a newer revision."""


def load_package(directory):
    """Verify delivery, then freeze exactly the bytes described by its manifest."""
    root = Path(directory).absolute()
    manifest_bytes = (root / "manifest.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    if manifest.get("version") != 2:
        raise ElectricalError("review requires a version 2 delivery package")
    statistics = verify_package(root)
    frozen = {}
    for name in ("circuit.json", "drc.json"):
        raw = (root / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != manifest["files"][name]:
            raise ElectricalError("delivery changed while loading; restart review")
        frozen[name] = json.loads(raw)
    if (root / "manifest.json").read_bytes() != manifest_bytes:
        raise ElectricalError("delivery changed while loading; restart review")
    circuit = frozen["circuit.json"]
    objects = {}
    parts, pins, nets = {}, {}, {}
    for identity, part in circuit["parts"].items():
        key = "part:" + identity
        parts[identity] = dict(part, key=key, path="/".join(part["hierarchy"]))
        objects[key] = part["reference"]
    type_names = {value: name for name, value in circuit["pin_types"].items()}
    for identity, pin in circuit["pins"].items():
        key = "pin:" + identity
        pins[identity] = dict(
            pin,
            key=key,
            reference=parts[pin["ref"]]["reference"],
            type_name=type_names.get(pin["func"], str(pin["func"])),
        )
        objects[key] = pins[identity]["reference"] + "." + pin["num"]
    aliases = {}
    for alias, name in circuit["net_aliases"].items():
        aliases.setdefault(name, []).append(alias)
    for name, net in circuit["nets"].items():
        key = "net:" + name
        nets[name] = dict(
            net,
            key=key,
            allegro_name=manifest["net_names"][name],
            aliases=sorted(aliases.get(name, [])),
        )
        objects[key] = name
    diagnostics = []
    for index, item in enumerate(frozen["drc.json"]["diagnostics"]):
        targets = set()

        def locate(value):
            if isinstance(value, str):
                for kind, collection in (("part", parts), ("pin", pins), ("net", nets)):
                    if value in collection:
                        targets.add(kind + ":" + value)
            elif isinstance(value, list):
                for entry in value:
                    locate(entry)
            elif isinstance(value, dict):
                for key, entry in value.items():
                    locate(key)
                    locate(entry)

        locate(item.get("object"))
        for field in ("members", "pins", "conflicts"):
            locate(item.get("evidence", {}).get(field))
        diagnostics.append(dict(item, index=index, targets=sorted(targets)))
    return {
        "version": 1,
        "board_id": circuit["board_id"],
        "name": circuit["name"],
        "fingerprint": digest(manifest),
        "snapshot": manifest["snapshot"],
        "statistics": statistics,
        "parts": parts,
        "pins": pins,
        "nets": nets,
        "diagnostics": diagnostics,
        "accessories": circuit.get("accessories", []),
        "objects": objects,
    }


class ReviewStore:
    """Version-bound state. File locks cover independent server processes too."""

    def __init__(self, package, package_dir, state_dir=None):
        default = (
            Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
            / "design2allegro/reviews"
        )
        base = (
            Path(state_dir).expanduser().resolve()
            if state_dir
            else default.expanduser().resolve()
        )
        root = Path(package_dir).resolve()
        if base == root or root in base.parents:
            raise ElectricalError(
                "review state directory must be outside the delivery package"
            )
        self.directory = (
            base / digest(package["board_id"])[:16] / package["fingerprint"]
        )
        if root == self.directory.resolve() or root in self.directory.resolve().parents:
            raise ElectricalError(
                "review state directory must be outside the delivery package"
            )
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "review.json"
        self.board_id = package["board_id"]
        self.fingerprint = package["fingerprint"]
        self.objects = package["objects"]
        self.mutex = threading.Lock()
        self.read()  # Refuse malformed state instead of silently resetting it.

    @contextmanager
    def locked(self):
        with self.mutex, (self.directory / "review.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def empty(self):
        return {
            "version": 1,
            "board_id": self.board_id,
            "fingerprint": self.fingerprint,
            "revision": 0,
            "entries": {},
        }

    def validate(self, data):
        if not isinstance(data, dict) or set(data) != {
            "version",
            "board_id",
            "fingerprint",
            "revision",
            "entries",
        }:
            raise ElectricalError("invalid review record fields")
        if type(data["version"]) is not int or data["version"] != 1:
            raise ElectricalError("unsupported review record version")
        if data["board_id"] != self.board_id or data["fingerprint"] != self.fingerprint:
            raise ElectricalError(
                "review record belongs to a different board or delivery version"
            )
        if (
            type(data["revision"]) is not int
            or data["revision"] < 0
            or not isinstance(data["entries"], dict)
        ):
            raise ElectricalError("invalid review revision or entries")
        for key, entry in data["entries"].items():
            if (
                key not in self.objects
                or not isinstance(entry, dict)
                or set(entry) != {"status", "note", "updated_at"}
            ):
                raise ElectricalError("invalid review object or entry: " + str(key))
            if not isinstance(entry["status"], str) or entry["status"] not in STATUSES:
                raise ElectricalError("invalid review status")
            if not isinstance(entry["note"], str) or len(entry["note"]) > 20000:
                raise ElectricalError(
                    "review note must be text of at most 20000 characters"
                )
            try:
                parsed = datetime.fromisoformat(entry["updated_at"])
                if parsed.utcoffset() is None:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ElectricalError("invalid review update timestamp") from None
        return data

    def _read(self):
        if not self.path.exists():
            return self.empty()
        try:
            return self.validate(json.loads(self.path.read_text(encoding="utf-8")))
        except (ValueError, TypeError) as exc:
            raise ElectricalError(
                f"invalid review state at {self.path}: {exc}"
            ) from exc

    def read(self):
        with self.locked():
            return self._read()

    @staticmethod
    def check_revision(data, revision):
        if type(revision) is not int or revision != data["revision"]:
            raise ReviewConflict(
                "review changed in another tab; reload records before retrying"
            )

    def _write(self, data):
        self.validate(data)
        encoded = canonical(data) + "\n"
        if len(encoded.encode()) > MAX_BODY - 4096:
            raise ElectricalError("review record exceeds the 8 MiB import/export limit")
        fd, name = tempfile.mkstemp(prefix=".review-", dir=self.directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.path)
        finally:
            Path(name).unlink(missing_ok=True)
        return data

    def update(self, revision, changes):
        if not isinstance(changes, dict) or not changes:
            raise ElectricalError("changes must contain review objects")
        with self.locked():
            data = self._read()
            self.check_revision(data, revision)
            for key, change in changes.items():
                if (
                    key not in self.objects
                    or not isinstance(change, dict)
                    or not change
                    or set(change) - {"status", "note"}
                ):
                    raise ElectricalError("invalid review change")
                entry = data["entries"].get(key, {"status": "pending", "note": ""})
                data["entries"][key] = dict(
                    entry, **change, updated_at=datetime.now(timezone.utc).isoformat()
                )
            data["revision"] += 1
            return self._write(data)

    def preview(self, revision, imported):
        imported = self.validate(imported)
        current = self.read()
        self.check_revision(current, revision)
        keys = set(current["entries"]) | set(imported["entries"])
        changed = sorted(
            key
            for key in keys
            if current["entries"].get(key) != imported["entries"].get(key)
        )
        return {
            "revision": revision,
            "changed": changed,
            "removed": sorted(set(current["entries"]) - set(imported["entries"])),
            "total": len(imported["entries"]),
        }

    def replace(self, revision, imported):
        imported = copy.deepcopy(self.validate(imported))
        with self.locked():
            self.check_revision(self._read(), revision)
            imported["revision"] = revision + 1
            return self._write(imported)


class ReviewServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, package_dir, *, port=0, state_dir=None):
        self.package = load_package(package_dir)
        self.store = ReviewStore(self.package, package_dir, state_dir)
        self.token = secrets.token_urlsafe(32)
        super().__init__(("127.0.0.1", port), ReviewHandler)
        self.url = f"http://127.0.0.1:{self.server_port}"


class ReviewHandler(BaseHTTPRequestHandler):
    server_version = "DesignReview/1"

    def log_message(self, *args):
        pass

    def send(
        self,
        status,
        data,
        content_type="application/json; charset=utf-8",
        attachment=False,
    ):
        body = data if isinstance(data, bytes) else (canonical(data) + "\n").encode()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'",
        )
        if attachment:
            self.send_header(
                "Content-Disposition", 'attachment; filename="review.json"'
            )
        self.end_headers()
        self.wfile.write(body)

    def allowed(self, mutation=False):
        if self.headers.get("Host") != urlsplit(self.server.url).netloc:
            self.send(403, {"error": "unexpected host"})
            return False
        if self.headers.get("Origin") not in (None, self.server.url):
            self.send(403, {"error": "unexpected origin"})
            return False
        if mutation and self.headers.get("X-Review-Token") != self.server.token:
            self.send(403, {"error": "invalid session token"})
            return False
        return True

    def do_GET(self):
        if not self.allowed():
            return
        path = urlsplit(self.path).path
        try:
            if path == "/api/package":
                self.send(200, dict(self.server.package, token=self.server.token))
            elif path in ("/api/review", "/api/review/export"):
                self.send(
                    200, self.server.store.read(), attachment=path.endswith("export")
                )
            elif path in STATIC:
                name, mime = STATIC[path]
                self.send(
                    200,
                    files("design2allegro")
                    .joinpath("review_static", name)
                    .read_bytes(),
                    mime,
                )
            else:
                self.send(404, {"error": "not found"})
        except (OSError, ValueError) as exc:
            self.send(500, {"error": str(exc)})

    def do_PATCH(self):
        self.mutate()

    def do_POST(self):
        self.mutate()

    def mutate(self):
        if not self.allowed(mutation=True):
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                self.send(413, {"error": "request must be between 1 byte and 8 MiB"})
                return
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ElectricalError("request must be an object")
            path = urlsplit(self.path).path
            if (
                path == "/api/review"
                and self.command == "PATCH"
                and set(body) == {"revision", "changes"}
            ):
                result = self.server.store.update(body["revision"], body["changes"])
            elif (
                path in ("/api/review/import/preview", "/api/review/import")
                and self.command == "POST"
                and set(body) == {"revision", "record"}
            ):
                fn = (
                    self.server.store.preview
                    if path.endswith("preview")
                    else self.server.store.replace
                )
                result = fn(body["revision"], body["record"])
            else:
                raise ElectricalError("invalid review request")
            self.send(200, result)
        except ReviewConflict as exc:
            self.send(409, {"error": str(exc)})
        except (ValueError, TypeError) as exc:
            self.send(400, {"error": str(exc)})
        except OSError as exc:
            self.send(500, {"error": "cannot save review: " + str(exc)})


def serve_review(directory, *, port=0, state_dir=None, open_browser=True):
    if not 0 <= port <= 65535:
        raise ElectricalError("port must be between 0 and 65535")
    with ReviewServer(directory, port=port, state_dir=state_dir) as server:
        print(
            f"Review: {server.url}\nRecords: {server.store.path}\nPress Ctrl+C to stop.",
            flush=True,
        )
        if open_browser:
            try:
                webbrowser.open(server.url)
            except webbrowser.Error:
                pass  # The printed URL remains usable on headless hosts.
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    return 0
