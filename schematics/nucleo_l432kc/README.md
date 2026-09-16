# NUCLEO-L432KC：官方 MB1180 电路示例

本示例把 ST 官方电路转录为 `design2allegro` YAML，输出 Allegro Telesis
网表。包括 STM32L432KCU6U、ST-LINK/V2-1、Micro-B USB、双路供电、
稳压器、晶体、复位、LED、Arduino Nano 排针及全部焊桥。仅支持 Allegro。

## 构建

在仓库根目录运行：

```bash
.venv/bin/design2allegro check schematics/nucleo_l432kc/board.yaml
.venv/bin/design2allegro build schematics/nucleo_l432kc/board.yaml -o build/parser/nucleo_l432kc
.venv/bin/design2allegro verify build/parser/nucleo_l432kc
```

网表为 `build/parser/nucleo_l432kc/nucleo_l432kc.tel`。导入时保留整个输出目录，
提供匹配的 Allegro 封装和 padstack；本项目不生成这些库文件。

## 内容与默认装配

共 **89 个电气器件/焊桥、312 个物理焊盘、82 个 PCB 网络、16 个明确 NC**。
DNP 的 C3、R13、CN2 保留焊盘和接线。装配状态见 [BOM](BOM.md)，
完整引脚网络见 [PINOUT](PINOUT.md)，库约定见 [FOOTPRINTS](FOOTPRINTS.md)。

- 目标 MCU U2 为 UFQFPN32，裸露焊盘 33 接地；U5 为 ST-LINK 的 STM32F103CBT6。
- X1 为目标 MCU 的 32.768 kHz 晶体；X2 为 ST-LINK 的 8 MHz 晶体。
- 开放焊桥：SB1、SB4、SB6、SB8、SB17。其余 13 个焊桥默认闭合。
- JP1 默认短接供电测流接口。CN3 的 4–5 脚另有出厂演示短路帽，
  将 PA12/D2 接地，使用此 GPIO 前移除。它们是装配附件，不额外增加 PCB 焊盘。
- 闭合焊桥、JP1 和演示短路帽不会合并两侧的 PCB 网络；元件属性记录闭合状态。
  SB16/SB18 默认连接 A5–D5、A4–D4，固件须遵守官方引脚复用限制。
- USB 为原板 Micro-B，接入 ST-LINK。未改成 USB-C，也未增删原板电路。

## 来源与版本处理

资料下载地址及 SHA-256 见 [sources.json](sources.json)。官方原始包留在构建研究目录，
不把厂商 CAD 二进制或固件加入源码。使用者仍需遵守 ST 原始资料附带的许可条款。

1. [ST 产品页](https://www.st.com/en/evaluation-tools/nucleo-l432kc.html)：
   官方 schematic pack 2.0 的 `MB1180.pdf` 标题栏为 **C.1，2015-06-05**，共三页。
   两张功能页的 SchDoc 连接与同包 PcbDoc 物理焊盘网络逐项交叉核对。
2. [官方 BOM](https://www.st.com/resource/en/bill_of_materials/nucleo-32pins_bom.zip)：
   文件 `MB1180C_BOM.xlsx` 内版本为 **C-09**，默认缓存选择 L412KB。
   本示例按 **A21=L432KC** 的公式求值，使用 STM32L432KCU6U、UFQFPN32，
   安装 X1/C12/C13，闭合 SB5/SB7、开放 SB6/SB8。数量按位号统计，
   不采用与位号不符的第 56、57 行 Quantity 缓存值。
3. [UM1956 Rev 6，2025-03](https://www.st.com/resource/en/user_manual/um1956-stm32-nucleo32-boards-mb1180-stmicroelectronics.pdf)：
   §6.1、§7、表 16 和表 17，核对跳线、排针与 **MB1180-L432KC-C02** 装配型号。
4. [STM32L432 数据手册](https://www.st.com/resource/en/datasheet/stm32l432kc.pdf)：
   图 5、引脚表和 §7.1，替换通用 MCU 符号的复用名称并补充裸露地焊盘。

这些是不同资料的版本号，不把通用 C.1 图纸冒充 L432KC 专用 C.2 原理图。
PCB 文件包含叠放的 LQFP/QFN 焊盘，本示例仅保留 L432KC 的 QFN 封装，
排除重复的 LQFP 焊盘和非电气 Logo。

## 校验范围与已知提示

规则检查全部网络的端点、网络隔离、NC、装配状态、阻值和 SWD/VCP/复位路径。
测试使用独立从官方 PCB 提取的完整连接表，并验证默认闭合焊桥形成的通路。
`initial_state` 是装配证据，规则引擎不进行开关、二极管或稳压器模拟。

保留 **10 条 ERC WARNING**，无豁免：

- 7 条 `ERC.DRIVE`：AVDD、NetC15_2、NetSB11_1、NetSB13_1、V5、VDD、VIN。
  当前 ERC 不跨焊桥、磁珠、二极管传播驱动；VIN 是可选外部电源输入。
- 3 条 `ERC.SINGLE`：T_JTDI、T_JTDO、T_SWO 是官方保留的单端网络。

这些提示不表示已完成电源时序或电气仿真。缺少完整电气模型的引脚仍在报告中列出；
没有把有源引脚统一改成 PASSIVE，也没有把电源边界假装为实际测量。
USB 枚举控制供电依赖 ST-LINK 固件；本示例不包含该固件。
**验收仅为电路转录及离线网表验证，实际 Allegro 导入、PCB 布局、制造与硬件均未验证。**
