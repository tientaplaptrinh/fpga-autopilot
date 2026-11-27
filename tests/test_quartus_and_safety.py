"""Unit tests for Quartus project_builder, report_parser, Yosys fallback, and GUI confinement."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import pyautogui
import pytest

from contracts.hdl_models import DigitalSpec, PortSpec
from quartus_driver.gui_inspector import (
    SafeGuiInspector,
    WindowConfinementError,
    audit_waveform_canvas,
    verify_point_in_bbox,
)
from quartus_driver.project_builder import build_quartus_project
from quartus_driver.report_parser import parse_quartus_reports
from quartus_driver.synth_runner import run_synthesis

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.mark.parametrize(
    ("preset", "expected_family", "expected_device"),
    [
        ("DE2-115", "Cyclone IV E", "EP4CE115F29C7"),
        ("DE10-Lite", "MAX 10", "10M50DAF484C7G"),
        ("DE1-SoC", "Cyclone V", "5CSEMA5F31C6"),
    ],
)
def test_project_builder_board_presets_and_sdc(
    tmp_path: Path, preset: str, expected_family: str, expected_device: str
) -> None:
    spec = DigitalSpec(
        name="demo_sync",
        title="Preset Test",
        description="Board preset test",
        board_preset=preset,  # type: ignore[arg-type]
        ports=[
            PortSpec(name="clk", direction="input", width=1),
            PortSpec(name="rst_n", direction="input", width=1, active_low=True),
            PortSpec(name="sw", direction="input", width=4),
            PortSpec(name="led", direction="output", width=4),
        ],
    )
    dummy_sv = tmp_path / "demo_sync.sv"
    dummy_sv.write_text("module demo_sync(input logic clk, rst_n, input logic [3:0] sw, output logic [3:0] led); assign led = sw; endmodule\n", encoding="utf-8")

    art = build_quartus_project(spec, [dummy_sv], tmp_path / preset)
    assert art.qpf_path.exists()
    assert art.qsf_path.exists()
    assert art.sdc_path.exists()
    assert art.tcl_path.exists()

    qsf_txt = art.qsf_path.read_text(encoding="utf-8")
    assert f'FAMILY "{expected_family}"' in qsf_txt
    assert f"DEVICE {expected_device}" in qsf_txt

    sdc_txt = art.sdc_path.read_text(encoding="utf-8")
    assert "create_clock" in sdc_txt
    assert "set_false_path -from [get_ports {rst_n}]" in sdc_txt


def test_report_parser_extracts_resources_timing_and_latch_warnings(tmp_path: Path) -> None:
    out_files = tmp_path / "output_files"
    out_files.mkdir()
    shutil.copy2(FIXTURES_DIR / "sample_top.map.rpt", out_files / "sample_top.map.rpt")
    shutil.copy2(FIXTURES_DIR / "sample_top.fit.rpt", out_files / "sample_top.fit.rpt")
    shutil.copy2(FIXTURES_DIR / "sample_top.sta.rpt", out_files / "sample_top.sta.rpt")

    rpt = parse_quartus_reports(project_dir=tmp_path, top_module="sample_top")
    assert rpt.compile_passed
    assert rpt.family == "Cyclone IV E"
    assert rpt.device == "EP4CE115F29C7"
    assert rpt.resources.logic_elements_or_alms == 96
    assert rpt.resources.combinational_functions == 88
    assert rpt.resources.dedicated_logic_registers == 52
    assert rpt.resources.memory_bits == 128
    assert rpt.resources.dsp_elements == 2
    assert rpt.resources.total_pins == 18
    assert rpt.resources.inferred_latches == 0
    assert rpt.timing.fmax_mhz == pytest.approx(241.55)
    assert rpt.timing.worst_setup_slack_ns == pytest.approx(15.860)
    assert rpt.timing.worst_hold_slack_ns == pytest.approx(0.214)

    # Inject a latch warning into .map.rpt and verify inferred_latches > 0
    map_p = out_files / "sample_top.map.rpt"
    map_p.write_text(
        map_p.read_text(encoding="utf-8")
        + '\nWarning (10240): Verilog HDL Always Construct warning at sample_top.sv(22): inferring latch(es) for variable "bad_q"\n',
        encoding="utf-8",
    )
    rpt_latched = parse_quartus_reports(project_dir=tmp_path, top_module="sample_top")
    assert rpt_latched.resources.inferred_latches == 1


def test_yosys_fallback_when_max10_family_absent_on_quartus13(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contracts.toolchain import find_tool

    spec = DigitalSpec(
        name="max10_reg",
        title="MAX 10 Fallback Check",
        description="Auto-fallback to Yosys when MAX 10 is absent in Quartus 13.0",
        board_preset="DE10-Lite",
        ports=[
            PortSpec(name="clk", direction="input", width=1),
            PortSpec(name="rst_n", direction="input", width=1, active_low=True),
            PortSpec(name="d", direction="input", width=4),
            PortSpec(name="q", direction="output", width=4),
        ],
    )
    sv = tmp_path / "max10_reg.sv"
    sv.write_text(
        """
module max10_reg (
    input  logic       clk,
    input  logic       rst_n,
    input  logic [3:0] d,
    output logic [3:0] q
);
    always_ff @(posedge clk or negedge rst_n) begin
        if (!rst_n) q <= 4'd0;
        else        q <= d;
    end
endmodule
""".strip()
        + "\n",
        encoding="utf-8",
    )

    if not find_tool("yosys"):
        import json
        import subprocess

        monkeypatch.setattr("quartus_driver.synth_runner.find_tool", lambda name, env=None: "mock_yosys" if name == "yosys" else find_tool(name, env))

        def _fake_yosys_run(cmd: list[str], cwd: str, **kwargs: object) -> subprocess.CompletedProcess[str]:
            stat_p = Path(cwd) / "max10_reg_yosys_stat.json"
            stat_p.write_text(
                json.dumps(
                    {
                        "design": {
                            "num_cells_by_type": {
                                "cycloneive_lcell_comb": 4,
                                "dffeas": 4,
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(cmd, 0, stdout="OK", stderr="")

        monkeypatch.setattr("quartus_driver.synth_runner.subprocess.run", _fake_yosys_run)

    rpt = run_synthesis(spec, [sv], tmp_path / "qproj", backend="yosys")
    assert rpt.compile_passed
    assert rpt.backend == "yosys"
    assert Path(rpt.qpf_path or "").exists()
    assert Path(rpt.qsf_path or "").exists()
    assert Path(rpt.sdc_path or "").exists()
    assert rpt.resources.dedicated_logic_registers >= 4
    assert rpt.resources.inferred_latches == 0


def test_gui_safety_confinement_and_opencv_waveform_auditor(tmp_path: Path) -> None:
    assert pyautogui.FAILSAFE is True
    inspector = SafeGuiInspector(audit_dir=tmp_path / "gui_audit")

    # 1. Out-of-bounds coordinate must be blocked immediately
    with pytest.raises(WindowConfinementError):
        inspector.safe_click(1500, 900, (100, 100, 800, 600), "GTKWave - sim.vcd", "test oob")

    # 2. Disallowed non-EDA window (e.g., Chrome / OS Settings) must be blocked even if inside bbox
    with pytest.raises(WindowConfinementError):
        verify_point_in_bbox(250, 250, (100, 100, 800, 600), "Google Chrome")

    # Verify blocked attempt was recorded in audit JSONL
    assert inspector.log_path.exists()
    assert "BLOCKED_CLICK" in inspector.log_path.read_text(encoding="utf-8")

    # 3. Blank black waveform canvas must fail OpenCV visual audit
    blank = np.zeros((600, 1200, 3), dtype=np.uint8)
    assert not audit_waveform_canvas(blank)["passed"]

    # 4. Over-compressed solid green bars must fail OpenCV visual audit
    solid_bars = np.zeros((600, 1200, 3), dtype=np.uint8)
    solid_bars[150:450, 400:1100] = (0, 220, 0)
    res_bars = audit_waveform_canvas(solid_bars)
    assert not res_bars["passed"]
    assert res_bars["solid_green_ratio"] >= 0.06

    # 5. Crisp multi-trace digital square waves must pass OpenCV visual audit
    crisp = np.zeros((600, 1200, 3), dtype=np.uint8)
    for row_idx, y_base in enumerate([160, 240, 320, 400]):
        period = 40 + row_idx * 24
        prev_y = y_base
        for x in range(380, 1120):
            high = ((x - 380) // (period // 2)) % 2 == 1
            cur_y = y_base - 22 if high else y_base
            crisp[cur_y, x] = (0, 235, 0)
            if cur_y != prev_y:
                y_lo, y_hi = min(cur_y, prev_y), max(cur_y, prev_y)
                crisp[y_lo : y_hi + 1, x] = (0, 235, 0)
            prev_y = cur_y
    res_crisp = audit_waveform_canvas(crisp)
    assert res_crisp["passed"], res_crisp
