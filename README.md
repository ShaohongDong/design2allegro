# design2allegro

**用代码设计电路，让硬件开发更快走向 Allegro PCB Layout。**

**Design circuits as code. Move faster toward PCB layout in Allegro.**

[中文](#中文) · [English](#english)

## 中文

### 为什么做这个项目

design2allegro 的设计初衷是**快速完成原理图中的电路设计，导出网表交给
Allegro 进行 PCB 布局布线，缩短硬件开发周期，并推动开发流程自动化**。

用可版本管理的文本描述器件、连接和设计规则，可以让重复电路成为可复用模块，
让设计变更进入代码审查，让网表、BOM 和引脚文档随设计一起更新。
硬件工程师可以专注于电路与选型，开发者可以通过脚本和自动检查减少重复工作。

当前工程是一个 Python 实现的 **Circuit 语言编译器**：使用 `.circuit` 文件
表达原理图中的电路内容，生成 Allegro Telesis 交付包，并提供浏览器连接拓扑审查。
目前没有传统图形原理图绘制功能。

```text
电路设计 → Circuit 描述与模块复用
         → 编译、规格校验与电气规则检查
         → Telesis 网表 + BOM + 引脚/封装文档
         → 独立回读验证 + 浏览器人工审查
         → 交给 Allegro，配合封装库进行 PCB Layout
```

最后一步是项目要衔接的工作流；**实际 Allegro 导入尚未验证**。

### 当前可以做什么

| 能力 | 对开发流程的帮助 |
| --- | --- |
| Circuit 1/2 电路描述 | 显式表达层级、端口、总线和 NC，便于追踪连接变更 |
| Circuit 2 模块复用 | 支持文件引用、类型常量、参数化模块和模块内规则，减少重复描述 |
| 规格与电气检查 | 校验单位、必填规格和声明的规则，输出带源码位置的诊断 |
| 稳定身份与自动位号 | 功能名与位号分离；保留已有位号，已删除位号保持预留 |
| 版本化共享器件库 | 统一逻辑引脚、物理焊盘映射、允许的封装和固定型号规格 |
| 一致的交付产物 | 从同一冻结电路快照生成网表、BOM、引脚及封装文档 |
| 独立回读验证 | 解析导出的网表和器件文件，对照交付快照检查一致性 |
| 浏览器人工审查 | 查看元件、网络、物理引脚、规格和诊断，保存人工状态与批注 |

新增 [XCZU15EG 最小系统工程](schematics/xczu15eg_minimal/README.md)：板载 PS/PL DDR4、QSPI/eMMC、电源与调试，附物理网表契约和 Vivado 引脚验证脚本。

当前输入为 Circuit 1/2，YAML 输入已退役。Allegro Telesis 是唯一支持的导出格式。
人工审查记录保存在交付包之外，不改变电路或自动检查结论。

### 快速上手

需要 Linux 和 Python 3.12+。以下步骤用于搭建开发环境；先安装 Python 3.12
及其 venv 支持，再从仓库根目录执行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

.venv/bin/design2allegro check schematics/nucleo_l432kc/board.circuit
.venv/bin/design2allegro build schematics/nucleo_l432kc/board.circuit -o build/parser/nucleo_l432kc
.venv/bin/design2allegro verify build/parser/nucleo_l432kc
.venv/bin/design2allegro review build/parser/nucleo_l432kc
```

`review` 启动本地服务并尝试打开浏览器，按 Ctrl+C 停止。界面资源随包提供，
运行时无需 Node 或 CDN。查看 [人工审查指南](docs/review.md) 了解筛选、批注和记录管理。

生成的网表位于 `build/parser/nucleo_l432kc/nucleo_l432kc.tel`。
交付目录还包含 `devices/`、`components.json`、`BOM.md`、`BOM.csv`、
`PINOUT.md`、`FOOTPRINTS.md`、`references.json`、电路及来源快照、检查报告和哈希清单。
交接时保留整个目录。

`build` 会维护设计旁的 `design.lock.json`，请将它与电路文件一起提交，保留位号历史。
`check` 不写入位号状态。

### 从真实电路示例开始

[NUCLEO-L432KC 示例](schematics/nucleo_l432kc/README.md) 将 ST 官方 MB1180 电路
转录为 Circuit 2，按接口、电源、ST-LINK、目标 MCU 和规则拆分文件。
示例文档记录了 **89 个器件、312 个物理焊盘、82 个网络和 16 个 NC 引脚**，
使用 `standard@2` 器件库。

这是本项目的采购选型版本；来源、替代器件及与官方 BOM 的差异都有记录。
示例文档列出了保留的 10 条 ERC 警告及其解释。
`tests/fixtures/` 中的合成电路用于编译器回归测试。

### 接入自动化开发流程

`check`、`build` 和 `verify` 都支持 `--json` 输出，可由脚本或 CI 调用。
例如，在电路变更后执行：

```sh
.venv/bin/design2allegro check schematics/nucleo_l432kc/board.circuit --json
```

命令退出码为 `0`（成功）、`2`（输入、设计或交付包校验失败）、`1`（执行失败）。
这些命令为自动检查、产物生成和交付验证提供集成入口；完整 CI 流水线需要另行配置。

自动检查及回读验证属于离线证据。导入 Allegro 需要匹配的封装符号和 padstack；
本工具不生成 `.psm`、padstack、PCB 几何或 Allegro 导入约束。
器件额定值不能单独证明工作裕量；PCB 布局、制造和硬件验收仍需完成各自的验证。
现有 v1 交付包仍支持只读验证，浏览器审查面向 v2 交付包。

### 开发与文档

运行代码位于 `src/design2allegro/`，内核测试位于 `tests/parser/`，
完整电路项目位于 `schematics/`。内核回归使用合成输入，板级验证单独运行。

```sh
make test            # 编译、规则、位号、CLI 与交付回归
# 首次运行浏览器测试前安装 Chromium：
.venv/bin/python -m playwright install chromium
make test-ui         # 浏览器审查交互测试
make example         # 构建并验证合成示例与 NUCLEO 电路
make benchmark       # 测量 10,000 个物理引脚的处理时间与内存
make build           # 构建 wheel
make verify-package  # 在独立环境中验证 wheel 安装与命令
make clean-preview   # 预览当前 build/parser/ 清理范围
```

Make 默认使用 `.venv/bin/python`，可用 `PYTHON=/path/to/python` 覆盖。
保留历史 `build/`、`dist/`、`.venv/` 和迁移备份；当前清理范围仅为 `build/parser/`。
运行时不依赖已退役的 SKiDL API 或原生引擎。

- [Circuit 输入格式](docs/design-format.md)
- [电气规则](docs/rules.md)
- [人工审查](docs/review.md)
- [开发与验证](docs/development.md)
- [MIT 许可证](LICENSE)

## English

### Why this project exists

design2allegro aims to **accelerate schematic circuit design, export netlists for
PCB layout in Allegro, and shorten hardware development cycles through automation**.

Describing components, connections and design rules as version-controlled text
makes repeated circuits reusable, brings design changes into code review, and
keeps netlists, BOMs and pin documentation in step. Hardware engineers can focus
on circuits and part selection while scripts and automated checks reduce repetitive work.

The current implementation is a **Circuit language compiler written in Python**.
It represents schematic circuit content in `.circuit` files, generates Allegro
Telesis delivery packages, and provides browser-based connectivity review.
It does not currently provide traditional graphical schematic drawing.

```text
Circuit design → Circuit source and reusable modules
               → Compilation, specification validation and electrical checks
               → Telesis netlist + BOM + pin/footprint documentation
               → Independent readback verification + human review in a browser
               → Handoff to Allegro with footprint libraries for PCB layout
```

The final step is the intended downstream workflow; **actual Allegro import remains unverified**.

### What works today

| Capability | How it helps |
| --- | --- |
| Circuit 1/2 descriptions | Explicit hierarchy, ports, buses and NC declarations make connectivity changes traceable |
| Circuit 2 reuse | Includes, typed constants, parameterized modules and local rules reduce repeated descriptions |
| Specification and electrical checks | Units, mandatory specifications and declared rules produce source-located diagnostics |
| Stable identities and automatic references | Functional names stay separate from references; existing numbers persist and removed numbers remain reserved |
| Versioned shared device catalogue | Logical pins, physical pad mappings, allowed packages and fixed model specifications have one definition |
| Consistent delivery artifacts | Netlists, BOMs and pin/footprint documentation come from one frozen circuit snapshot |
| Independent readback verification | Exported netlists and device files are parsed and checked against the delivered snapshot |
| Browser-based human review | Components, nets, physical pins, specifications and diagnostics can be inspected and annotated |

Circuit 1/2 are the current inputs; YAML input is retired. Allegro Telesis is the
only supported export format. Human review records live outside the delivery
package and do not change the circuit or automated check results.

### Quick start

Linux and Python 3.12+ are required. To set up a development environment, first
install Python 3.12 with venv support, then run from the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'

.venv/bin/design2allegro check schematics/nucleo_l432kc/board.circuit
.venv/bin/design2allegro build schematics/nucleo_l432kc/board.circuit -o build/parser/nucleo_l432kc
.venv/bin/design2allegro verify build/parser/nucleo_l432kc
.venv/bin/design2allegro review build/parser/nucleo_l432kc
```

`review` starts a local server and attempts to open your browser; press Ctrl+C to
stop it. UI assets ship with the package, so no Node or CDN is needed at runtime.
See the [review guide](docs/review.md) for filtering, annotations and record management.

The netlist is `build/parser/nucleo_l432kc/nucleo_l432kc.tel`. The delivery also
includes `devices/`, `components.json`, `BOM.md`, `BOM.csv`, `PINOUT.md`,
`FOOTPRINTS.md`, `references.json`, circuit and provenance snapshots, check
reports and a hashed manifest. Keep the entire directory for handoff.

`build` maintains `design.lock.json` beside the design. Commit it with your circuit
files to preserve reference history. `check` does not write annotation state.

### Start with a real circuit example

The [NUCLEO-L432KC example](schematics/nucleo_l432kc/README.md) transcribes ST's
official MB1180 circuit into Circuit 2, with separate interfaces, power, ST-LINK,
target MCU and rule files. Its documentation records **89 parts, 312 physical pads,
82 nets and 16 NC pins**, using the `standard@2` catalogue.

This is the project's procurement-selection variant, with documented sources,
substitutions and differences from the official BOM. The example documentation
lists 10 retained ERC warnings and their explanations. Synthetic circuits under
`tests/fixtures/` serve compiler regression testing.

### Build an automated workflow

`check`, `build` and `verify` support `--json` output for scripts and CI.
For example, after a circuit change:

```sh
.venv/bin/design2allegro check schematics/nucleo_l432kc/board.circuit --json
```

Exit codes are `0` for success, `2` for invalid input, design or delivery package,
and `1` for execution failure. These commands provide integration points for
automated checks, artifact generation and delivery verification; a complete CI
pipeline needs separate configuration.

Automated checks and readback provide offline evidence. Allegro import requires
matching package symbols and padstacks; this tool does not generate `.psm`,
padstacks, PCB geometry or imported Allegro constraints. Component ratings alone
do not prove operating margins. PCB layout, manufacturing and hardware acceptance
still require their own validation. Existing v1 delivery packages remain readable
by `verify`; browser review supports v2 delivery packages.

### Development and documentation

Runtime code lives in `src/design2allegro/`, kernel tests in `tests/parser/`, and
complete circuit projects in `schematics/`. Kernel regressions use synthetic
inputs; board validation runs separately.

```sh
make test            # Compiler, rules, references, CLI and delivery regressions
# Install Chromium before the first browser test run:
.venv/bin/python -m playwright install chromium
make test-ui         # Browser review interaction tests
make example         # Build and verify the synthetic fixture and NUCLEO circuit
make benchmark       # Measure time and memory for 10,000 physical pins
make build           # Build a wheel
make verify-package  # Validate wheel installation and commands in isolation
make clean-preview   # Preview cleanup of current build/parser/ outputs
```

Make uses `.venv/bin/python` by default; override it with `PYTHON=/path/to/python`.
Preserve historical `build/`, `dist/`, `.venv/` and migration backups. Current
cleanup targets only `build/parser/`. The retired SKiDL API and native engine
are not runtime dependencies.

- [Circuit input format](docs/design-format.md)
- [Electrical rules](docs/rules.md)
- [Human review](docs/review.md)
- [Development and verification](docs/development.md)
- [MIT license](LICENSE)
