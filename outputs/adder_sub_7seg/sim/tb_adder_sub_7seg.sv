`timescale 1ns/1ps

module tb_adder_sub_7seg;

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

    adder_sub_7seg dut (
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
        $dumpfile("adder_sub_7seg.vcd");
        $dumpvars(0, tb_adder_sub_7seg);

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
