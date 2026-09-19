# Run from repository root. All generated files stay in the dedicated build tree.
set repo [file normalize [file join [file dirname [info script]] ../../..]]
set board [file join $repo schematics xczu15eg_minimal]
set out [file join $repo build parser xczu15eg_vivado]
file mkdir $out
cd $out
file delete -force [file join $out validation.ok]
create_project -force xczu15eg_minimal [file join $out project] -part xczu15eg-ffvb1156-2-i
set_param general.maxThreads 4
create_bd_design ps_check
create_bd_cell -type ip -vlnv xilinx.com:ip:zynq_ultra_ps_e:* ps
set ps [get_bd_cells ps]
set_property -dict [list \
 CONFIG.PSU__DDRC__MEMORY_TYPE {DDR 4} \
 CONFIG.PSU__DDRC__DEVICE_CAPACITY {8192 MBits} \
 CONFIG.PSU__DDRC__DRAM_WIDTH {16 Bits} \
 CONFIG.PSU__DDRC__BUS_WIDTH {64 Bit} \
 CONFIG.PSU__DDRC__ECC {Disabled} \
 CONFIG.PSU__DDRC__SPEED_BIN {DDR4_1600J} \
 CONFIG.PSU__DDRC__FREQ_MHZ {800} \
 CONFIG.PSU__DDRC__BG_ADDR_COUNT {1} \
 CONFIG.PSU__DDRC__ROW_ADDR_COUNT {16} \
 CONFIG.PSU__DDRC__COL_ADDR_COUNT {10} \
 CONFIG.PSU__USE__M_AXI_GP2 {0} \
 CONFIG.PSU__PSS_REF_CLK__FREQMHZ {33.333} \
 CONFIG.PSU__QSPI__PERIPHERAL__ENABLE {1} \
 CONFIG.PSU__QSPI__PERIPHERAL__MODE {Dual Parallel} \
 CONFIG.PSU__QSPI__PERIPHERAL__IO {MIO 0 .. 12} \
 CONFIG.PSU__SD0__PERIPHERAL__ENABLE {1} \
 CONFIG.PSU__SD0__PERIPHERAL__IO {MIO 13 .. 22} \
 CONFIG.PSU__SD0__SLOT_TYPE {eMMC} \
 CONFIG.PSU__SD0__RESET__ENABLE {1} \
 CONFIG.PSU__UART0__PERIPHERAL__ENABLE {1} \
 CONFIG.PSU__UART0__PERIPHERAL__IO {MIO 42 .. 43} \
 CONFIG.PSU__IOU_SLCR__BANK0_IO_STANDARD {LVCMOS18} \
 CONFIG.PSU__IOU_SLCR__BANK1_IO_STANDARD {LVCMOS18} \
 CONFIG.PSU__IOU_SLCR__BANK2_IO_STANDARD {LVCMOS18}] $ps
validate_bd_design
save_bd_design
report_property $ps -file [file join $out ps_configuration.txt]
write_bd_tcl -force [file join $out ps_configuration.tcl]
close_bd_design [get_bd_designs ps_check]
# The PS validation BD is not part of the PL-only pin placement harness.
set_property USED_IN_SYNTHESIS false [get_files -filter {FILE_TYPE == "Block Designs"}]
create_ip -name ddr4 -vendor xilinx.com -library ip -module_name pl_ddr4
set ip [get_ips pl_ddr4]
set_property -dict [list \
 CONFIG.C0.DDR4_MemoryPart {MT40A512M16LY-075} \
 CONFIG.C0.DDR4_DataWidth {32} \
 CONFIG.C0.DDR4_TimePeriod {1250} \
 CONFIG.C0.DDR4_InputClockPeriod {5000} \
 CONFIG.C0.DDR4_DataMask {DM_NO_DBI} \
 CONFIG.System_Clock {Differential}] $ip
report_property $ip -file [file join $out pl_configuration.txt]
generate_target all $ip
synth_ip $ip
read_verilog [file join $board tools ddr_pin_check.v]
read_xdc [file join $board tools pl_ddr4.xdc]
synth_design -top ddr_pin_check -part xczu15eg-ffvb1156-2-i
opt_design
place_design
report_drc -file [file join $out placed_drc.rpt]
report_io -file [file join $out placed_io.rpt]
write_checkpoint -force [file join $out placed.dcp]
set errors [get_drc_violations -quiet -filter {SEVERITY == Error}]
if {[llength $errors]} { error "Placed design has DRC errors: $errors" }
set f [open [file join $out validation.ok] w]
puts $f "PS configuration validated; PL DDR4 synthesized and placed; zero ERROR DRC. Not routed or board tested."
close $f
exit
