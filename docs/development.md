# Development

Use Python 3.12+ and `.venv`; install `pip install -e '.[dev]'`. Make targets use
`.venv/bin/python` unless `PYTHON=/path/to/python` is supplied. The runtime package
is `src/design2allegro/`; schemas ship inside its wheel. Tests live in
`tests/parser/`. Examples are YAML projects under `schematics/`.

`make test` runs parser, hierarchy/bus, electrical-rule, CLI and delivery tests.
`make example` compiles and independently verifies the board designs under `schematics/`.
`make benchmark` measures a 10,000-pin design from actual YAML loading through
export, recording timings and peak process RSS in `build/parser/benchmark/result.json`.
No timing threshold is implied by that measurement.

`make build` builds one `design2allegro` wheel from a staged source copy.
`make verify-package` installs it in a fresh virtual environment and runs all
three commands outside the repository, including negative input checks. It checks
that neither SKiDL nor the old native extension is installed in that environment.

Logs and disposable outputs are confined to `build/parser/`. `make clean-preview`
shows the cleanup target; `make clean` removes only that directory, preserving
`.venv`, `dist`, migration backups, historical build outputs and external archives.
New wheel hashes live in `dist/design2allegro-SHA256SUMS`; older wheel files remain
historical artifacts and must not be used to validate this implementation.

Format Python with Black and isort (`isort --profile black`). Add behavioral
regressions for changes to YAML semantics, connectivity or rule decisions.
Handwritten Telesis/device fixtures and round-trip inventory comparisons provide
offline evidence, not vendor-tool acceptance.

The previous source was archived locally before cleanup at
`build/migration/pre-parser-source.tar.gz`. That archive is not part of the package.
