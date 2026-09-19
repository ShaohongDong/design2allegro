// Static pin/clock placement harness. Not a memory test or application bitstream.
module ddr_pin_check (
    input wire refclk_p, refclk_n, reset_n,
    output wire [16:0] ddr_addr,
    output wire [1:0] ddr_ba,
    output wire ddr_bg, ddr_cke, ddr_cs_n, ddr_odt,
    output wire ddr_act_n, ddr_reset_n, ddr_ck_p, ddr_ck_n,
    inout wire [31:0] ddr_dq,
    inout wire [3:0] ddr_dm, ddr_dqs_p, ddr_dqs_n
);
    wire dci_locked;
    DCIRESET dci_reset (.RST(~reset_n), .LOCKED(dci_locked));
    (* DONT_TOUCH = "yes" *) pl_ddr4 memory (
        .c0_sys_clk_p(refclk_p), .c0_sys_clk_n(refclk_n), .sys_rst(~reset_n | ~dci_locked),
        .c0_ddr4_adr(ddr_addr), .c0_ddr4_ba(ddr_ba), .c0_ddr4_bg(ddr_bg),
        .c0_ddr4_cke(ddr_cke), .c0_ddr4_cs_n(ddr_cs_n), .c0_ddr4_odt(ddr_odt),
        .c0_ddr4_act_n(ddr_act_n), .c0_ddr4_reset_n(ddr_reset_n),
        .c0_ddr4_ck_t(ddr_ck_p), .c0_ddr4_ck_c(ddr_ck_n),
        .c0_ddr4_dm_dbi_n(ddr_dm), .c0_ddr4_dq(ddr_dq),
        .c0_ddr4_dqs_t(ddr_dqs_p), .c0_ddr4_dqs_c(ddr_dqs_n),
        .c0_ddr4_app_en(1'b0), .c0_ddr4_app_hi_pri(1'b0),
        .c0_ddr4_app_wdf_end(1'b0), .c0_ddr4_app_wdf_wren(1'b0),
        .c0_ddr4_app_addr(29'b0), .c0_ddr4_app_cmd(3'b0),
        .c0_ddr4_app_wdf_data(256'b0), .c0_ddr4_app_wdf_mask(32'b0)
    );
endmodule
