# Design format, version 2

`board.yaml` is the design entrypoint. `components.json`, BOM, PINOUT and
FOOTPRINTS are build outputs, never design inputs. The compiler resolves an
offline shared device catalogue distributed with the wheel. Version 1 input is
rejected with a migration message; existing version 1 delivery packages remain
readable by `verify`.

## Design and libraries

```yaml
version: 2
id: my-board
name: my_board
library: {name: standard, version: '1'}
top: board
modules:
  board:
    parts:
      reset_pullup:
        id: reset-pullup
        identity_namespace: ''
        device: generic.resistor
        package: resistor_0603
        assembly: fitted
        properties:
          resistance: '10 kohm'
          tolerance: '1 %'
          power_rating: '0.1 W'
    nc:
      - {part: reset_pullup, pin: A}
      - {part: reset_pullup, pin: B}
```

`id` identifies the board; `name` supplies `<name>.tel`, independently of input
filename/output directory. No `references`, per-instance `ref`, `value` or local
`components.yaml` inputs are accepted. UTF-8 YAML uses string keys, explicit
units, lowercase booleans, and no aliases, merge keys or executable tags.
Duplicate keys, unknown structural fields and nonfinite metadata are errors.

The bundled catalogue is `libraries/<name>/<version>.json` within the installed
package. `load_design(path, library_root=...)` or the explicit
`DESIGN2ALLEGRO_LIBRARY_ROOT` environment variable selects another *shared*
catalogue root with that layout. There is no project-directory fallback or
network lookup. Catalogue versions and raw content hashes enter `inputs.json` and the reference
lock. Modifying a previously built catalogue without changing its version fails;
publish a new catalogue revision and update the design selection explicitly.

Each catalogue device declares category, reference prefix, logical pins and
their electrical types, allowed package bindings, optional pin groups, fixed
properties and source information. Each package binds every distinct logical
pin to exactly one physical pad; exposed pads must be explicit logical pins.
Multiple power/ground pads therefore have distinct logical names. The package
name identifies an externally supplied Allegro symbol, not generated geometry.
A concrete model's fixed specifications cannot be overridden by instances.
Generic models require instance specifications. Synthetic regression devices
are explicitly identified in their catalogue source metadata.

## Properties and assembly

All resolved properties appear in `components.json`. `normalized_properties`
uses decimal SI values and explicit dimensions; BOM grouping compares these
values, device, package and assembly status. Equivalent unit spellings group
together; different tolerance, voltage rating or power rating do not.

- Resistors require `resistance`, `tolerance`, `power_rating`.
- Capacitors require `capacitance`, `voltage_rating`, `tolerance`, `dielectric`,
  `polarized` (boolean). Absolute tolerance such as `0.25 pF` is supported.
- Inductors require `inductance`, `current_rating`, `dc_resistance`; ferrites use
  `impedance` and `impedance_frequency` instead of inductance.
- Crystals require `frequency`, `load_capacitance`, `frequency_tolerance`.
- Diodes/LEDs require `type`, `current_rating`, `voltage_rating`; LEDs add `color`.
- Transistors require `type`, `current_rating`, `voltage_rating`, `power_rating`.
- ICs require `manufacturer`, `mpn`, `supply_min`, `supply_max`; regulators add
  `output_voltage`, `current_rating`.
- Connectors require `positions`, `pitch`, `current_rating`, `voltage_rating`.
- Switches require `initial_state`, `current_rating`, `voltage_rating`;
  solder bridges/jumpers require `initial_state` (`open` or `closed`).

The authoritative profiles are in `properties.py`. Missing required properties
produce non-waivable `PROPERTY.REQUIRED` errors, including DNP parts. No guessed
ratings or `unknown` placeholders can pass. `electrical` remains the input for
operating conditions and electrical rule models; it cannot conflict with a
resolved resistance, assembly state or default switch state. Declaring ratings
does not validate undeclared working voltage, dissipation or derating.

`assembly` is required (`fitted` or `dnp`). DNP parts retain physical pads and
connections. Board-level `accessories` contain `id`, `description`, positive
`quantity`, and `assembly`; they appear in BOM without introducing PCB pads.

## Identity, hierarchy and connectivity

Part names express function; immutable `id` fields express identity. Module
instances also require immutable IDs. By default an expanded part's identity is
its ancestor instance IDs followed by its local ID, joined with `/`. This makes
reusable modules independent. Renaming local names does not affect identity.

For a physical part that must move between module instances, specify a fixed
`identity_namespace` (empty string means board-global). Keep that namespace and
ID unchanged during moves. NUCLEO parts explicitly pin their namespaces. Do not
pin one absolute namespace inside a multiply instantiated module: that would
create duplicate identities, which the compiler rejects. Copying a physical
part requires a new ID; editing/reparenting preserves its explicit namespace.

Ports and buses retain the original explicit semantics: `ports: {data:
{width: 4}}`, `instances: {left: {id: left, module: endpoint}}`. Net endpoints
are `{part, pin}`, `{part, group}`, `{port}`, or `{instance, port}`. Group members
are ordered logical names defined by the device library. All endpoint widths
must match; no implicit broadcast, reversal or global power-net merging occurs.
Every physical pin must be connected or explicitly `nc`. NC uses local part/pin
or part/group endpoints. Duplicate use and connections conflicting with NC fail.
Ports must connect on both sides; shorting distinct same-scope nets fails.

The canonical net name is the shallowest participating path, then lexical order.
Bus bits append `[i]`. `net_aliases` preserves other names. Hierarchy is bounded
to 64 levels and 100,000 expanded instances.

Rules, supplemental models and waivers use stable part identities and logical
pin IDs, for example `target/mcu.PA13`; net rules use canonical net names.
`rules.yaml` remains optional (inline rules also work). Rule-set version remains
1: the electrical rule language is unchanged, only its object IDs changed.
See [rules.md](rules.md). Diagnostics retain source locations and functional
paths; annotated delivery snapshots also contain allocated references.

## Annotation and delivery

`check` builds/checks a logical snapshot and does not write annotation state.
`build` checks it, allocates references and publishes all artifacts together.
`design.lock.json`, beside the entrypoint, is engine-owned history: commit it,
restore it when missing, and do not manually renumber it.

First allocation sorts stable identities and numbers each library-defined prefix
from one. Subsequent builds keep assignments; additions use the historical
maximum plus one. Deleted assignments remain reserved. Prefix changes retire
old references and allocate in the new prefix. Other property changes do not
renumber components. Conflicting, malformed or foreign-board locks are errors.

Builds serialize with a nonblocking directory lock. A persistent build marker
and existing v2 output detect lost annotation history. Copy the lock when moving
or cloning a design; deleting all history cannot be detected as an earlier build.
A transaction journal permits recovery if publication is interrupted. Normal
pre-commit failures restore the previous package; a crash after package publication
is recovered forward by verifying the package and committing its pending lock.

Outputs include `.tel`, `devices/*.txt`, `components.json`, `BOM.md`, `BOM.csv`,
`PINOUT.md`, `FOOTPRINTS.md`, `references.json`, circuit/hierarchy/inputs snapshots,
DRC reports, electrical rules, import instructions and a hashed manifest.
Documentation is generated from the same immutable annotated circuit. Verification
independently parses the netlist and device files, checks all physical connectivity,
and checks derived files against the circuit. Unmanaged output files prevent
replacement. Version 2 snapshots retain stable IDs as keys and store physical
references separately; public `compile_design()` does not allocate references.

Exit codes: 0 success, 2 invalid/blocked design, 1 I/O/internal failure. Python
entrypoints remain `load_design`, `compile_design`, `check_design`, `export_design`.
A successful package verification is offline acceptance, not actual Allegro import
or hardware validation.
