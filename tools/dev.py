"""Isolated development tasks for the Circuit compiler."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import venv
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "parser"


def run(args, label, *, env=None, cwd=None, expected=0):
    logs = BUILD / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        list(map(str, args)),
        cwd=cwd or ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    (logs / (label + ".log")).write_text(result.stdout)
    print(result.stdout, end="")
    if result.returncode != expected:
        raise SystemExit(f"{label}: exit {result.returncode}, expected {expected}")


def environment():
    return dict(os.environ, PYTHONPATH=str(ROOT / "src"), PYTHONDONTWRITEBYTECODE="1")


def build():
    stage = BUILD / "package-source"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copytree(
        ROOT / "src" / "design2allegro",
        stage / "src" / "design2allegro",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copy2(ROOT / name, stage / name)
    run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", ROOT / "dist", stage],
        "build",
    )
    wheel = ROOT / "dist" / "design2allegro-3.2.0-py3-none-any.whl"
    (ROOT / "dist" / "design2allegro-SHA256SUMS").write_text(
        hashlib.sha256(wheel.read_bytes()).hexdigest() + "  " + wheel.name + "\n"
    )
    return wheel


def verify_review(entry, package, work, env):
    """Exercise the installed CLI and bundled assets outside the checkout."""
    log = work / "review-server.log"
    with log.open("w") as stream:
        process = subprocess.Popen(
            [
                str(entry),
                "review",
                str(package),
                "--no-browser",
                "--state-dir",
                str(work / "review-state"),
            ],
            cwd=work,
            env=env,
            stdout=stream,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 20
            url = None
            while time.monotonic() < deadline:
                lines = log.read_text().splitlines()
                url = next(
                    (
                        line.removeprefix("Review: ")
                        for line in lines
                        if line.startswith("Review: ")
                    ),
                    None,
                )
                if url:
                    break
                if process.poll() is not None:
                    raise RuntimeError(log.read_text())
                time.sleep(0.05)
            if not url:
                raise RuntimeError("review server startup timed out")
            with urlopen(url + "/api/package", timeout=5) as response:
                package_data = json.load(response)
            for resource in (
                "/",
                "/app.js",
                "/style.css",
                "/vendor/cytoscape.min.js",
                "/vendor/LICENSE.cytoscape",
            ):
                with urlopen(url + resource, timeout=5) as response:
                    assert response.status == 200 and response.read()
            key = next(iter(package_data["objects"]))
            request = Request(
                url + "/api/review",
                method="PATCH",
                data=json.dumps(
                    {
                        "revision": 0,
                        "changes": {key: {"status": "approved", "note": "wheel smoke"}},
                    }
                ).encode(),
                headers={
                    "Content-Type": "application/json",
                    "X-Review-Token": package_data["token"],
                },
            )
            with urlopen(request, timeout=5) as response:
                saved = json.load(response)
                assert (
                    saved["revision"] == 1
                    and saved["entries"][key]["note"] == "wheel smoke"
                )
            print(
                "Installed review CLI: assets, frozen package API and saved annotation passed."
            )
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def verify():
    wheel = build()
    dest = BUILD / "wheel-env"
    if dest.exists():
        shutil.rmtree(dest)
    venv.EnvBuilder(with_pip=False).create(dest)
    python = dest / "bin" / "python"
    run(
        [sys.executable, "-m", "pip", "--python", python, "install", wheel],
        "package-install",
    )
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("PYTHONPATH", None)
    with tempfile.TemporaryDirectory(prefix="design2allegro-") as folder:
        work = Path(folder)
        shutil.copytree(ROOT / "tests" / "fixtures" / "fpga_soc", work / "project")
        entry = dest / "bin" / "design2allegro"
        run(
            [
                python,
                "-c",
                "import importlib.util; assert importlib.util.find_spec('skidl') is None; assert importlib.util.find_spec('_skidl_native') is None; assert importlib.util.find_spec('yaml') is None",
            ],
            "package-independent",
            env=env,
            cwd=work,
        )
        run(
            [entry, "check", work / "project/board.circuit", "--json"],
            "package-check",
            env=env,
            cwd=work,
        )
        run(
            [
                entry,
                "build",
                work / "project/board.circuit",
                "-o",
                work / "output",
                "--json",
            ],
            "package-build",
            env=env,
            cwd=work,
        )
        run(
            [entry, "verify", work / "output", "--json"],
            "package-verify",
            env=env,
            cwd=work,
        )
        shutil.copytree(ROOT / "tests/fixtures/parameterized", work / "parameterized")
        run(
            [
                entry,
                "build",
                work / "parameterized/board.circuit",
                "-o",
                work / "parameterized-output",
                "--json",
            ],
            "package-circuit2-build",
            env=env,
            cwd=work,
        )
        run(
            [entry, "verify", work / "parameterized-output", "--json"],
            "package-circuit2-verify",
            env=env,
            cwd=work,
        )
        verify_review(entry, work / "parameterized-output", work, env)
        bad = work / "bad.circuit"
        bad.write_text('circuit 1;\nboard x { id = "x"; id = "x"; }\n')
        run(
            [entry, "check", bad, "--json"],
            "package-negative",
            env=env,
            cwd=work,
            expected=2,
        )


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "command",
        choices=[
            "build",
            "test",
            "test-ui",
            "example",
            "benchmark",
            "verify-package",
            "clean",
        ],
    )
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if args.dry_run and args.command != "clean":
        p.error("--dry-run is only valid with clean")
    if args.command == "clean":
        # Preserve all pre-migration outputs, source backups, dist/, .venv/ and external archives.
        if BUILD.is_symlink():
            raise SystemExit("refusing symlink cleanup")
        if BUILD.exists():
            print(("would remove " if args.dry_run else "remove ") + str(BUILD))
            if not args.dry_run:
                shutil.rmtree(BUILD)
    elif args.command == "build":
        build()
    elif args.command == "verify-package":
        verify()
    elif args.command in ("test", "test-ui"):
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                ROOT
                / ("tests/review_ui" if args.command == "test-ui" else "tests/parser"),
                "-q",
                "--basetemp",
                BUILD / ("review-ui-tmp" if args.command == "test-ui" else "test-tmp"),
            ],
            args.command,
            env=environment(),
        )
    elif args.command == "example":
        for name, project in (
            ("fpga_soc", ROOT / "tests/fixtures/fpga_soc"),
            ("nucleo_l432kc", ROOT / "schematics/nucleo_l432kc"),
        ):
            run(
                [
                    sys.executable,
                    "-m",
                    "design2allegro",
                    "build",
                    project / "board.circuit",
                    "-o",
                    BUILD / name,
                    "--json",
                ],
                "example-" + name,
                env=environment(),
            )
            run(
                [
                    sys.executable,
                    "-m",
                    "design2allegro",
                    "verify",
                    BUILD / name,
                    "--json",
                ],
                "verify-" + name,
                env=environment(),
            )
    elif args.command == "benchmark":
        run(
            [sys.executable, ROOT / "tools/benchmark.py"],
            "benchmark",
            env=environment(),
        )


if __name__ == "__main__":
    main()
