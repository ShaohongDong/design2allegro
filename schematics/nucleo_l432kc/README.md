# NUCLEO-L432KC：官方 MB1180 电路示例

本示例把 ST 官方电路转录为 `design2allegro` 专用 Circuit 语言，输出 Allegro Telesis
网表。包括 STM32L432KCU6U、ST-LINK/V2-1、Micro-B USB、双路供电、
稳压器、晶体、复位、LED、Arduino Nano 排针及全部焊桥。仅支持 Allegro。

## 输入结构与选型状态

`board.circuit` 为 Circuit 2 入口，通过 `include` 引入 `templates.circuit`、
`interfaces.circuit`、`power.circuit`、`stlink.circuit`、`target.circuit` 和
`rules.circuit`。输入使用功能名及稳定 ID，位号由引擎自动分配。
`rules.circuit` 用显式网络代表引脚组和 `isolated_all` 检查网络隔离。

原有 76 项缺规格错误已补齐，使用共享器件库 `standard@2`，保留 `standard@1`。
检查为 511 项 PASS、0 项 ERROR，保留下文的 10 条 WARNING。
这是基于官方连接的**本项目采购选型版本**，替代器件不冒充原板实装型号。

## 检查与构建

在仓库根目录运行：

```bash
.venv/bin/design2allegro check schematics/nucleo_l432kc/board.circuit
.venv/bin/design2allegro build schematics/nucleo_l432kc/board.circuit -o build/parser/nucleo_l432kc
.venv/bin/design2allegro verify build/parser/nucleo_l432kc
```

构建的网表为 `build/parser/nucleo_l432kc/nucleo_l432kc.tel`。导入时保留整个输出目录，
提供匹配的 Allegro 封装和 padstack；本项目不生成这些库文件。

## 内容与默认装配

共 **89 个电气器件/焊桥、312 个物理焊盘、82 个 PCB 网络、16 个明确 NC**。
DNP 的 C3、R13、CN2 保留焊盘和接线。装配状态、完整引脚网络及封装表分别由构建生成到输出目录的
`BOM.md`、`PINOUT.md`、`FOOTPRINTS.md`，不再作为手写输入维护。

- 目标 MCU U2 为 UFQFPN32，裸露焊盘 33 接地；U5 为 ST-LINK 的 STM32F103CBT6。
- X1 为目标 MCU 的 32.768 kHz 晶体；X2 为 ST-LINK 的 8 MHz 晶体。
- 开放焊桥：SB1、SB4、SB6、SB8、SB17。其余 13 个焊桥默认闭合。
- JP1 默认短接供电测流接口。CN3 的 4–5 脚另有出厂演示短路帽，
  将 PA12/D2 接地，使用此 GPIO 前移除。它们是装配附件，不额外增加 PCB 焊盘。
- 闭合焊桥、JP1 和演示短路帽不会合并两侧的 PCB 网络；元件属性记录闭合状态。
  SB16/SB18 默认连接 A5–D5、A4–D4，固件须遵守官方引脚复用限制。
- USB 为原板 Micro-B，接入 ST-LINK。未改成 USB-C，也未增删原板电路。

## 与官方 BOM 的差异

下表使用功能名；括号内官方位号仅供查阅来源，不控制生成编号。
完整原型号、替代原因、引脚/封装核对及数据手册链接见
[sources.json](sources.json) 的 `project_selections`、`specification_sources`。

| 器件 | 官方记录 | 本项目选型 / 修正 |
| --- | --- | --- |
| Arduino 排针 CN3/CN4 | ATOM PH254015B-09303 | Wuerth 61301511121，15 针 2.54 mm 公排针；3 A、250 VAC |
| 调试排针 CN2 | 通用 5 针，DNP | Wuerth 61300511121；保持 DNP |
| 电源红灯 LD2 | 19-217/R6C-AL1M2VY/3T | Everlight 19-217/R6C-P1Q2/3T，0603；亮度档不同 |
| 用户灯 LD3 | 19-213SY6C/S530-E2/TR8LED | Everlight 19-213/G6C-AP1Q2/3T，0603 黄绿色；光学档不同 |
| 调试双色灯 LD1 | Everluck LE-RGW35280 | Broadcom HSMF-A201-A00J1；采用原 SchDoc 中 Avago 备选型号 |
| 复位晶体管 T1 | ST MMBT9013，厂商资料无法确认 | Taitron MMBT9013；见下方原封装编号约定 |
| MCO 电容 C3 | 20 pF，DNP，无完整型号 | YAGEO CC0603JRNPO9BN200，50 V、NP0、±5%；保持 DNP |
| 预留电阻 R13 | 10 kohm，DNP，无完整型号 | YAGEO RC0603FR-0710KL，±1%、0.1 W；保持 DNP |
| 复位按键 B1 | 通用 BOM；SchDoc 标 KSS221G | C&K KSS221GLFS，补完整订货后缀，银触点 50 mA/32 VDC |
| 磁珠 L1 | FCM1608KF-601T05，BOM 写 350 mA | 型号不变；按厂商表修正为 500 mA，DCR ≤0.5 ohm、100 MHz |

电阻功率、MCU/稳压器工作范围、晶体初始频差等按原型号手册补全。
LED 的 5 V 是反向耐压；BAT60 的 3 A 是占空比 0.11 的重复峰值，不能当作
连续额定电流。`rating_conditions` 随器件属性导出到 BOM，保留这些条件。
稳压器输入工作范围不表示在低于输出电压时仍能稳压。

**封装编号约定：** 原 MB1180 `SOT23-3` 的焊盘 1=E、2=B、3=C；
它的 1/2 位置与通常的 JEDEC SOT-23 编号相反。Taitron 数据手册引脚为
1=B、2=E、3=C，因此厂商引脚 1/2/3 对应原封装焊盘 2/1/3。
此绑定按原 PCB 坐标核对，网络保持原样。提供 Allegro 封装时必须遵守
原几何和编号，不能直接套用普通 SOT-23 编号。原排针封装名的 `_F`
后缀也沿用历史名称；公排针选型依据 SchDoc 注释及 PCB 封装描述。

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
板级约束保存在本设计的 `rules.circuit` 中，通过显式 `check` / `build` 命令检查；
内核测试不读取本设计，也不固定板级器件数量、选型或告警列表。

`board.circuit` 通过 `netlist_expectations` 指定本目录的
[`netlist.expected.json`](netlist.expected.json)。这是最终网表的全量物理基准：
89 个器件及封装、312 个物理引脚、82 个网络的完整成员和 16 个 NC。
首版连接清单由已有 `PRESENT_*` 板级规则整理，与全部编译网络逐项比对；
NC 与 `NC` 规则逐项核对，物理编号和封装来自当前器件绑定及 `design.lock.json`。
采用项目自动分配的位号，不是官方原图位号，也不表示新增了独立官方 CAD 验证。

`build` 在网表转换后、发布输出和更新位号锁之前自动回读 `.tel` 与 device 文件，
按此基准严格校验；任何缺项、多项、错接、封装或 NC 差异都会阻止交付，
保留旧输出及位号锁。交付包包含基准副本，单独运行 `verify` 也会重复校验，
无需原设计目录。`check` 只检查基准格式、完整性和原有电气规则。
修改板级设计时应人工审阅和更新基准；正常构建不会自动覆盖该文件。

`initial_state` 是装配证据，规则引擎不进行开关、二极管或稳压器模拟。

保留 **10 条 ERC WARNING**，无豁免：

- 7 条 `ERC.DRIVE`：AVDD、NetC15_2、NetSB11_1、NetSB13_1、V5、VDD、VIN。
  当前 ERC 不跨焊桥、磁珠、二极管传播驱动；VIN 是可选外部电源输入。
- 3 条 `ERC.SINGLE`：T_JTDI、T_JTDO、T_SWO 是官方保留的单端网络。

这些提示不表示已完成电源时序或电气仿真。缺少完整电气模型的引脚仍在报告中列出；
没有把有源引脚统一改成 PASSIVE，也没有把电源边界假装为实际测量。
USB 枚举控制供电依赖 ST-LINK 固件；本示例不包含该固件。
**验收仅为电路转录及离线网表验证，实际 Allegro 导入、PCB 布局、制造与硬件均未验证。**
