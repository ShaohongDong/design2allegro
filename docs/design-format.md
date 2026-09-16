# Circuit language, versions 1 and 2

`board.circuit` is the single design entrypoint for design2allegro 3.x. It contains
board configuration and may include reusable Circuit 2 fragments containing
templates, modules, constants, accessories, rules and waivers. Circuit 1 remains
supported without the new declarations. YAML
inputs are retired. The shared device catalogue remains JSON; internal circuit
and delivery schemas remain version 2. Existing version 1 packages remain
readable by `verify`.

## Declarations and values

```text
circuit 1;
board my_board {
    id = "my-board";
    library = "standard@1";
    top = board;
}
template resistor_0603 {
    device = "generic.resistor";
    package = "resistor_0603";
    assembly = fitted;
    properties { tolerance = 1 %; power_rating = 0.1 W; }
}
module board {
    part reset_pullup using resistor_0603 {
        id = "reset-pullup";
        identity_namespace = "";
        properties { resistance = 10 kohm; }
    }
    nc reset_pullup.A, reset_pullup.B;
}
```

The name after `board` supplies `<name>.tel`; `id` identifies the board independently
of filenames. Generated `components.json`, BOM, PINOUT and FOOTPRINTS are outputs,
not inputs. Neither assigned references nor project-local component definitions
are accepted.

Source is UTF-8, with `//` comments and insignificant whitespace. Braces delimit
blocks; assignments and connections end with `;`. Double-quoted strings use JSON
escapes. Bare words are strings, except `true`, `false` and `null`. Numbers may use
scientific notation; quantities need an explicit unit (`10 kohm`, `0.25 pF`,
`1 %`). Compound or unusual strings can always be quoted. Lists use commas:
`[pin(mcu.PA0), pin(mcu.PA1)]`. Property blocks accept `key = value;`; `properties
{ ... }` and `properties = { ... };` are equivalent. Duplicate declarations,
unknown structural fields, nonfinite numbers and nesting beyond 64 levels fail.
There is no executable code or implicit connectivity. Blocks and declarations may
refer forward to templates/modules. Circuit 2 adds bounded expressions and explicit
file dependencies, described below. Quote names containing hyphens or slashes in
Circuit 2; those characters are arithmetic operators outside strings.

Templates are file-level, single-layer declarations selected explicitly with
`part name using template_name`. They may supply device, package, assembly,
properties, electrical models and description, but never identity. Instances
replace scalar fields and override individual top-level property/electrical keys;
nested values replace as a whole. Library-fixed specifications still cannot be
overridden. Diagnostics include instance and template locations. There are no
module-wide defaults or template inheritance.

## Circuit 2 reuse and expressions

Use `circuit 2;` in the entrypoint and every included fragment. A fragment cannot
contain a `board` declaration. Includes are explicit, quoted, relative `.circuit`
paths, resolved beside the including file; `../` is allowed. There is no search
path, wildcard, network fetch or conditional inclusion.

```text
circuit 2;
include "common.circuit";           // import exported names directly
include "analog/divider.circuit" as analog;
const PULLUP: resistance = 10 kohm;
const CURRENT: current = 3.3 V / $PULLUP;
group DEBUG = [pin(target.mcu.PA13), pin(target.mcu.PA14)];
```

An alias prefixes exported constants/templates/modules/groups (`$analog.R`,
`analog.divider`). Definitions keep their own lexical environment: importing a
module never redirects its internal template or constant names to the caller.
Files load once per real path; declarations/rules mount once per namespace, so
shared diamond dependencies are safe. Different declarations with the same
exported name are errors. Include cycles, missing files and parse failures report
the include chain. Every dependency's raw SHA-256 enters the build inputs.
Includes and constant dependencies are limited to 64 levels.

Constants and module parameters have explicit types: `number`, `integer`,
`boolean`, `string`, `group`, `ratio`, `resistance`, `capacitance`, `inductance`,
`voltage`, `current`, `power`, `frequency`, `length`. `$name` references a binding.
`group NAME = [...]` is shorthand for a typed, ordered list of unique references
of one kind. Groups select rule objects; they never create electrical connections.
Global groups use board-relative paths; module groups use instance-relative paths.

```text
module divider(upper: resistance = 10 kohm,
               lower: resistance = $upper / 2) {
    ports IN, OUT, GND;
    part hi using resistor { id = "upper"; properties { resistance = $upper; } }
    part lo using resistor { id = "lower"; properties { resistance = $lower; } }
    net IN = hi.A, port.IN;
    net OUT = hi.B, lo.A, port.OUT;
    net GND = lo.B, port.GND;
    group ROOTS = [pin(hi.A), pin(hi.B), pin(lo.B)];
    rules { rule SEPARATE isolated_all $ROOTS; }
}
// In a parent module, with all three ports connected:
// instance sense: divider(upper = 20 kohm) { id = "sense-stable"; }
```

Arguments are named, validated and evaluated in the caller; defaults may refer
to other parameters or lexical constants. Missing required arguments, unknown
arguments, type mismatches and dependency cycles fail. Parameters may supply
specifications, device/package/assembly values and positive integer bus widths.
They cannot generate names, IDs, instance counts, connection lists or conditional
parts. No loops, functions, interpolation, implicit nets or external code run.

Arithmetic uses 28-digit Decimal values with `+ - * /`, unary signs and parentheses;
multiplication/division precede addition/subtraction. Units are checked dimensionally:
`10 V / 2 mA` yields resistance, `2 V * 10 mA` yields power, and adding resistance
to voltage fails. Ratios accept `%` and `ppm`; `integer` rejects fractional values.
Division by zero, unsupported final compound dimensions and excessive expression
depth fail with source locations. Expressions are calculated before schema validation.

A module may contain one `rules` block with local models and groups. Typed references
and selector patterns bind relative to each instance. Rule IDs use immutable
instance ID paths, so repeated modules get independent diagnostics and a renamed
functional instance preserves its rule IDs. File-global rules in aliases are
prefixed by the alias. Keep stable IDs unchanged when splitting files.

## Shared libraries

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

Optional `rating_conditions` describes AC/DC, pulse duty, temperature and
thermal limits; it is carried into the component inventory and BOM. A scalar
rating alone does not encode these conditions.

The authoritative profiles are in `properties.py`. Missing required properties
produce non-waivable `PROPERTY.REQUIRED` errors, including DNP parts. No guessed
ratings or `unknown` placeholders can pass. `electrical` remains the input for
operating conditions and electrical rule models; it cannot conflict with a
resolved resistance, assembly state or default switch state. Declaring ratings
does not validate undeclared working voltage, dissipation or derating.

`assembly` is required (`fitted` or `dnp`). DNP parts retain physical pads and
connections. Board-level `accessory` declarations contain an ID, `description`, positive
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

Declare scalar ports with `ports GND, RESET;`, buses with `ports DATA[4];`, and
children with `instance left: endpoint { id = "left"; }`. A connection is
`net DATA = port.DATA, chip.group(DATA);`. Endpoints are `part.pin`,
`part.group(group_name)`, `port.name`, or `instance.port`. Part and instance
names must be distinct; `port` is reserved for the local port namespace.
Group members are ordered logical names defined by the catalogue. All endpoint
widths must match; no implicit broadcast, reversal or global power-net merging
occurs. Use `nc chip.SPARE;` (or a local pin group) for unconnected physical pins.
Every physical pin must be connected or explicitly NC; duplicates and NC conflicts
fail. Ports connect on both sides; distinct same-scope nets cannot be shorted.
Optional net models follow the endpoints:
`net VDD = chip.VDD, port.VDD { electrical { role = power; } };`.

The canonical net name is the shallowest participating path, then lexical order.
Bus bits append `[i]`. `net_aliases` preserves other names. Hierarchy is bounded
to 64 levels and 100,000 expanded instances.

Rules, supplemental models and waivers live in the entrypoint or included fragments. Typed functional
references such as `pin(target.mcu.PA13)`, `part(target.mcu)` and `net(VDD)` resolve
after hierarchy expansion. Slash-separated instance paths are also accepted.
A renamed functional path must be updated in its rule references; stale references
fail with source positions. Ordinary strings are never interpreted as references.
See [rules.md](rules.md) for rules, selectors and waivers.

Use `accessory demo_shunt { description = "removable shunt"; quantity = 1;
assembly = fitted; }` for a BOM-only item without physical pads.

## Migrating existing designs

Merge the former board/rules/waiver input into one `.circuit` file. Preserve board
ID, part and instance IDs, explicit identity namespaces, library revision and
`design.lock.json`. Replace rule identity strings with typed functional references;
retain independent expected connections rather than deriving rules from actual
nets. Extract only genuinely shared known attributes into templates. Missing
specifications remain errors. The bundled NUCLEO migration retains 89 parts,
312 pads, 82 nets and 16 NC pins. Circuit 2 combines its pairwise isolation checks
into one aggregate rule: 511 passing results and 10 warnings. Required specifications
are now complete using documented project selections; see the board README for
official BOM differences.

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
