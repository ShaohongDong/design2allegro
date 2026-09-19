# 验证记录（2026-09-19）

- `make test`：185 passed。
- `.venv/bin/python -m pytest tests/boards -q`：10 passed；包括完整 1156 球的官方 CSV/Vivado 对比、3150 焊盘覆盖、RFU/收发器处理、所有 FPGA 电源球、UART/复位、电源短接与信号交换负向用例、物理契约回读，以及全部 74 个 Vivado 顶层端口球位与板级网表交叉核对。
- `make example`：三个工程均生成、回读成功，包括 XCZU15EG。
- `make verify-package`：wheel 独立环境成功编译/回读 XCZU15EG 和现有夹具，原有 Review 资源/API 测试通过。首次因本机 Python 缺 ensurepip 失败，安装到项目虚拟环境的 pip/virtualenv 后重跑成功；没有修改系统 Python。
- 板级导出：538 个器件、3150 个物理引脚、332 个网络；完整契约核对通过。静态 DRC 仍有 14 个警告，列表见 `remaining_diagnostics.json` 和工程 README。
- Review：`http://127.0.0.1:8766/` 及 `/api/package` HTTP 200，API 读到本板统计。没有以页面可访问替代逐网人工电气审查。
- Vivado 2025.2：`validate_bd_design` 验证 PS DDR4/双 QSPI/eMMC/UART 配置；DDR4 IP 使用 MT40A512M16LY-075、32 位、1250 ps CK、5000 ps 输入周期。综合、优化、布局成功，`placed_drc.rpt` 无 ERROR。
- PL 验证顶层包括 DCIRESET，解除复位时等待 DCI 锁定；早期缺 DCIRESET 的 44 个警告已修正。最终仍有 1 个 RTSTAT-13 Critical Warning（没有 route）和 3 个生成的 dbg_hub PDCN-1569 LUT Warning，未隐藏或豁免。

复现 Vivado 检查（仓库根目录，具备相应器件/许可证）：

```sh
/home/dsh/AMD/2025.2/Vivado/bin/vivado -mode batch -nojournal \
  -log build/parser/xczu15eg_vivado/run.log \
  -source schematics/xczu15eg_minimal/tools/validate_vivado.tcl
```

脚本输出位于 `build/parser/xczu15eg_vivado/`。`validation.ok` 只表示 PS 配置与 PL 综合/布局通过；每次运行开始移除旧标志。
源文件、模型、物理契约、日志及报告的 SHA-256 见 `validation.json`。Vivado 输入脚本末次增加的旧成功标志清理属于记录卫生，不改变已执行的 PS/PL 参数和布线约束。

**未完成且不在这些检查的证明范围内：** Allegro 实际导入、PCB layout、DDR SI/电源 PI、稳态和动态电流/热设计、上下电时序波形、FPGA route 和时序收敛、启动固件、DDR 校准/压力测试、实板验收。详见上级 README 的 PCB 交接项。
