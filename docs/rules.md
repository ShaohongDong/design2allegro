# Electrical rule reference

Place one `rules { ... }` block per file. Circuit 2 also allows one per module.
Module references/selectors are instance-relative, and rule IDs use the instance
ID path. Rule IDs remain stable;
rule expectations are written independently of the design connections.

```text
rules {
    description = "Static connectivity and assembly checks";
    models {
        parts { part(target.mcu) { bank = B0; } }
        nets { net(VDD) { domain = CORE; } }
    }
    rule SWD connected [pin(target.mcu.PA13)] {
        targets = [pin(debug.mcu.PA13)];
    }
    rule MCU_FITTED attribute [part(target.mcu)] { name = assembly; equals = fitted; }
    rule GPIO_PRESENT required {
        selector { entity = pins; pattern = "target/mcu.PA*"; }
    }
}
waiver {
    rule = OPTIONAL_PIN;
    object = pin(target.mcu.PA0);
    reason = "Reserved for a later assembly";
    owner = "board-team";
    expires = "2027-01-01";
}
```

Use `pin(functional.path.LOGICAL_PIN)`, `part(functional.path)` and `net(NAME)`
for object references, including nested parameters and model keys. Quotes inside
the parentheses support unusual names, e.g. `pin("target.mcu.1")`.
Net references resolve aliases and bus bits such as `net(DATA[0])`. Functional
paths are converted to stable IDs before checking; assigned `U1`/`R1` references
are never input identities. Plain strings, including attribute values, remain
literal data. Selectors match **slash-separated functional paths** with shell-style
patterns; entities are `parts`, `pins` or `nets` (canonical net names).
A selector matching nothing retains the existing required-UNKNOWN blocking behavior.

A rule is `rule ID KIND [scope...] { parameter = value; }`. Omit the scope list
when using `selector`. Parameterless rules may end directly with `;`.
`required` checks connected physical pins; it is not an existence check for parts
or nets. Attribute checks can target pins, parts or nets.
`required`, `severity`, `applicable` and `selector` are rule options;
`origin` stores a descriptive source string. The `source` keyword is an electrical
parameter (e.g. voltage source), so it cannot be confused with `origin`.
Nested lists/maps express interface and DDR models. Circuit 2 permits typed
constants and arithmetic in values.

Internally each rule retains `id`, `kind`, `scope` or `selector`, and `params`. Unknown
parameters are rejected. Missing evidence for required checks blocks delivery.
`models` supplies declared pin, part and net electrical properties; no datasheet
values are inferred. Units are mandatory for physical quantities.

| Kind | Accepted parameter keys |
| --- | --- |
| `required` | (none) |
| `no_connect` | (none) |
| `drive` | `arbitration`, `pull` |
| `capability` | `capability` |
| `attribute` | `allowed`, `equals`, `name` |
| `connected` | `targets` |
| `isolated` | `targets` |
| `isolated_all` (Circuit 2) | (none) |
| `voltage` | `logic`, `source` |
| `power` | `allowed_sources` |
| `pull` | `direction`, `max`, `min`, `rail` |
| `state` | `active_level`, `initial_state`, `pull`, `source` |
| `bank` | `bank`, `capability`, `standards`, `vcco`, `vref` |
| `differential` | `allow_swap`, `peer`, `targets` |
| `interface` | `endpoints`, `protocol`, `pulls` |
| `ddr` | `bit_maps`, `byte_map`, `control_pairs`, `controller`, `memory` |
| `path` | `target`, `via` |

`isolated_all` takes at least two explicit representative connected pins (a scope
list or named group), one for each expected separate network. It emits one
aggregate result and lists every conflicting net and its members. NC pins,
duplicates, parts/nets and fewer than two members are configuration errors.
The representative list must be authored independently of actual connectivity;
generating it from the current nets would hide accidental shorts. NUCLEO uses
82 authored representatives, preserving all 3,321 pairwise separation expectations.

Interface protocols are UART, SPI, I2C and JTAG (lowercase values).
DDR rules use ordered `dq` lists, `dqs_p`, `dqs_n` and optional `dm` in each
controller/memory group; swapping data bits requires an explicit allowed map.
See `tests/fixtures/fpga_soc/board.circuit` and `tests/parser/test_interfaces.py` for
complete declarations, and `tests/parser/test_rules.py` for voltage, power,
differential and bank examples.

ERC always evaluates pin-type contention and drive. A declared rule FAIL with
ERROR severity or a required UNKNOWN blocks export. Warnings remain visible.
No rules means ERC-only validation, not complete device-specific coverage.
The report lists unmodeled and unscoped pins explicitly.

`attribute` resolves metadata on pins, parts or nets according to the scoped object.
Assembly states are checked as attributes; they do not merge physical PCB nets.
