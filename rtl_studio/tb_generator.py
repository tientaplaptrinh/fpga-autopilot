"""Self-checking SystemVerilog testbench + Python golden vector generator."""

from __future__ import annotations

import json
import random
from pathlib import Path

from jinja2 import Template

from contracts.hdl_models import DigitalSpec

SEG7_TABLE: dict[int, int] = {
    0x0: 0b100_0000,
    0x1: 0b111_1001,
    0x2: 0b010_0100,
    0x3: 0b011_0000,
    0x4: 0b001_1001,
    0x5: 0b001_0010,
    0x6: 0b000_0010,
    0x7: 0b111_1000,
    0x8: 0b000_0000,
    0x9: 0b001_0000,
    0xA: 0b000_1000,
    0xB: 0b000_0011,
    0xC: 0b100_0110,
    0xD: 0b010_0001,
    0xE: 0b000_0110,
    0xF: 0b000_1110,
}


def generate_adder_sub_golden_vectors() -> list[dict[str, int]]:
    """Compute exact 512-entry golden truth table in Python for 4-bit signed adder/subtractor."""
    vectors: list[dict[str, int]] = []
    for sub_mode in (0, 1):
        for a_u in range(16):
            for b_u in range(16):
                a_s = a_u - 16 if (a_u & 0x8) else a_u
                b_s = b_u - 16 if (b_u & 0x8) else b_u
                true_val = (a_s - b_s) if sub_mode else (a_s + b_s)

                b_eff = b_u ^ (0xF if sub_mode else 0x0)
                sum5 = a_u + b_eff + sub_mode
                res_u = sum5 & 0xF
                res_s = res_u - 16 if (res_u & 0x8) else res_u
                cout = (sum5 >> 4) & 0x1
                overflow = 1 if (true_val < -8 or true_val > 7) else 0
                zero = 1 if res_u == 0 else 0
                seg_sign = 0b011_1111 if res_s < 0 else 0b111_1111
                mag = abs(res_s) & 0xF
                seg_mag = SEG7_TABLE[mag]

                vectors.append(
                    {
                        "sub_mode": sub_mode,
                        "a": a_u,
                        "b": b_u,
                        "result": res_u,
                        "cout": cout,
                        "overflow": overflow,
                        "zero": zero,
                        "seg_sign": seg_sign,
                        "seg_mag": seg_mag,
                    }
                )
    return vectors


def generate_uart_golden_bytes(seed: int = 20261127, count: int = 64) -> list[int]:
    """Generate 64 deterministic test bytes including mandatory corner patterns."""
    rng = random.Random(seed)
    mandatory = [0x00, 0xFF, 0x55, 0xAA, 0x01, 0x80, 0x7F, 0xFE]
    rest = [rng.randint(0, 255) for _ in range(max(0, count - len(mandatory)))]
    return (mandatory + rest)[:count]


_TB_ADDER_SUB_SV = Template(
    """`timescale 1ns/1ps

module tb_{{ top_module }};

    logic              clk;
    logic signed [3:0] a;
    logic signed [3:0] b;
    logic              sub_mode;
    logic signed [3:0] result;
    logic              cout;
    logic              overflow;
    logic              zero;
    logic        [6:0] seg_sign;
    logic        [6:0] seg_mag;

    integer passed_cnt;
    integer failed_cnt;
    integer cycle_cnt;

    {{ top_module }} dut (
        .a        (a),
        .b        (b),
        .sub_mode (sub_mode),
        .result   (result),
        .cout     (cout),
        .overflow (overflow),
        .zero     (zero),
        .seg_sign (seg_sign),
        .seg_mag  (seg_mag)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    function automatic [6:0] golden_seg7(input [3:0] nib);
        begin
            case (nib)
                4'h0:    golden_seg7 = 7'b100_0000;
                4'h1:    golden_seg7 = 7'b111_1001;
                4'h2:    golden_seg7 = 7'b010_0100;
                4'h3:    golden_seg7 = 7'b011_0000;
                4'h4:    golden_seg7 = 7'b001_1001;
                4'h5:    golden_seg7 = 7'b001_0010;
                4'h6:    golden_seg7 = 7'b000_0010;
                4'h7:    golden_seg7 = 7'b111_1000;
                4'h8:    golden_seg7 = 7'b000_0000;
                4'h9:    golden_seg7 = 7'b001_0000;
                4'hA:    golden_seg7 = 7'b000_1000;
                4'hB:    golden_seg7 = 7'b000_0011;
                4'hC:    golden_seg7 = 7'b100_0110;
                4'hD:    golden_seg7 = 7'b010_0001;
                4'hE:    golden_seg7 = 7'b000_0110;
                4'hF:    golden_seg7 = 7'b000_1110;
                default: golden_seg7 = 7'b111_1111;
            endcase
        end
    endfunction

    task automatic check_vector(
        input        in_sub,
        input [3:0]  in_a,
        input [3:0]  in_b
    );
        integer       a_int, b_int, math_val;
        logic [3:0]   b_xor, exp_res, exp_mag;
        logic [4:0]   sum5;
        logic         exp_cout, exp_ovf, exp_zero;
        logic [6:0]   exp_sign, exp_seg;
        logic [20:0]  exp_packed, got_packed;
        logic [8:0]   in_packed;
        begin
            sub_mode = in_sub;
            a        = $signed(in_a);
            b        = $signed(in_b);
            @(posedge clk);
            #1;
            cycle_cnt = cycle_cnt + 1;

            a_int    = in_a[3] ? ($signed({28'hFFFFFFF, in_a})) : $signed({28'd0, in_a});
            b_int    = in_b[3] ? ($signed({28'hFFFFFFF, in_b})) : $signed({28'd0, in_b});
            math_val = in_sub ? (a_int - b_int) : (a_int + b_int);

            b_xor    = in_b ^ {4{in_sub}};
            sum5     = {1'b0, in_a} + {1'b0, b_xor} + {4'd0, in_sub};
            exp_res  = sum5[3:0];
            exp_cout = sum5[4];
            exp_ovf  = (math_val < -8) || (math_val > 7);
            exp_zero = (exp_res == 4'd0);
            exp_sign = exp_res[3] ? 7'b011_1111 : 7'b111_1111;
            exp_mag  = exp_res[3] ? ((~exp_res) + 4'd1) : exp_res;
            exp_seg  = golden_seg7(exp_mag);

            in_packed  = {in_sub, in_a, in_b};
            exp_packed = {exp_res, exp_cout, exp_ovf, exp_zero, exp_sign, exp_seg};
            got_packed = {result[3:0], cout, overflow, zero, seg_sign, seg_mag};

            if (got_packed === exp_packed) begin
                passed_cnt = passed_cnt + 1;
            end else begin
                failed_cnt = failed_cnt + 1;
                $display("[FAIL] cycle=%0d input=%h exp=%h got=%h", cycle_cnt, in_packed, exp_packed, got_packed);
            end
        end
    endtask

    integer sm, ia, ib;

    initial begin
        $dumpfile("{{ vcd_filename }}");
        $dumpvars(0, tb_{{ top_module }});

        passed_cnt = 0;
        failed_cnt = 0;
        cycle_cnt  = 0;
        a          = 4'sd0;
        b          = 4'sd0;
        sub_mode   = 1'b0;

        // Exhaustive 16 x 16 x 2 = 512 directed & corner truth-table sweep
        for (sm = 0; sm < 2; sm = sm + 1) begin
            for (ia = 0; ia < 16; ia = ia + 1) begin
                for (ib = 0; ib < 16; ib = ib + 1) begin
                    check_vector(sm[0], ia[3:0], ib[3:0]);
                end
            end
        end

        @(posedge clk);
        $display("[SUMMARY] passed=%0d failed=%0d", passed_cnt, failed_cnt);
        $finish;
    end

endmodule
"""
)

_TB_TRAFFIC_FSM_SV = Template(
    """`timescale 1ns/1ps

module tb_{{ top_module }};

    localparam [31:0] TICKS_PER_SEC = 32'd4;
    localparam [3:0]  GREEN_SEC     = 4'd4;
    localparam [3:0]  YELLOW_SEC    = 4'd2;
    localparam [3:0]  PED_SEC       = 4'd3;
    localparam [3:0]  ALL_RED_SEC   = 4'd1;

    logic       clk;
    logic       rst_n;
    logic       ped_btn_raw;
    logic       emergency_ovr;
    logic [2:0] ns_light;
    logic [2:0] ew_light;
    logic       ped_walk;
    logic [3:0] countdown;

    integer passed_cnt;
    integer failed_cnt;
    integer cycle_cnt;

    // Coverage flags across all 8 states & safety checks
    logic [7:0] state_seen;

    {{ top_module }} #(
        .SIM_MODE          (32'd1),
        .CLK_FREQ_HZ       (32'd50_000_000),
        .SIM_TICKS_PER_SEC (TICKS_PER_SEC),
        .GREEN_SEC         (GREEN_SEC),
        .YELLOW_SEC        (YELLOW_SEC),
        .PED_SEC           (PED_SEC),
        .ALL_RED_SEC       (ALL_RED_SEC)
    ) dut (
        .clk           (clk),
        .rst_n         (rst_n),
        .ped_btn_raw   (ped_btn_raw),
        .emergency_ovr (emergency_ovr),
        .ns_light      (ns_light),
        .ew_light      (ew_light),
        .ped_walk      (ped_walk),
        .countdown     (countdown)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    // Cycle-accurate Golden Reference Model
    logic [2:0]  g_state, g_next_state;
    logic [31:0] g_tick_cnt, g_db_cnt;
    logic [3:0]  g_timer_sec, g_next_dur;
    logic        g_ff1, g_ff2, g_db, g_db_d, g_ped_pend, g_resume_ew;
    logic        g_sec_tick, g_phase_done, g_ped_pulse;
    logic [2:0]  g_ns, g_ew;
    logic        g_walk;
    logic [3:0]  g_cd;

    always_comb begin
        g_ped_pulse  = g_db && !g_db_d;
        g_sec_tick   = (g_tick_cnt == (TICKS_PER_SEC - 32'd1));
        g_phase_done = g_sec_tick && (g_timer_sec <= 4'd1);

        g_next_state = g_state;
        g_next_dur   = GREEN_SEC;
        if (emergency_ovr) begin
            g_next_state = 3'd7;
            g_next_dur   = 4'd0;
        end else begin
            case (g_state)
                3'd0: if (g_phase_done) begin g_next_state = 3'd1; g_next_dur = YELLOW_SEC; end
                3'd1: if (g_phase_done) begin g_next_state = 3'd2; g_next_dur = ALL_RED_SEC; end
                3'd2: if (g_phase_done) begin
                    if (g_ped_pend) begin g_next_state = 3'd6; g_next_dur = PED_SEC; end
                    else            begin g_next_state = 3'd3; g_next_dur = GREEN_SEC; end
                end
                3'd3: if (g_phase_done) begin g_next_state = 3'd4; g_next_dur = YELLOW_SEC; end
                3'd4: if (g_phase_done) begin g_next_state = 3'd5; g_next_dur = ALL_RED_SEC; end
                3'd5: if (g_phase_done) begin
                    if (g_ped_pend) begin g_next_state = 3'd6; g_next_dur = PED_SEC; end
                    else            begin g_next_state = 3'd0; g_next_dur = GREEN_SEC; end
                end
                3'd6: if (g_phase_done) begin
                    if (g_resume_ew) begin g_next_state = 3'd3; g_next_dur = GREEN_SEC; end
                    else             begin g_next_state = 3'd0; g_next_dur = GREEN_SEC; end
                end
                3'd7: begin g_next_state = 3'd2; g_next_dur = ALL_RED_SEC; end
                default: begin g_next_state = 3'd0; g_next_dur = GREEN_SEC; end
            endcase
        end

        g_ns   = 3'b100;
        g_ew   = 3'b100;
        g_walk = 1'b0;
        g_cd   = g_timer_sec;
        case (g_state)
            3'd0: g_ns = 3'b001;
            3'd1: g_ns = 3'b010;
            3'd3: g_ew = 3'b001;
            3'd4: g_ew = 3'b010;
            3'd6: g_walk = 1'b1;
            3'd7: g_cd = 4'd0;
            default: ;
        endcase
    end

    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            g_ff1       <= 1'b0;
            g_ff2       <= 1'b0;
            g_db_cnt    <= 32'd0;
            g_db        <= 1'b0;
            g_db_d      <= 1'b0;
            g_ped_pend  <= 1'b0;
            g_resume_ew <= 1'b1;
            g_state     <= 3'd0;
            g_tick_cnt  <= 32'd0;
            g_timer_sec <= GREEN_SEC;
        end else begin
            g_ff1  <= ped_btn_raw;
            g_ff2  <= g_ff1;
            g_db_d <= g_db;
            if (g_ff2 == g_db) begin
                g_db_cnt <= 32'd0;
            end else if (g_db_cnt >= 32'd1) begin
                g_db_cnt <= 32'd0;
                g_db     <= g_ff2;
            end else begin
                g_db_cnt <= g_db_cnt + 32'd1;
            end

            if (emergency_ovr || (g_state == 3'd6)) begin
                g_ped_pend <= 1'b0;
            end else if (g_ped_pulse || g_db) begin
                g_ped_pend <= 1'b1;
            end

            if (g_state == 3'd2) g_resume_ew <= 1'b1;
            else if (g_state == 3'd5) g_resume_ew <= 1'b0;

            g_state <= g_next_state;
            if (emergency_ovr) begin
                g_tick_cnt  <= 32'd0;
                g_timer_sec <= 4'd0;
            end else if (g_state != g_next_state) begin
                g_tick_cnt  <= 32'd0;
                g_timer_sec <= g_next_dur;
            end else if (g_sec_tick) begin
                g_tick_cnt <= 32'd0;
                if (g_timer_sec > 4'd1) g_timer_sec <= g_timer_sec - 4'd1;
            end else begin
                g_tick_cnt <= g_tick_cnt + 32'd1;
            end
        end
    end

    task automatic step_and_verify(input integer n_cycles);
        integer i;
        logic [10:0] exp_vec, got_vec;
        logic [2:0]  pre_ns, pre_ew;
        logic        pre_walk;
        begin
            for (i = 0; i < n_cycles; i = i + 1) begin
                @(posedge clk);
                #1;
                cycle_cnt = cycle_cnt + 1;
                exp_vec = {g_ns, g_ew, g_walk, g_cd};
                got_vec = {ns_light, ew_light, ped_walk, countdown};
                state_seen[g_state] = 1'b1;

                // Mutual-exclusion safety assertion: never NS & EW non-red simultaneously, never walk unless both red
                if (((ns_light != 3'b100) && (ew_light != 3'b100)) ||
                    (ped_walk && ((ns_light != 3'b100) || (ew_light != 3'b100)))) begin
                    failed_cnt = failed_cnt + 1;
                    $display("[FAIL] cycle=%0d input=%h exp=%h got=%h", cycle_cnt, {rst_n, ped_btn_raw, emergency_ovr}, exp_vec, got_vec);
                end else if (got_vec === exp_vec) begin
                    passed_cnt = passed_cnt + 1;
                end else begin
                    failed_cnt = failed_cnt + 1;
                    $display("[FAIL] cycle=%0d input=%h exp=%h got=%h", cycle_cnt, {rst_n, ped_btn_raw, emergency_ovr}, exp_vec, got_vec);
                end

                // Mid-cycle Moore glitch check check at +2ns
                pre_ns   = ns_light;
                pre_ew   = ew_light;
                pre_walk = ped_walk;
                #2;
                if ((ns_light !== pre_ns) || (ew_light !== pre_ew) || (ped_walk !== pre_walk)) begin
                    failed_cnt = failed_cnt + 1;
                    $display("[FAIL] cycle=%0d input=%h exp=%h got=%h", cycle_cnt, 4'hF, {pre_ns, pre_ew, pre_walk}, {ns_light, ew_light, ped_walk});
                end
            end
        end
    endtask

    initial begin
        $dumpfile("{{ vcd_filename }}");
        $dumpvars(0, tb_{{ top_module }});

        passed_cnt    = 0;
        failed_cnt    = 0;
        cycle_cnt     = 0;
        state_seen    = 8'd0;
        rst_n         = 1'b0;
        ped_btn_raw   = 1'b0;
        emergency_ovr = 1'b0;

        // 1. Initial asynchronous reset assertion & release
        #12;
        rst_n = 1'b1;
        step_and_verify(64); // Full normal NS -> EW -> NS cycle

        // 2. Bouncy pedestrian button press (1-cycle glitch ignored, sustained press accepted)
        @(negedge clk);
        ped_btn_raw = 1'b1;
        step_and_verify(1);
        @(negedge clk);
        ped_btn_raw = 1'b0; // Glitch < debounce threshold
        step_and_verify(3);

        // Real sustained pedestrian request during NS_GREEN
        @(negedge clk);
        ped_btn_raw = 1'b1;
        step_and_verify(6);
        @(negedge clk);
        ped_btn_raw = 1'b0;
        step_and_verify(48); // Crosses ST_PED_WALK and resumes EW_GREEN

        // Second pedestrian request during EW_GREEN to exercise ALL_RED_2 -> ST_PED_WALK -> NS_GREEN
        @(negedge clk);
        ped_btn_raw = 1'b1;
        step_and_verify(6);
        @(negedge clk);
        ped_btn_raw = 1'b0;
        step_and_verify(48);

        // 3. Emergency override assertion mid-green & recovery
        @(negedge clk);
        emergency_ovr = 1'b1;
        step_and_verify(8);
        @(negedge clk);
        emergency_ovr = 1'b0;
        step_and_verify(24);

        // 4. Mid-transaction asynchronous reset recovery
        #3;
        rst_n = 1'b0;
        #9;
        if ((ns_light !== 3'b001) || (ew_light !== 3'b100) || (ped_walk !== 1'b0)) begin
            failed_cnt = failed_cnt + 1;
            $display("[FAIL] cycle=%0d input=%h exp=%h got=%h", cycle_cnt, 4'h0, 7'b001_100_0, {ns_light, ew_light, ped_walk});
        end else begin
            passed_cnt = passed_cnt + 1;
        end
        @(negedge clk);
        rst_n = 1'b1;
        step_and_verify(20);

        // 5. Verify 100% state coverage across all 8 FSM states
        if (state_seen !== 8'hFF) begin
            failed_cnt = failed_cnt + 1;
            $display("[FAIL] cycle=%0d input=%h exp=%h got=%h", cycle_cnt, 8'hFF, 8'hFF, state_seen);
        end else begin
            passed_cnt = passed_cnt + 1;
        end

        $display("[SUMMARY] passed=%0d failed=%0d", passed_cnt, failed_cnt);
        $finish;
    end

endmodule
"""
)

_TB_UART_FIFO_SV = Template(
    """`timescale 1ns/1ps

module tb_{{ top_module }};

    // Accelerated baud rate for simulation: OS_DIV = 3_200_000 / (100_000 * 16) = 2 clocks/oversample, 32 clocks/bit
    localparam [31:0] SIM_CLK_FREQ  = 32'd3_200_000;
    localparam [31:0] SIM_BAUD_RATE = 32'd100_000;
    localparam integer BIT_CLKS     = 32;

    logic       clk;
    logic       rst_n;
    logic       wr_en;
    logic [7:0] wr_data;
    logic       rd_en;
    logic       rx_serial;
    logic       clr_err;
    logic       tx_serial;
    logic [7:0] rd_data;
    logic       tx_full;
    logic       tx_empty;
    logic       rx_full;
    logic       rx_empty;
    logic       tx_busy;
    logic       framing_error;

    logic       loopback_en;
    logic       manual_rx;

    logic [7:0] tx_vec [0:63];
    integer     tx_idx;
    integer     rx_idx;
    integer     passed_cnt;
    integer     failed_cnt;
    integer     cycle_cnt;
    integer     guard_Wait;

    assign rx_serial = loopback_en ? tx_serial : manual_rx;

    {{ top_module }} #(
        .CLK_FREQ  (SIM_CLK_FREQ),
        .BAUD_RATE (SIM_BAUD_RATE)
    ) dut (
        .clk           (clk),
        .rst_n         (rst_n),
        .wr_en         (wr_en),
        .wr_data       (wr_data),
        .rd_en         (rd_en),
        .rx_serial     (rx_serial),
        .clr_err       (clr_err),
        .tx_serial     (tx_serial),
        .rd_data       (rd_data),
        .tx_full       (tx_full),
        .tx_empty      (tx_empty),
        .rx_full       (rx_full),
        .rx_empty      (rx_empty),
        .tx_busy       (tx_busy),
        .framing_error (framing_error)
    );

    initial begin
        clk = 1'b0;
        forever #5 clk = ~clk;
    end

    always @(posedge clk) begin
        cycle_cnt <= cycle_cnt + 1;
    end

    task automatic inject_bad_stop_frame(input [7:0] bad_payload);
        integer b, c;
        begin
            // Start bit (0)
            manual_rx = 1'b0;
            for (c = 0; c < BIT_CLKS; c = c + 1) @(posedge clk);
            // 8 Data bits LSB-first
            for (b = 0; b < 8; b = b + 1) begin
                manual_rx = bad_payload[b];
                for (c = 0; c < BIT_CLKS; c = c + 1) @(posedge clk);
            end
            // Deliberate BAD stop bit (0 instead of 1) -> must assert framing_error!
            manual_rx = 1'b0;
            for (c = 0; c < BIT_CLKS; c = c + 1) @(posedge clk);
            // Return line to idle high
            manual_rx = 1'b1;
            for (c = 0; c < (BIT_CLKS / 2); c = c + 1) @(posedge clk);
        end
    endtask

    initial begin
        $dumpfile("{{ vcd_filename }}");
        $dumpvars(0, tb_{{ top_module }});

{% for idx, val in golden_bytes %}        tx_vec[{{ idx }}] = 8'h{{ "%02X" % val }};
{% endfor %}

        passed_cnt  = 0;
        failed_cnt  = 0;
        cycle_cnt   = 0;
        rst_n       = 1'b0;
        wr_en       = 1'b0;
        wr_data     = 8'h00;
        rd_en       = 1'b0;
        clr_err     = 1'b0;
        loopback_en = 1'b1;
        manual_rx   = 1'b1;
        tx_idx      = 0;
        rx_idx      = 0;

        // Asynchronous reset
        repeat (4) @(posedge clk);
        rst_n = 1'b1;
        @(posedge clk);

        // Verify empty guard when RX FIFO is empty
        @(negedge clk);
        rd_en = 1'b1;
        @(posedge clk);
        @(negedge clk);
        rd_en = 1'b0;
        if (!rx_empty) begin
            failed_cnt = failed_cnt + 1;
            $display("[FAIL] cycle=%0d input=%h exp=%h got=%h", cycle_cnt, 8'hEE, 1'b1, rx_empty);
        end

        // Phase 1: Stream all 64 golden bytes through 8-byte TX/RX FIFOs in serial loopback
        guard_Wait = 0;
        while ((rx_idx < 64) && (guard_Wait < 40000)) begin
            @(negedge clk);
            wr_en = 1'b0;
            rd_en = 1'b0;

            if ((tx_idx < 64) && !tx_full) begin
                wr_en   = 1'b1;
                wr_data = tx_vec[tx_idx];
                tx_idx  = tx_idx + 1;
            end

            if (!rx_empty) begin
                if (rd_data === tx_vec[rx_idx]) begin
                    passed_cnt = passed_cnt + 1;
                end else begin
                    failed_cnt = failed_cnt + 1;
                    $display("[FAIL] cycle=%0d input=%h exp=%h got=%h", cycle_cnt, rx_idx[7:0], tx_vec[rx_idx], rd_data);
                end
                rd_en  = 1'b1;
                rx_idx = rx_idx + 1;
            end

            @(posedge clk);
            guard_Wait = guard_Wait + 1;
        end
        @(negedge clk);
        wr_en = 1'b0;
        rd_en = 1'b0;

        if (rx_idx != 64) begin
            failed_cnt = failed_cnt + 1;
            $display("[FAIL] cycle=%0d input=%h exp=%h got=%h", cycle_cnt, 8'd64, 8'd64, rx_idx[7:0]);
        end

        // Ensure no framing errors occurred during clean 64-byte loopback
        if (framing_error !== 1'b0) begin
            failed_cnt = failed_cnt + 1;
            $display("[FAIL] cycle=%0d input=%h exp=%h got=%h", cycle_cnt, 8'hF0, 1'b0, framing_error);
        end

        // Phase 2: Deliberate Framing Error Injection & Recovery Check
        repeat (BIT_CLKS * 2) @(posedge clk);
        loopback_en = 1'b0;
        manual_rx   = 1'b1;
        repeat (4) @(posedge clk);

        inject_bad_stop_frame(8'hA5);

        if ((framing_error === 1'b1) && (rx_empty === 1'b1)) begin
            passed_cnt = passed_cnt + 1;
        end else begin
            failed_cnt = failed_cnt + 1;
            $display("[FAIL] cycle=%0d input=%h exp=%h got=%h", cycle_cnt, 8'hA5, 2'b11, {framing_error, rx_empty});
        end

        // Clear framing error flag and verify clean recovery
        @(negedge clk);
        clr_err = 1'b1;
        @(posedge clk);
        @(negedge clk);
        clr_err     = 1'b0;
        loopback_en = 1'b1;
        @(posedge clk);
        #1;
        if (framing_error === 1'b0) begin
            passed_cnt = passed_cnt + 1;
        end else begin
            failed_cnt = failed_cnt + 1;
            $display("[FAIL] cycle=%0d input=%h exp=%h got=%h", cycle_cnt, 8'hC1, 1'b0, framing_error);
        end

        $display("[SUMMARY] passed=%0d failed=%0d", passed_cnt, failed_cnt);
        $finish;
    end

endmodule
"""
)


def _render_generic_tb(spec: DigitalSpec, vcd_filename: str) -> str:
    """Self-checking smoke + random stimulus testbench for generic/custom DigitalSpecs."""
    top = spec.top_module or spec.name
    clk = spec.clock_port or "tb_clk"
    rst = spec.reset_port
    lines = [
        "`timescale 1ns/1ps",
        f"module tb_{top};",
        f"    logic {clk};" if not spec.clock_port else "",
    ]
    for p in spec.ports:
        sign_s = " signed" if p.signed else ""
        rng_s = f" [{p.width - 1}:0]" if p.width > 1 else ""
        lines.append(f"    logic{sign_s}{rng_s} {p.name};")

    lines.append("    integer passed_cnt = 0;")
    lines.append("    integer failed_cnt = 0;")
    lines.append("    integer cycle_cnt = 0;")
    lines.append(f"    {top} dut (")
    for idx, p in enumerate(spec.ports):
        comma = "" if idx == len(spec.ports) - 1 else ","
        lines.append(f"        .{p.name} ({p.name}){comma}")
    lines.append("    );")
    lines.append(f"    initial begin {clk} = 1'b0; forever #5 {clk} = ~{clk}; end")
    lines.append("    initial begin")
    lines.append(f'        $dumpfile("{vcd_filename}");')
    lines.append(f"        $dumpvars(0, tb_{top});")
    for p in spec.ports:
        if p.direction == "input" and p.name != spec.clock_port:
            lines.append(f"        {p.name} = {p.width}'d0;")
    if rst:
        rst_assert = "1'b0" if spec.reset_active_low else "1'b1"
        rst_deassert = "1'b1" if spec.reset_active_low else "1'b0"
        lines.append(f"        {rst} = {rst_assert};")
        lines.append(f"        repeat (3) @(posedge {clk});")
        lines.append(f"        {rst} = {rst_deassert};")

    outputs = [p for p in spec.ports if p.direction == "output"]
    stim_inputs = [
        p for p in spec.ports if p.direction == "input" and p.name not in {spec.clock_port, spec.reset_port}
    ]
    lines.append("        repeat (32) begin")
    lines.append(f"            @(negedge {clk});")
    for inp in stim_inputs:
        lines.append(f"            {inp.name} = $urandom;")
    lines.append(f"            @(posedge {clk}); #1; cycle_cnt = cycle_cnt + 1;")
    if outputs:
        unk_checks = " || ".join(f"(^{o.name} === 1'bx)" for o in outputs)
        lines.append(f"            if ({unk_checks}) begin")
        lines.append("                failed_cnt = failed_cnt + 1;")
        lines.append('                $display("[FAIL] cycle=%0d input=%h exp=%h got=%h", cycle_cnt, 8\'h00, 1\'b0, 1\'b1);')
        lines.append("            end else begin")
        lines.append("                passed_cnt = passed_cnt + 1;")
        lines.append("            end")
    else:
        lines.append("            passed_cnt = passed_cnt + 1;")
    lines.append("        end")
    lines.append('        $display("[SUMMARY] passed=%0d failed=%0d", passed_cnt, failed_cnt);')
    lines.append("        $finish;")
    lines.append("    end")
    lines.append("endmodule")
    return "\n".join(ln for ln in lines if ln != "") + "\n"


def generate_testbench(
    spec: DigitalSpec,
    output_dir: Path,
    vcd_filename: str | None = None,
) -> tuple[Path, Path | None]:
    """Generate self-checking SystemVerilog testbench and Python golden vector JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    top = spec.top_module or spec.name
    vcd_name = vcd_filename or f"{top}.vcd"
    tb_path = output_dir / f"tb_{top}.sv"
    golden_json_path: Path | None = None

    if spec.archetype == "adder_sub_7seg":
        vectors = generate_adder_sub_golden_vectors()
        golden_json_path = output_dir / f"{top}_golden_vectors.json"
        golden_json_path.write_text(json.dumps(vectors, indent=2), encoding="utf-8")
        tb_sv = _TB_ADDER_SUB_SV.render(top_module=top, vcd_filename=vcd_name)
    elif spec.archetype == "traffic_fsm":
        tb_sv = _TB_TRAFFIC_FSM_SV.render(top_module=top, vcd_filename=vcd_name)
    elif spec.archetype == "uart_fifo_top":
        gbytes = generate_uart_golden_bytes(count=64)
        golden_json_path = output_dir / f"{top}_golden_vectors.json"
        golden_json_path.write_text(
            json.dumps({"loopback_bytes_hex": [f"0x{b:02X}" for b in gbytes]}, indent=2),
            encoding="utf-8",
        )
        tb_sv = _TB_UART_FIFO_SV.render(
            top_module=top,
            vcd_filename=vcd_name,
            golden_bytes=list(enumerate(gbytes)),
        )
    else:
        tb_sv = _render_generic_tb(spec, vcd_name)

    tb_path.write_text(tb_sv.strip() + "\n", encoding="utf-8")
    return tb_path, golden_json_path
