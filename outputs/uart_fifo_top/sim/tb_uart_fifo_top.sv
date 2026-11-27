`timescale 1ns/1ps

module tb_uart_fifo_top;

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

    uart_fifo_top #(
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
        $dumpfile("uart_fifo_top.vcd");
        $dumpvars(0, tb_uart_fifo_top);

        tx_vec[0] = 8'h00;
        tx_vec[1] = 8'hFF;
        tx_vec[2] = 8'h55;
        tx_vec[3] = 8'hAA;
        tx_vec[4] = 8'h01;
        tx_vec[5] = 8'h80;
        tx_vec[6] = 8'h7F;
        tx_vec[7] = 8'hFE;
        tx_vec[8] = 8'h12;
        tx_vec[9] = 8'h85;
        tx_vec[10] = 8'h9A;
        tx_vec[11] = 8'h4B;
        tx_vec[12] = 8'h55;
        tx_vec[13] = 8'h91;
        tx_vec[14] = 8'hC9;
        tx_vec[15] = 8'h79;
        tx_vec[16] = 8'h89;
        tx_vec[17] = 8'h2C;
        tx_vec[18] = 8'h52;
        tx_vec[19] = 8'hED;
        tx_vec[20] = 8'h11;
        tx_vec[21] = 8'h53;
        tx_vec[22] = 8'h68;
        tx_vec[23] = 8'h14;
        tx_vec[24] = 8'hFA;
        tx_vec[25] = 8'h4D;
        tx_vec[26] = 8'h0E;
        tx_vec[27] = 8'h1B;
        tx_vec[28] = 8'hE4;
        tx_vec[29] = 8'h8C;
        tx_vec[30] = 8'hF2;
        tx_vec[31] = 8'h11;
        tx_vec[32] = 8'h10;
        tx_vec[33] = 8'hF3;
        tx_vec[34] = 8'h7B;
        tx_vec[35] = 8'h56;
        tx_vec[36] = 8'hC4;
        tx_vec[37] = 8'h81;
        tx_vec[38] = 8'h4F;
        tx_vec[39] = 8'h8C;
        tx_vec[40] = 8'hD1;
        tx_vec[41] = 8'h46;
        tx_vec[42] = 8'hEA;
        tx_vec[43] = 8'h78;
        tx_vec[44] = 8'h90;
        tx_vec[45] = 8'h36;
        tx_vec[46] = 8'h88;
        tx_vec[47] = 8'h31;
        tx_vec[48] = 8'h46;
        tx_vec[49] = 8'hA0;
        tx_vec[50] = 8'h28;
        tx_vec[51] = 8'hF9;
        tx_vec[52] = 8'h56;
        tx_vec[53] = 8'h2A;
        tx_vec[54] = 8'h24;
        tx_vec[55] = 8'h0C;
        tx_vec[56] = 8'h14;
        tx_vec[57] = 8'h97;
        tx_vec[58] = 8'h70;
        tx_vec[59] = 8'h8E;
        tx_vec[60] = 8'hA9;
        tx_vec[61] = 8'hE3;
        tx_vec[62] = 8'h81;
        tx_vec[63] = 8'h7D;


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
