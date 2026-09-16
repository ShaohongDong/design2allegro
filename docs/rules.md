# Electrical rule reference

Version 2 designs address stable part identities and logical pin names, such as
`target/mcu.PA13`, never generated `U1.23` references. The rule language itself
retains `version: 1`. Procurement property errors are non-waivable and are
reported separately from electrical operating-condition checks.

Each rule uses `id`, `kind`, `scope` or `selector`, and `params`. Unknown
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
| `voltage` | `logic`, `source` |
| `power` | `allowed_sources` |
| `pull` | `direction`, `max`, `min`, `rail` |
| `state` | `active_level`, `initial_state`, `pull`, `source` |
| `bank` | `bank`, `capability`, `standards`, `vcco`, `vref` |
| `differential` | `allow_swap`, `peer`, `targets` |
| `interface` | `endpoints`, `protocol`, `pulls` |
| `ddr` | `bit_maps`, `byte_map`, `control_pairs`, `controller`, `memory` |
| `path` | `target`, `via` |

Interface protocols are UART, SPI, I2C and JTAG (lowercase values).
DDR rules use ordered `dq` lists, `dqs_p`, `dqs_n` and optional `dm` in each
controller/memory group; swapping data bits requires an explicit allowed map.
See `tests/fixtures/fpga_soc/rules.yaml` and `tests/parser/test_interfaces.py` for
complete declarations, and `tests/parser/test_rules.py` for voltage, power,
differential and bank examples.

ERC always evaluates pin-type contention and drive. A declared rule FAIL with
ERROR severity or a required UNKNOWN blocks export. Warnings remain visible.
No rules means ERC-only validation, not complete device-specific coverage.
The report lists unmodeled and unscoped pins explicitly.

`attribute` resolves metadata on pins, parts or nets according to the scoped object.
Assembly states are checked as attributes; they do not merge physical PCB nets.
