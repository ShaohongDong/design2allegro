# Sources and interpretation

Retrieved/checked 2026-09-19. `sources.json` records hashes of files used locally;
large source PDFs remain in `docs/` or the research build directory and are not
required to compile this board. Package CSV/TXT retain the manufacturer's notices.

| Source | Use and limits |
| --- | --- |
| [User reference](../../../docs/ZW_XCZU15EG_SCH_V2.0.pdf), 35 pages | FPGA pp.2–9; PS memory p.10; PL DDR4 p.11; storage p.12; other clock/power/debug pages. Connectivity is selectively rebuilt, not a lossless conversion. |
| [AMD Zynq UltraScale+ package files](https://www.amd.com/en/developer/resources/adaptive-socs-and-fpgas/package-pinout-files/zynq-ultrascale-plus-package-device-pinout-files.html) / [ZIP](https://download.amd.com/adaptive-socs-and-fpgas/developer/adaptive-socs-and-fpgas/package-pinout-files/zuppackages/zupall.zip) | `xczu15egffvb1156pkg.csv/.txt`: complete 1156-ball inventory; independently compared with installed Vivado 2025.2. |
| [UG1085 v2.5](https://docs.amd.com/api/khub/documents/xzMsp_c5sG9J6A3u7NkJYQ/content) | PS boot modes and MIO functions. Research filename `ug1075.pdf` is a historical download filename; the document inside is **UG1085**, not UG1075. |
| [UG583](https://docs.amd.com/r/en-US/ug583-ultrascale-pcb-design) | PS/PL power, clock, reset, unused pins, DDR PCB requirements. |
| [DS925 PS sequencing](https://docs.amd.com/r/en-US/ds925-zynq-ultrascale-plus/PS-Power-On/Off-Power-Supply-Sequencing) | Supply ordering; PS_POR_B remains asserted until power is stable. Dynamic waveforms are not verified. |
| [UG578](https://docs.amd.com/api/khub/documents/BY7rRWkUQliMvNvosLhSZA/content) | Unused GTY receiver, reference clock, calibration and unpowered supply guidance. |
| [DS593](https://docs.amd.com/api/khub/documents/TI9ts12CeuAeBtQpR7HWBw/content), Fig.14 | 2 mm 14-pin JTAG connector mapping; NC/HALT not used. |
| Micron DDR4: reference p.11 and Vivado 2025.2 DDR4 IP model `MT40A512M16LY-075` | Physical 96-ball x16 map from reference; timing/capacity model from AMD IP. Exact selected MPN datasheet and procurement lifecycle must be rechecked before PCB release; no successful vendor DDR PDF download is represented as evidence. |
| [Micron eMMC 4.51 IT datasheet mirror](https://d.myirtech.com/Z-turn-Lite/public/DVD/01-Document/Datasheet/Peripheral/EMMC_4GB_8GB.pdf), `emmc_ps8210_v451_80s_153b_it.pdf`, Rev E June 2014 | Primary-authored IT AM ball table; web-indexed copy consulted. Local binary download was unavailable. |
| [Micron AM package WT datasheet mirror](https://assets.componentsense.com/images/datasheets/1508418172774_MTFC8GACAAAM-1M-WT-Micron.pdf), Rev F June 2014 | Downloaded manufacturer's 4/8GB AM 153-ball table, cross-checking omissions. Different temperature/order suffix: not proof of the full IT ordering specification. |
| [Micron obsolete eMMC catalog](https://www.micron.com/products/obsolete/obsolete-emmc/part-catalog) | MTFC8GACAAAM-4M IT obsolete status, 64 Gbit and package identity. |
| Winbond W25Q256JW and reference p.12 | WSON8 8×6 mapping, 1.8 V dual parallel flash. Exact package/order suffix remains a procurement review item. |
| [TPS543C20A](https://www.ti.com/lit/ds/symlink/tps543c20a.pdf) | Core buck pinning, standalone mode, VSEL/SS/RT/RAMP/ILIM programming. |
| [TPS568215](https://www.ti.com/lit/ds/symlink/tps568215.pdf) | Six auxiliary buck regulators: physical pins, feedback, MODE, EN/PG behavior. |
| [TPS748](https://www.ti.com/lit/ds/symlink/tps74801.pdf) | PSPLL regulator pins, bias/dropout and feedback. Two OUT pads share one internal node; OUT_10 is passive in ERC to avoid a false independent-driver conflict. |
| [TPS51200](https://www.ti.com/lit/ds/symlink/tps51200.pdf) | VTT/VREF regulator pinning, VIN/VLDOIN, EN constrained to VIN. |
| [TPS3808](https://www.ti.com/lit/ds/symlink/tps3808.pdf) | Supervisor pinning, adjustable sense threshold, open-drain reset and CT delay. |
| [Nexperia BAT54](https://assets.nexperia.com/documents/data-sheet/BAT54.pdf), table 2 | Pin 1 anode, 2 NC, 3 cathode. |
| [Abracon AK3A](https://abracon.com/datasheets/AK3A.pdf) | `AK3ADAF1-200.0000T`: LVDS, 3.3 V, industrial 25 ppm, OE pin1; 6-pad configuration 1. |
| [Abracon ASE](https://abracon.com/Oscillators/ASEseries.pdf) | PS CMOS 33.333 MHz oscillator, four pads. |
| [Abracon ABS07](https://abracon.com/Resonators/ABS07.pdf) | 32.768 kHz tuning-fork crystal; actual stray capacitance requires PCB measurement. |

Generic R/C/L, connectors, switch, LED and testpads carry explicit specifications
and footprint identifiers, not invented manufacturer order codes. Select actual
parts and verify DC bias, current/thermal derating and geometry before purchasing.

`design_inventory.json` is an authoring manifest, not measured evidence.
`netlist.expected.json` freezes it in physical form using only the lock's reference
assignment; it was not copied from the exported Telesis or compiler connectivity.
`rules.circuit` and board tests separately check functional requirements, exact
FPGA pin coverage, reserved pins and representative fault injection.
