# Repository Guidelines

## Project Structure & Module Organization

This repository builds `design2allegro`, a YAML circuit compiler producing
Allegro-oriented Telesis packages. Runtime code lives in `src/design2allegro/`:
loading/schema validation, hierarchy expansion, immutable circuit models,
electrical checks, export and independent readback verification. The bundled
`schema.json` defines version 1 inputs. Tests live in `tests/parser/`; complete
YAML projects live in `schematics/nucleo_l432kc/`.
Historical synthetic designs live in `tests/fixtures/` for regression only.
Allegro Telesis is the only supported export format.
See `docs/design-format.md` for input semantics and `docs/rules.md` for rules.

## Build, Test, and Development Commands

Use Python 3.12+ and install `.venv/bin/python -m pip install -e '.[dev]'`.
Make defaults to `.venv/bin/python`; override `PYTHON` when necessary.

- `make test`: run parser, electrical-rule, CLI and output regressions.
- `make example`: compile and verify all example projects.
- `make benchmark`: process 10,000 physical pins and record time/memory.
- `make build`: build one pure-Python wheel in `dist/`.
- `make verify-package`: test wheel-only installation in a fresh environment.
- `make clean-preview`: preview cleanup of current `build/parser/` outputs.

## Coding Style & Naming Conventions

Use four-space indentation, UTF-8, LF, no trailing whitespace and final
newlines; Make recipes use tabs. Use Black and isort's Black profile. Python
functions/modules use `snake_case`, classes use `PascalCase`. Keep parsing,
semantic compilation and exporting separate; new flows must not depend on the
retired SKiDL API or native engine.

## Testing Guidelines

Use pytest with `test_*.py` files and `test_*` functions. Exercise real YAML inputs
for parser changes. Cover source-located failures, bus order, reference stability,
NC handling, required unknown rules and preservation of existing output on failure.
Use handwritten output fixtures alongside full inventory/connectivity readback.
No numeric coverage threshold is configured. Run `make test` for substantive
changes and `make verify-package` for packaging changes.

## Commit & Pull Request Guidelines

This project starts with an initial import; no established commit convention exists.
Use focused commits with imperative subjects. Describe behavior, link relevant
issues and report validation results. Distinguish offline package verification
from actual Allegro import, which remains unverified.

## Artifact Handling

Preserve historical `build/` and `dist/` artifacts, `.venv/`, migration backups
and external archives. Current cleanup targets only `build/parser/`. Never remove
fixtures by filename extension. Preserve user files in output directories.
