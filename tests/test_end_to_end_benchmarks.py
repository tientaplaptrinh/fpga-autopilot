"""End-to-end verification tests checking all 3 real FPGA benchmarks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.hdl_models import AutopilotRunSummary

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT_DIR / "outputs"


@pytest.mark.parametrize(
    ("bench_name", "min_passed_vectors"),
    [
        ("adder_sub_7seg", 512),
        ("traffic_fsm", 200),
        ("uart_fifo_top", 66),
    ],
)
def test_benchmark_end_to_end_artifacts_verified(bench_name: str, min_passed_vectors: int) -> None:
    run_json = OUTPUTS_DIR / bench_name / "run_summary.json"
    assert run_json.exists(), f"Missing {run_json}; run `python -m cli run --spec benchmarks/lab_specs.yaml --all` first."

    summary = AutopilotRunSummary.model_validate_json(run_json.read_text(encoding="utf-8"))
    assert summary.overall_passed, f"Benchmark {bench_name} did not pass overall gate: {summary}"

    # 1. Zero lint warnings & zero inferred latches
    assert summary.lint_report.passed
    assert summary.lint_report.inferred_latches == 0
    assert summary.lint_report.error_count == 0
    assert summary.lint_report.warning_count == 0

    # 2. 100% bit-exact self-checking simulation pass rate
    assert summary.sim_result.compile_passed
    assert summary.sim_result.sim_passed
    assert summary.sim_result.failed_vectors == 0
    assert summary.sim_result.passed_vectors >= min_passed_vectors
    assert summary.sim_result.vcd_path and Path(summary.sim_result.vcd_path).exists()

    # 3. Real synthesis compilation & 0 synthesized latches
    assert summary.synthesis_report.compile_passed
    assert summary.synthesis_report.resources.inferred_latches == 0
    assert summary.synthesis_report.qpf_path and Path(summary.synthesis_report.qpf_path).exists()
    assert summary.synthesis_report.qsf_path and Path(summary.synthesis_report.qsf_path).exists()
    assert summary.synthesis_report.sdc_path and Path(summary.synthesis_report.sdc_path).exists()

    # 4. Verified GUI waveform screenshot
    wave_caps = [c for c in summary.visual_captures if c.capture_type == "gtkwave_waveform"]
    assert len(wave_caps) == 1
    assert wave_caps[0].visual_audit_passed
    assert Path(wave_caps[0].image_path).exists()

    # 5. Markdown & LaTeX (+ PDF) deliverables
    assert summary.summary_md_path and Path(summary.summary_md_path).exists()
    assert summary.latex_tex_path and Path(summary.latex_tex_path).exists()
    if summary.latex_pdf_path:
        assert Path(summary.latex_pdf_path).exists()

    # 6. Toolchain audit JSON exists
    tc_json = ROOT_DIR / "artifacts" / "toolchain_audit.json"
    assert tc_json.exists()
    tc_data = json.loads(tc_json.read_text(encoding="utf-8"))
    assert tc_data["capabilities"]["has_simulator"] is True
