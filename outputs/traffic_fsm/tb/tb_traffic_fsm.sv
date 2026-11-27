`timescale 1ns/1ps

module tb_traffic_fsm;

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

    traffic_fsm #(
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
        $dumpfile("traffic_fsm.vcd");
        $dumpvars(0, tb_traffic_fsm);

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
