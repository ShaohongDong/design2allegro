# design2allegro

A **YAML design compiler** generating Allegro Telesis netlists and matching
component, BOM, pinout and footprint documentation.

```text
board.yaml + versioned shared device catalogue
  → typed specifications → stable-identity circuit → electrical checks
  → automatic reference annotation → netlist + documentation → readback
```

## Install and run

Python 3.12+ and Linux are required. Allegro is the only output backend.

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/design2allegro check tests/fixtures/fpga_soc/board.yaml
.venv/bin/design2allegro build tests/fixtures/fpga_soc/board.yaml -o build/parser/fpga_soc
.venv/bin/design2allegro verify build/parser/fpga_soc
```

This synthetic regression design exercises the compiler; it is not a hardware
reference board. The output is `fpga_soc.tel`, named by the design's explicit `name` field.
Commit the automatically generated `design.lock.json` alongside the design to
preserve reference history. `check` does not write annotation state.

## Design contract

- Version 2 inputs use functional instance names and immutable IDs, not `U1/R1`
  assignments. Reusable modules keep explicit ports, buses and NC declarations.
- The shared, versioned device catalogue ships in the wheel. It defines logical
  pins, physical pad mappings, allowed Allegro packages and fixed model specs.
- Instance properties include resistor resistance/tolerance/power, capacitor
  capacitance/tolerance/voltage/type, and category-specific specifications.
  Units are checked and normalized. Fixed model specifications cannot be changed.
- Missing mandatory specifications block delivery, including DNP parts. Ratings
  are not proof of operating margins without declared operating conditions.
- Connections and rules use stable identities; generated reference numbers are
  separate. Existing numbers persist across edits; removed numbers are reserved.
- Netlist, BOM, pinout, footprint and component inventory are generated from one
  frozen circuit snapshot and published together with rollback/recovery support.

See [input format and migration details](docs/design-format.md),
[electrical rules](docs/rules.md), and [development](docs/development.md).

## NUCLEO-L432KC migration status

The [official board design](schematics/nucleo_l432kc/README.md) has been migrated
to version 2 with **89 parts, 312 pads, 82 nets and 16 NC pins**, retaining official
connectivity and assembly checks. Its project-local `components.yaml`, `BOM.md`,
`PINOUT.md` and `FOOTPRINTS.md` are removed as design inputs.

**Its new strict build is blocked by missing mandatory specifications.** Known
BOM facts were transcribed; unsupported ratings were not guessed. Run `check` to
see every missing field and its source position.
Historical output in `build/` is not a successful version 2 rebuild.

## Delivery and acceptance

Outputs include `<name>.tel`, `devices/`, `components.json`, `BOM.md`, `BOM.csv`,
`PINOUT.md`, `FOOTPRINTS.md`, `references.json`, immutable circuit and provenance
snapshots, DRC reports and a hashed manifest. `verify` parses physical netlists
and device files and checks derived artifacts against the delivered circuit.

**Actual Allegro import is unverified.** Supply matching Allegro package symbols
and padstacks; the compiler does not generate `.psm`, padstacks, PCB geometry or
imported Allegro constraints. Version 1 input is retired; existing version 1
packages remain available for read-only verification.

## Development

```sh
make test            # schema, rules, annotation, transactions and delivery
make example         # build regression fixture; confirm NUCLEO's strict property blockers
make benchmark       # 10,000 pins through loading, checking and export
make build           # version 2 wheel, including the shared catalogue
make verify-package  # isolated wheel-only positive/negative CLI checks
make clean-preview   # preview current build/parser cleanup
```

Historical `build/` and `dist/` outputs are preserved. The retired SKiDL runtime
and other EDA backends are not dependencies.
