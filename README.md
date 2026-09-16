# design2allegro

A dedicated **YAML circuit design compiler** that emits an offline-verified
Allegro Telesis delivery package. Describe components, hierarchical modules,
explicit ports, buses and physical references without executing Python designs.

```text
YAML design + component libraries
    → schema validation → hierarchy/bus expansion → physical circuit
    → ERC / declared electrical rules → Telesis + device files → readback
```

## Install and run

Python 3.12 or newer is required. Allegro Telesis is the only supported export
format. Linux is required for atomic replacement of existing output packages.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/design2allegro check schematics/nucleo_l432kc/board.yaml
.venv/bin/design2allegro build schematics/nucleo_l432kc/board.yaml -o build/board
.venv/bin/design2allegro verify build/board --json
```

See [the input format](docs/design-format.md), [development instructions](docs/development.md)
and the complete [NUCLEO-L432KC example](schematics/nucleo_l432kc/board.yaml).
The [official NUCLEO-L432KC board example](schematics/nucleo_l432kc/README.md) includes
ST-LINK, supply circuits, default assembly settings and source traceability.
The machine-readable schema ships as `design2allegro/schema.json`.

## Design contract

- Component libraries declare **every physical pin**, its unique logical name,
  electrical type, and an explicit Allegro package name.
- Modules contain components, reusable child modules, typed-width ports and nets.
  Buses connect position by position; there is no implicit scalar broadcast.
- Top-level reference mappings assign paths such as `fpga/endpoint/chip` to `U1`.
- Every physical pin must be connected or explicitly NC. Invalid references,
  duplicate assignments, width mismatches and recursive modules block compilation.
- ERC always runs. Optional declarative rules cover voltage, power, interfaces,
  banks, DDR and related electrical properties. Required unknown results block
  delivery; warnings alone do not. Exact documented waivers are supported.

## Outputs and acceptance boundary

A successful build writes `<board-name>.tel`, `devices/*.txt`, `circuit.json`,
`hierarchy.json`, `inputs.json`, `drc.json`, `drc.md`, `electrical-rules.json`,
`IMPORT.md` and `manifest.json`. Hashes, physical inventory, device terminals and
connectivity are verified before publishing. Repeated builds of unchanged inputs
produce identical files. Source locations and input hashes intentionally change
when source files change, even if the electrical snapshot digest stays the same.

For `schematics/nucleo_l432kc/board.yaml`, the netlist is `nucleo_l432kc.tel`.
For a design named `sensor.yaml`, it is `sensor.tel`; the output directory does
not change the filename. Board names must use ASCII letters, digits, `_`, `-` or
`.` and start with a letter, digit or `_`.

**Actual Allegro import has not been verified.** Import using your version's
Telesis/Other logic workflow and supply matching package symbols and padstacks.
This tool does not create `.psm`, padstacks or Allegro constraints. Electrical
rules are sidecar data, not imported physical constraints.

## Development

```bash
make test            # parser, hierarchy, rules, CLI and export regressions
make example         # compile and verify all YAML examples
make benchmark       # 10,000 physical pins, timings and peak RSS
make build           # single pure-Python wheel in dist/
make verify-package  # fresh venv, wheel-only positive and negative CLI checks
make clean-preview   # preview removal of current build/parser/ outputs
```

The old Python design API, native engine and other EDA backends have been retired;
there is no compatibility layer. Existing `build/` and `dist/` artifacts from the
previous implementation are historical evidence, not current compiler outputs.
