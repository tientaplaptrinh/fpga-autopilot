"""Unit tests for static_linter.py, simulator_runner.py, and self_healer.py."""

from __future__ import annotations

from pathlib import Path

from contracts.hdl_models import DigitalSpec, PortSpec
from rtl_studio.static_linter import run_static_lint
from rtl_studio.tb_generator import generate_testbench
from sim_loop.self_healer import run_self_healing_loop
from sim_loop.simulator_runner import run_simulation


def test_static_linter_detects_latch_blkseq_missing_reset_and_width(tmp_path: Path) -> None:
    buggy_sv = tmp_path / "buggy_dut.sv"
    buggy_sv.write_text(
        """
module buggy_dut (
    input  logic       clk,
    input  logic       rst_n,
    input  logic       sel,
    input  logic [3:0] din,
    output logic [3:0] q_seq,
    output logic [3:0] y_latch,
    output logic       undriven_out
);
    // Bug 1: missing reset & blocking '=' in always_ff
    always_ff @(posedge clk) begin
        q_seq = 8'hAA;
    end

    // Bug 2: inferred latch (incomplete if without default at top of always_comb)
    always_comb begin
        if (sel) begin
            y_latch = din;
        end
    end
endmodule
""".strip()
        + "\n",
        encoding="utf-8",
    )

    rpt = run_static_lint(buggy_sv, top_module="buggy_dut")
    assert not rpt.passed
    assert rpt.inferred_latches >= 1
    assert rpt.blocking_in_seq >= 1
    assert rpt.missing_reset_clauses >= 1
    assert rpt.undriven_nets >= 1
    assert rpt.width_mismatches >= 1


def test_simulator_runner_enforces_timeout_on_infinite_loop(tmp_path: Path) -> None:
    dut_sv = tmp_path / "hang_dut.sv"
    dut_sv.write_text(
        "module hang_dut(input logic a, output logic y); always_comb begin y = 1'b0; y = a; end endmodule\n",
        encoding="utf-8",
    )
    tb_sv = tmp_path / "tb_hang_dut.sv"
    tb_sv.write_text(
        """
`timescale 1ns/1ps
module tb_hang_dut;
    logic a = 1'b0;
    logic y;
    hang_dut dut(.a(a), .y(y));
    initial begin
        forever #1 a = ~a;
    end
endmodule
""".strip()
        + "\n",
        encoding="utf-8",
    )

    res = run_simulation(dut_sv, tb_sv, work_dir=tmp_path / "sim", timeout_sec=1.5)
    assert res.compile_passed
    assert res.timed_out
    assert not res.sim_passed


def test_self_healer_repairs_latch_and_functional_bug_without_touching_tb(tmp_path: Path) -> None:
    # Deliberately broken adder_sub_7seg: inferred latch on zero + missing +sub_mode carry-in!
    broken_rtl = """
module adder_sub_7seg (
    input  logic signed [3:0] a,
    input  logic signed [3:0] b,
    input  logic              sub_mode,
    output logic signed [3:0] result,
    output logic              cout,
    output logic              overflow,
    output logic              zero,
    output logic        [6:0] seg_sign,
    output logic        [6:0] seg_mag
);
    logic [3:0] a_u;
    logic [3:0] b_eff;
    logic [4:0] sum_ext;
    logic [3:0] mag;

    always_comb begin
        a_u      = 4'd0;
        b_eff    = 4'd0;
        sum_ext  = 5'd0;
        result   = 4'sd0;
        cout     = 1'b0;
        overflow = 1'b0;
        mag      = 4'd0;
        seg_sign = 7'b111_1111;
        seg_mag  = 7'b111_1111;

        a_u      = a[3:0];
        b_eff    = b[3:0] ^ {4{sub_mode}};
        // BUG 1: missing + {4'b0000, sub_mode}
        sum_ext  = {1'b0, a_u} + {1'b0, b_eff};
        result   = $signed(sum_ext[3:0]);
        cout     = sum_ext[4];
        overflow = (a_u[3] == b_eff[3]) && (sum_ext[3] != a_u[3]);

        // BUG 2: inferred latch on `zero` (no top default, no else!)
        if (sum_ext[3:0] == 4'd0) begin
            zero = 1'b1;
        end

        if (sum_ext[3]) begin
            seg_sign = 7'b011_1111;
            mag      = (~sum_ext[3:0]) + 4'd1;
        end else begin
            seg_sign = 7'b111_1111;
            mag      = sum_ext[3:0];
        end

        case (mag)
            4'h0:    seg_mag = 7'b100_0000;
            4'h1:    seg_mag = 7'b111_1001;
            4'h2:    seg_mag = 7'b010_0100;
            4'h3:    seg_mag = 7'b011_0000;
            4'h4:    seg_mag = 7'b001_1001;
            4'h5:    seg_mag = 7'b001_0010;
            4'h6:    seg_mag = 7'b000_0010;
            4'h7:    seg_mag = 7'b111_1000;
            4'h8:    seg_mag = 7'b000_0000;
            default: seg_mag = 7'b111_1111;
        endcase
    end
endmodule
"""
    spec = DigitalSpec(
        name="adder_sub_7seg",
        top_module="adder_sub_7seg",
        title="Self-Heal Adder Test",
        description="Broken RTL repair verification",
        archetype="adder_sub_7seg",
        clock_port=None,
        reset_port=None,
        ports=[
            PortSpec(name="a", direction="input", width=4, signed=True),
            PortSpec(name="b", direction="input", width=4, signed=True),
            PortSpec(name="sub_mode", direction="input", width=1),
            PortSpec(name="result", direction="output", width=4, signed=True),
            PortSpec(name="cout", direction="output", width=1),
            PortSpec(name="overflow", direction="output", width=1),
            PortSpec(name="zero", direction="output", width=1),
            PortSpec(name="seg_sign", direction="output", width=7, active_low=True),
            PortSpec(name="seg_mag", direction="output", width=7, active_low=True),
        ],
    )

    rtl_dir = tmp_path / "rtl"
    rtl_dir.mkdir()
    dut_file = rtl_dir / "adder_sub_7seg.sv"
    dut_file.write_text(broken_rtl.strip() + "\n", encoding="utf-8")

    tb_file, _ = generate_testbench(spec, tmp_path / "tb")
    tb_before = tb_file.read_bytes()

    outcome = run_self_healing_loop(
        rtl_files=[dut_file],
        tb_file=tb_file,
        work_dir=tmp_path / "sim",
        spec=spec,
        max_iterations=6,
    )

    assert outcome.passed
    assert outcome.iterations >= 1
    assert len(outcome.patch_history) >= 2
    assert outcome.lint_report.passed
    assert outcome.lint_report.inferred_latches == 0
    assert outcome.sim_result.passed_vectors == 512
    assert outcome.sim_result.failed_vectors == 0
    assert tb_file.read_bytes() == tb_before
