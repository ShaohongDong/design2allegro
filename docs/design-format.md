# Design format, version 1

Inputs are UTF-8 YAML `.yaml` or `.yml` files. All keys must be strings. Quote
physical numbers (`"1"`, `"08"`), values and numeric logical names. Only lowercase
`true` and `false` are implicit booleans; dates remain strings. Duplicate keys,
unknown structural fields, aliases, merge keys, custom tags, non-finite numbers
and non-JSON metadata are rejected. YAML is never executed or interpolated.

## Files and component libraries

A design has `version: 1`, `libraries` (local paths relative to the design file),
`modules`, `top`, and `references`. Optional `rules` and `waivers` are inline data
or paths to YAML files relative to that same design. No network loading or Python
callbacks are supported. Library files contain `version: 1` and `components`.
Component names must be unique across the project's libraries.

```yaml
# components.yaml
version: 1
components:
  RESISTOR:
    package: R0805
    value: "4.7k"
    pins:
      "1": {name: A, type: PASSIVE}
      "2": {name: B, type: PASSIVE}
    electrical: {role: resistor, resistance: "4.7 kohm"}
```

The package must match a supplied Allegro library symbol. Pins are keyed by
physical terminal numbers (ASCII letters, digits, underscores), with unique
logical `name` and a required `type`. Supported types are INPUT, OUTPUT, BIDIR,
TRISTATE, PASSIVE, UNSPEC, PWRIN, PWROUT, OPENCOLL, OPENEMIT, PULLUP, PULLDN,
NOCONNECT and FREE. Optional `electrical` maps may appear on components and pins.
A component's `groups` maps each group name to an ordered, unique list of physical
pin numbers, e.g. `DATA: ["A1", "A2", "A3", "A4"]`.

## Modules, nets and endpoints

```yaml
version: 1
libraries: [components.yaml]
top: board
references: {left: R1, right: R2}
modules:
  board:
    parts:
      left: {component: RESISTOR}
      right: {component: RESISTOR, value: "10k"}
    nets:
      MID:
        endpoints:
          - {part: left, pin: B}
          - {part: right, pin: A}
    nc:
      - {part: left, pin: A}
      - {part: right, pin: B}
```

Module names and local part, instance, port, group and net names use
`[A-Za-z_][A-Za-z0-9_]*`. Part and child instance names cannot overlap.
`parts` entries require `component` and optionally set `value` or `electrical`.
Electrical declarations are combined by intersection, never silently overridden.
To change a resistor value and its modeled resistance, define a matching component
variant instead of conflicting electrical declarations.

A module may declare `ports: {data: {width: 4}}` and
`instances: {child: {module: endpoint}}`. A net has `endpoints` and optional
`electrical` metadata. Exactly four endpoint forms are accepted:

| Form | Meaning |
| --- | --- |
| `{part: chip, pin: CLK}` | Unique logical pin name in the component library |
| `{part: chip, group: DATA}` | Ordered physical pin group in the library |
| `{port: data}` | Current module's port |
| `{instance: child, port: data}` | Immediate child's port |

All endpoints of a net must have equal width. Scalar pins have width one. Bus
position `i` connects to position `i`; buses do not broadcast or reverse
implicitly. A width-N net becomes `NAME[0]` through `NAME[N-1]`; width one uses
`NAME`. Use separate scalar ports when individual bit routing is needed.

Every module port must be connected internally; every child port must be connected
in its parent. Top-level ports may describe board boundaries but still require
physical pins inside the design. Every physical pin must appear on a net or in
`nc`; NC accepts only local part/pin or part/group endpoints. Repeated endpoints,
including repeated NC, are errors. A one-pin net is legal with an ERC warning;
a network containing no physical pins is invalid.

Module nesting is limited to 64 levels and expansion to 100,000 instances.
Distinct nets in the same scope cannot become shorted through child ports.
Canonical net names must not collide with board references.

The compiler merges parent/child nets through ports, keeping local nets isolated
between instances. The canonical name is the shallowest participating network
path, with lexical ordering breaking ties. `net_aliases` in `circuit.json` records
all local-to-canonical mappings. There are no implicit global power nets.

## Board references and electrical rules

References map complete instance/part paths (without the top module's name) to
board references, e.g. `fpga/endpoint/chip: U1`. Every expanded physical part needs
exactly one mapping. References match `[A-Za-z][A-Za-z0-9_]*`, are normalized to
uppercase, and must be unique ignoring case. Pin numbers remain as declared.

Rules use `version: 1`, optional `description` and `models`, and a `rules` list:

```yaml
version: 1
rules:
  - id: CLOCK
    kind: connected
    scope: [U1.8]
    params: {targets: [U2.8]}
```

A rule requires `id`, `kind` and either `scope` or
`selector: {entity: pins, pattern: "U1.*"}`. Entities are pins, parts or nets.
References in rules use board IDs (`U1.8`) or canonical net names (`DATA[0]`).
Optional `required` defaults true, `severity` defaults ERROR, and `applicable`
defaults true. `models` supplements electrical declarations by entity and ID.
Use explicit units such as `"1.8 V"` or `"4.7 kohm"`.
See [the rule reference](rules.md) for kinds and accepted parameters.

Waivers are a list of exact `rule`, `object`, `reason`, and `owner` records, with
optional ISO `expires`. Expired, duplicate, unmatched and wildcard waivers fail.
Configuration errors cannot be waived. Optional rules omitted entirely do not
block normal ERC-only designs; explicitly required rules with missing evidence do.

## Diagnostics and delivery

`check`, `build` and `verify` accept `--json`. Exit codes are 0 for success, 2 for
invalid inputs or failed checks, and 1 for I/O or internal execution failure.
Semantic errors include a source location and module path where available.
Failed checking produces diagnostics and never replaces an existing package.
Only directories managed by this tool, with no extra user files, can be replaced.

Python callers can use `load_design(path)`, `compile_design(loaded)`,
`check_design(compiled)`, and `export_design(compiled, output_dir)`.
The compiled electrical digest excludes source positions and input hashes;
`inputs.json` preserves exact input hashes and `circuit.json` preserves provenance.
Do not treat an offline PASS as proof of physical correctness or real Allegro import.

## Board names and netlist filenames

For `board.yaml` or `board.yml`, the enclosing directory is the board name.
For other design filenames, use the filename stem. The compiled snapshot records
this as `name`; export produces `<name>.tel`, independently of the output directory.
Use ASCII letters, digits, `_`, `-` and `.`, starting with a letter, digit or `_`.
Unsafe names fail export without replacing existing output. Existing packages
containing `design.tel` remain readable; rebuilding replaces managed old output
with the board-named netlist. The YAML schema and CLI arguments are unchanged.
