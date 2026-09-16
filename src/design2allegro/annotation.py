"""Persistent automatic annotation and recoverable package/lock publication."""

import copy
import fcntl
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from .model import CompiledDesign, ElectricalError, canonical


def read_lock(path, board_id):
    if path.is_symlink():
        raise ElectricalError("symlink reference lock forbidden")
    if not path.exists():
        return {"version": 2, "board_id": board_id, "assignments": {}, "retired": []}
    try:

        def unique(pairs):
            out = {}
            for k, v in pairs:
                if k in out:
                    raise ElectricalError("duplicate reference lock key " + k)
                out[k] = v
            return out

        data = json.loads(path.read_text(), object_pairs_hook=unique)
    except ValueError as exc:
        raise ElectricalError("corrupt reference lock") from exc
    if (
        not isinstance(data, dict)
        or set(data) - {"version", "board_id", "assignments", "retired", "library"}
        or not {"version", "board_id", "assignments", "retired", "library"} <= set(data)
        or data["version"] != 2
        or data["board_id"] != board_id
    ):
        raise ElectricalError(
            "reference lock belongs to another board or has invalid schema"
        )
    if not isinstance(data["assignments"], dict) or not isinstance(
        data["retired"], list
    ):
        raise ElectricalError("invalid reference lock")
    library = data["library"]
    if (
        not isinstance(library, dict)
        or set(library) != {"name", "version", "sha256"}
        or not all(isinstance(v, str) for v in library.values())
        or not re.fullmatch("[a-f0-9]{64}", library["sha256"])
    ):
        raise ElectricalError("invalid locked catalogue identity")
    refs = list(data["assignments"].values()) + data["retired"]
    if any(
        not isinstance(v, str) or not re.fullmatch("[A-Z]+[1-9][0-9]*", v) for v in refs
    ) or len(set(refs)) != len(refs):
        raise ElectricalError("reference lock collision or invalid reference")
    if any(not re.fullmatch("[A-Za-z][A-Za-z0-9_/-]*", k) for k in data["assignments"]):
        raise ElectricalError("invalid lock identity")
    return data


def annotate(snapshot, previous):
    data = snapshot.data
    lock = copy.deepcopy(previous)
    library = dict(data["library"])
    library["sha256"] = data["inputs"][
        "catalog:" + library["name"] + "@" + library["version"]
    ]
    old_library = lock.get("library")
    if (
        old_library
        and (old_library["name"], old_library["version"])
        == (library["name"], library["version"])
        and old_library != library
    ):
        raise ElectricalError("catalogue content changed without a version change")
    lock["library"] = library
    used = list(lock["assignments"].values()) + lock["retired"]
    maximum = {}
    for ref in used:
        m = re.fullmatch("([A-Z]+)([0-9]+)", ref)
        maximum[m[1]] = max(maximum.get(m[1], 0), int(m[2]))
    for identity, part in sorted(data["parts"].items()):
        prefix = part["prefix"]
        old = lock["assignments"].get(identity)
        if old and re.fullmatch(prefix + "[1-9][0-9]*", old):
            ref = old
        else:
            if old:
                lock["retired"].append(old)
            maximum[prefix] = maximum.get(prefix, 0) + 1
            ref = prefix + str(maximum[prefix])
            lock["assignments"][identity] = ref
        part["reference"] = ref
    data["stage"] = "annotated"
    data["references"] = {k: p["reference"] for k, p in data["parts"].items()}
    return (
        CompiledDesign(
            canonical(data),
            snapshot.rules_json,
            snapshot.waivers_json,
            snapshot.design_path,
        ),
        lock,
    )


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def sync_package(path):
    for file in path.rglob("*"):
        if file.is_file():
            with file.open("rb") as stream:
                os.fsync(stream.fileno())
    for directory in sorted(
        (p for p in path.rglob("*") if p.is_dir()),
        key=lambda p: len(p.parts),
        reverse=True,
    ):
        sync_directory(directory)
    sync_directory(path)


def atomic_json(path, data):
    fd, name = tempfile.mkstemp(prefix="." + path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(canonical(data) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def deliver(snapshot, output, writer):
    from .telesis import publish

    if not snapshot.design_path:
        raise ElectricalError("build requires a source design path for its lock")
    folder = Path(snapshot.design_path).parent
    # Lock the directory inode: no persistent guard file and no unlink race.
    fd = os.open(folder, os.O_RDONLY)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ElectricalError("another build is updating this design") from exc
        lock_path = folder / "design.lock.json"
        journal = folder / ".design.transaction.json"
        marker = folder / ".design.built.json"
        if journal.is_symlink() or marker.is_symlink():
            raise ElectricalError("symlink build state forbidden")
        if journal.exists():
            pending = json.loads(journal.read_text())
            if pending.get("board_id") != snapshot.data["board_id"]:
                raise ElectricalError("transaction board mismatch")
            manifest = Path(pending["output"]) / "manifest.json"
            if (
                manifest.exists()
                and json.loads(manifest.read_text()).get("snapshot")
                == pending["snapshot"]
            ):
                from .verify import verify_package

                verify_package(manifest.parent)
                atomic_json(lock_path, pending["lock"])
                atomic_json(marker, {"board_id": pending["board_id"]})
            journal.unlink()
        target = Path(output).absolute()
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise ElectricalError("symlink output path forbidden")
        if not lock_path.exists() and (
            marker.exists() or (target / "manifest.json").exists()
        ):
            # Old v1 packages carry no v2 annotation state and may be replaced.
            old = (
                json.loads((target / "manifest.json").read_text())
                if (target / "manifest.json").exists()
                else {}
            )
            if marker.exists() or old.get("version") == 2:
                raise ElectricalError(
                    "reference lock missing for previously built design; restore design.lock.json"
                )
        previous = read_lock(lock_path, snapshot.data["board_id"])
        annotated, lock = annotate(snapshot, previous)
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".design-delivery-", dir=target.parent))
        stage.rmdir()
        published = False
        existed = target.exists()
        try:
            result = writer(annotated, stage)
            sync_package(stage)
            atomic_json(
                journal,
                {
                    "board_id": snapshot.data["board_id"],
                    "output": str(target),
                    "snapshot": annotated.digest,
                    "lock": lock,
                },
            )
            publish(stage, target)
            published = True
            sync_directory(target.parent)
            atomic_json(lock_path, lock)
            atomic_json(marker, {"board_id": snapshot.data["board_id"]})
            journal.unlink()
            return result
        except Exception:
            if published:
                # Before lock commit, restore the complete old package. After a
                # successful lock commit, keep the journal for forward recovery.
                committed = (
                    lock_path.exists() and json.loads(lock_path.read_text()) == lock
                )
                if not committed:
                    if existed:
                        publish(stage, target)
                    else:
                        os.replace(target, stage)
                    journal.unlink(missing_ok=True)
            elif journal.exists():
                journal.unlink()
            raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)
    finally:
        os.close(fd)
