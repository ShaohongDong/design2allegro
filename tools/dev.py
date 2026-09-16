"""Isolated development tasks for the YAML compiler."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

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
    wheel = ROOT / "dist" / "design2allegro-2.0.0-py3-none-any.whl"
    (ROOT / "dist" / "design2allegro-SHA256SUMS").write_text(
        hashlib.sha256(wheel.read_bytes()).hexdigest() + "  " + wheel.name + "\n"
    )
    return wheel


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
                "import importlib.util; assert importlib.util.find_spec('skidl') is None; assert importlib.util.find_spec('_skidl_native') is None",
            ],
            "package-independent",
            env=env,
            cwd=work,
        )
        run(
            [entry, "check", work / "project/board.yaml", "--json"],
            "package-check",
            env=env,
            cwd=work,
        )
        run(
            [
                entry,
                "build",
                work / "project/board.yaml",
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
        bad = work / "bad.yaml"
        bad.write_text("version: 1\nversion: 1\n")
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
        choices=["build", "test", "example", "benchmark", "verify-package", "clean"],
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
    elif args.command == "test":
        run(
            [
                sys.executable,
                "-m",
                "pytest",
                ROOT / "tests/parser",
                "-q",
                "--basetemp",
                BUILD / "test-tmp",
            ],
            "test",
            env=environment(),
        )
    elif args.command == "example":
        for name in ("fpga_soc",):
            run(
                [
                    sys.executable,
                    "-m",
                    "design2allegro",
                    "build",
                    ROOT / f"tests/fixtures/{name}/board.yaml",
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
        run(
            [
                sys.executable,
                "-m",
                "design2allegro",
                "check",
                ROOT / "schematics/nucleo_l432kc/board.yaml",
                "--json",
            ],
            "nucleo-strict-attributes",
            env=environment(),
            expected=2,
        )
        report = json.loads((BUILD / "logs/nucleo-strict-attributes.log").read_text())
        failures = [
            d
            for d in report["diagnostics"]
            if d["severity"] == "ERROR" and d["status"] != "PASS"
        ]
        if not failures or any(d["rule"] != "PROPERTY.REQUIRED" for d in failures):
            raise SystemExit("unexpected NUCLEO validation failure")
        print(
            f"NUCLEO: export blocked by {len(failures)} missing required attributes; connectivity checks passed."
        )
    elif args.command == "benchmark":
        run(
            [sys.executable, ROOT / "tools/benchmark.py"],
            "benchmark",
            env=environment(),
        )


if __name__ == "__main__":
    main()
