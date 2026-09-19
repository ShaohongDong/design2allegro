# XCZU15EG 最小系统核心板

依据 `docs/ZW_XCZU15EG_SCH_V2.0.pdf` 重建的可编辑 Circuit 2 电路工程。
板子尺寸不限制，不设板对板连接器，不引出以太网、USB、PCIe、视频、普通 PL I/O 或高速收发器。
这是供原理图审查与 PCB 设计使用的初版，交付形式为 `.circuit`、Telesis、BOM 和浏览器连接审查，**不是传统分页图形原理图或可直接投板的 PCB 工程**。

## 范围与文件

| 模块 | 内容 |
| --- | --- |
| `fpga.circuit` | XCZU15EG-2FFVB1156I，完整 1156 球、供电、去耦和明确 NC |
| `ps_ddr4.circuit` | 4 × 8 Gbit x16，单 rank、64 位、4 GiB、无 ECC |
| `pl_ddr4.circuit` | 2 × 8 Gbit x16，单 rank、32 位、2 GiB、无 ECC |
| `storage.circuit` | 双并联 W25Q256JWEIQ，合计 64 MiB；8 GB eMMC |
| `clock_reset.circuit` | PS 33.333 MHz、PL DDR 200 MHz 差分时钟、32.768 kHz RTC、启动绑带、上电复位 |
| `debug.circuit` | JTAG、1.8 V UART、启动跳线、复位按钮、状态测试点、电源灯 |
| `power.circuit` | 12 V 输入，各级 DC/DC、LDO、PS/PL 独立 VTT/VREF、电源良好信号 |
| `rules.circuit` | 独立编写的 DDR 位序、存储、调试、复位、时序与网络隔离要求 |
| `netlist.expected.json` | 冻结物理封装/焊盘/网络/NC 契约，导出后重新解析 Telesis 核对 |
| `evidence/` | 来源、引脚提取表、设计清单和验证记录 |
| `tools/` | 可复现的 Vivado PS 配置、PL DDR4 综合/布局检查 |

入口为 `board.circuit`，共享库为 `xczu15eg@1`。保持 `design.lock.json`，避免重编号。
完整交付目前为 **538 个器件、3150 个焊盘、332 个网络、571 个 NC**，其中物理测试点也计入器件。

## 生成与审查

从仓库根目录执行：

```sh
.venv/bin/python -m design2allegro check schematics/xczu15eg_minimal/board.circuit
.venv/bin/python -m design2allegro build schematics/xczu15eg_minimal/board.circuit -o build/parser/xczu15eg_minimal
.venv/bin/python -m design2allegro verify build/parser/xczu15eg_minimal
.venv/bin/python -m design2allegro review build/parser/xczu15eg_minimal
.venv/bin/python -m pytest tests/boards -q
make test
make example
make verify-package
```

交付目录包含 `xczu15eg_minimal.tel`、`devices/`、`BOM.csv`、`PINOUT.md`、
`FOOTPRINTS.md`、`IMPORT.md`、DRC 和冻结输入。封装名称只是 Allegro 关联键；仍需创建或匹配真实 padstack/package symbol，核对 BGA 顶视/底视及焊盘编号。
`make example` 包含本工程，`make verify-package` 还在仅安装 wheel 的环境编译和回读本工程。

## 与参考图的差异

- 原 PS SO-DIMM 改为四颗板载 x16 DDR4；PS 专用 DDR 信号按功能同名直连，地址/命令/时钟采用单 rank 拓扑。PL 保留参考图 bank 64/65 的球位分配。
- 六颗内存选 `MT40A512M16LY-075:E`，使用 Vivado 的同名模型，初始目标为 DDR4-1600（800 MHz CK）；参考图的 `-062E` 速度档未沿用。最终采购须核对完整温度等级及后缀。
- 参考 eMMC 符号只有 143 个焊盘，本库根据 Micron AM 封装表补全 153 个；所有 RFU/NC 悬空，包括参考图接地的 A6/J5。保留的 `MTFC8GACAAAM-4M IT` 已停产，采购替换必须重新核对球位、VDDIM、RFU/DS 定义及固件，不能直接替换为任意 153 球器件。
- 移除不需要的收发器和外部接口；未使用收发器电源/接收端/校准端按 AMD 指导接地，发送端与参考时钟不连接。此配置不提供高速串行功能，也不承诺未供电 PS-GTR 相关安全擦除功能。
- PL DDR PAR 通过 0 Ω 固定低，IP 禁用奇偶校验；ALERT_B 保留为 FPGA 输入监视。PL 系统复位 AD5 与内存复位 AK12 为独立网络，禁止短接。
- JTAG 使用 2 mm 2×7 排针，12/14 不连接；PS_SRST 独立测试点。UART0 TX=MIO43，RX=MIO42。
- 电源重新设计为 12 V 输入和 PGOOD 分级使能，未照抄外设供电树。Nexperia BAT54 焊盘为 1=A、2=NC、3=K。

## 启动与外部连接

默认 PS_MODE[3:0]=0010，QSPI32 启动；闭合 `debug.jtag_boot` 跳线将 MODE1 拉低，进入 JTAG（0000）。
切换后重新上电或触发 POR。QSPI 不用 MIO6 反馈时钟，软件应使用无反馈时钟允许的保守频率。
eMMC 使用 SD0、MIO13..20=DAT0..7、MIO21=CMD、MIO22=CLK、MIO23=RESET_N；当前绑带不直接选择 eMMC 启动。

| 接口 | 引脚 |
| --- | --- |
| 12 V 输入 | 1=+12 V，2=GND；需稳压、限流外部电源 |
| UART（4 针，2.54 mm） | 1=GND，2=板端 TX，3=板端 RX，4=1.8 V 电平参考；外接 1.8 V UART 适配器 |
| JTAG（14 针，2 mm） | 2=3.3 V 参考，4=TMS，6=TCK，8=TDO，10=TDI；奇数针接地；12/14=NC |

JTAG、UART 的电源脚用于参考，不用于反向给核心板供电。复位按钮拉低 ALL_GOOD，重新触发 PS POR 和 PL 系统复位。
RTC 不配置电池；断电不保持时间。PL 业务位流需维持未用 I/O 安全状态，并将 PL_ALERT_N 设置为输入。

## 电源实现

| 输出 | 电源器件 | 使能条件/用途 |
| --- | --- | --- |
| 5 V 辅助 | TPS568215 | 输入分压使能；供应偏置和早期 PGOOD 上拉 |
| 0.85 V | TPS543C20A | 5 V PGOOD；PS LP/FP/DDR 核心、PL VCCINT/VCCBRAM/VCCINT_IO 合并常供电 |
| 1.8 V AUX | TPS568215 | 核心 PGOOD；AUX、PSAUX、模拟/PLL 支路、PSBATT |
| 2.5 V VPP | TPS568215 | 核心 PGOOD；DDR4 VPP |
| 1.2 V PSPLL | TPS74801 | AUX PGOOD；IN=1.8 V、BIAS=5 V |
| 1.2 V DDR | TPS568215 | VPP 与 PSPLL 的 PGOOD 二极管与门 |
| 1.8 V I/O、3.3 V I/O | 两颗 TPS568215 | PSPLL PGOOD；MIO 与存储/调试供电 |
| PS/PL 0.6 V VTT、VREF | 两颗 TPS51200 | VIN=3.3 V，VLDOIN=1.2 V，EN=DDR_PG，EN 上拉到 3.3 V |

全部 PGOOD 经隔离二极管汇入 ALL_GOOD，仅控制最终复位，不反馈到早期级使能，避免上电循环等待。
两个 TPS3808G01 监视 3.3 V 和 ALL_GOOD，47 nF 延时电容，分别产生 3.3 V PS_POR_N 与 1.2 V PL_SYS_RESET_N。
3.3 V 分压反馈 45.3 kΩ/10 kΩ，对应约 3.318 V；其他阻值和软启动参数见 `power.circuit`。

额定 40 A/8 A 是器件能力，不是已验证的板级可用电流。负载、散热、输出电感饱和/纹波、有效电容量、控制环路、上下电波形与关机反向时序仍须基于实际应用验证。
模拟支路采用 0 Ω + 电容预留，尚未完成噪声/PDN 优化；不得把它们当作已定型的滤波设计。

## 验证范围与后续交接

`evidence/validation.md` 记录实际执行结果。连接规则独立于电路源文件编写，球位表交叉核对 AMD 官方 CSV 与 Vivado 数据库。
物理网表契约从作者清单和稳定位号生成，**不是独立第三方电气设计审查**；它能防止导出、封装映射与后续改线偏离冻结清单。
更改连线时同时审核规则与契约，不能通过盲目重新生成契约来消除失败。

当前静态 ERC 有 14 个警告：两项源自未配置功能的通用 FPGA BIDIR 与开漏相连（PL_ALERT_N、PL_SYS_RESET_N）；
其余 12 项为输入电源、地、DC/DC 输出电感之后及 0 Ω 滤波之后的供电驱动识别限制。
这些警告没有被隐藏或豁免；详细网络和诊断随交付包保留。规则不覆盖所有器件的模拟参数、过流/过压和动态电源行为。

PCB 阶段必须完成：封装/引脚复核，PS/PL DDR4 拓扑与长度/阻抗约束，参考时钟抖动与幅度核查，去耦摆放与 PDN，
DDR4 SI 仿真、电源热设计/负载分析、启动/关机波形、Allegro 实际导入、最终 FPGA 布线时序和实板 DDR 压测/启动测试。
Vivado 检查只验证 PS 参数和 PL DDR 的引脚资源可布局；不包含 FPGA route、应用时序收敛、DDR 校准或硬件验收。
