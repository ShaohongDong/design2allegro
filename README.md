# design2allegro

A **Circuit language compiler** generating Allegro Telesis netlists and matching
component, BOM, pinout and footprint documentation.

```text
board.circuit + included .circuit fragments + versioned shared device catalogue
  → typed specifications → stable-identity circuit → electrical checks
  → automatic reference annotation → netlist + documentation → readback
```

## Install and run

Python 3.12+ and Linux are required. Allegro is the only output backend.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/design2allegro check tests/fixtures/fpga_soc/board.circuit
.venv/bin/design2allegro build tests/fixtures/fpga_soc/board.circuit -o build/parser/fpga_soc
.venv/bin/design2allegro verify build/parser/fpga_soc
```

This synthetic regression design exercises the compiler; it is not a hardware
reference board. The output is `fpga_soc.tel`, named by the name in the `board` declaration.
Commit the automatically generated `design.lock.json` alongside the design to
preserve reference history. `check` does not write annotation state.

## Design contract

- Circuit 1/2 inputs use functional instance names and immutable IDs, not `U1/R1`
  assignments. Reusable modules keep explicit ports, buses and NC declarations.
- Circuit 2 adds explicit includes/aliases, typed constants, parameterized modules,
  dimensional arithmetic, named rule groups and instance-local rules.
- The shared, versioned device catalogue ships in the wheel. It defines logical
  pins, physical pad mappings, allowed Allegro packages and fixed model specs.
- Instance properties include resistor resistance/tolerance/power, capacitor
  capacitance/tolerance/voltage/type, and category-specific specifications.
  Units are checked and normalized. Fixed model specifications cannot be changed.
- Missing mandatory specifications block delivery, including DNP parts. Ratings
  are not proof of operating margins without declared operating conditions.
- Connections and rules use functional names resolved to stable identities.
  Generated reference numbers are separate. Existing numbers persist across edits; removed numbers are reserved.
- Netlist, BOM, pinout, footprint and component inventory are generated from one
  frozen circuit snapshot and published together with rollback/recovery support.

See [input format and migration details](docs/design-format.md),
[electrical rules](docs/rules.md), and [development](docs/development.md).

## NUCLEO-L432KC

The [board design](schematics/nucleo_l432kc/README.md) uses Circuit 2 fragments
for templates, interfaces, power, ST-LINK, target and rules. It retains **89 parts,
312 pads, 82 nets and 16 NC pins**. Required specifications are complete;
documented project procurement selections and the official BOM differences are
recorded in its README and `sources.json`. It uses `standard@2`; revision 1 is
preserved unchanged. Checks pass with the 10 documented ERC warnings.

```sh
.venv/bin/design2allegro build schematics/nucleo_l432kc/board.circuit -o build/parser/nucleo_l432kc
.venv/bin/design2allegro verify build/parser/nucleo_l432kc
```

The generated netlist is `build/parser/nucleo_l432kc/nucleo_l432kc.tel`.

## Human review

Run `design2allegro review <output-directory>` to inspect a verified v2 delivery
in a local browser. The full-board topology links components, nets and physical
pins to specifications and diagnostics. Human statuses and notes autosave outside
the package, with version isolation, import/export and concurrent-edit detection.
See the [review guide](docs/review.md) for controls and record storage.

## Delivery and acceptance

Outputs include `<name>.tel`, `devices/`, `components.json`, `BOM.md`, `BOM.csv`,
`PINOUT.md`, `FOOTPRINTS.md`, `references.json`, immutable circuit and provenance
snapshots, DRC reports and a hashed manifest. `verify` parses physical netlists
and device files and checks derived artifacts against the delivered circuit.

**Actual Allegro import is unverified.** Supply matching Allegro package symbols
and padstacks; the compiler does not generate `.psm`, padstacks, PCB geometry or
imported Allegro constraints. All YAML input is retired; existing version 1
packages remain available for read-only verification.

## Development

```sh
make test            # schema, rules, annotation, transactions and delivery
make test-ui         # synthetic review browser tests (Playwright Chromium)
make example         # build and verify the regression fixture and NUCLEO
make benchmark       # 10,000 pins through loading, checking and export
make build           # version 3 wheel, including the shared catalogue
make verify-package  # isolated wheel-only positive/negative CLI checks
make clean-preview   # preview current build/parser cleanup
```

Historical `build/` and `dist/` outputs are preserved. The retired SKiDL runtime
and other EDA backends are not dependencies.
