"""End-to-end CLI orchestrator for Digital Design & Quartus II Autopilot."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import yaml

from contracts.hdl_models import AutopilotRunSummary, DigitalSpec, PortSpec, VisualCapture
from contracts.toolchain import audit_toolchain
from quartus_driver.gui_inspector import SafeGuiInspector
from quartus_driver.synth_runner import run_synthesis
from report_gen.lab_report_builder import build_lab_reports
from rtl_studio.sv_generator import generate_rtl
from rtl_studio.tb_generator import generate_testbench
from sim_loop.self_healer import run_self_healing_loop

ROOT_DIR = Path(__file__).resolve().parent


def load_specs_from_yaml(yaml_path: Path) -> list[DigitalSpec]:
    """Load either a single DigitalSpec or a `benchmarks:` list from YAML."""
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and "benchmarks" in raw:
        return [DigitalSpec.model_validate(item) for item in raw["benchmarks"]]
    if isinstance(raw, list):
        return [DigitalSpec.model_validate(item) for item in raw]
    if isinstance(raw, dict):
        return [DigitalSpec.model_validate(raw)]
    raise ValueError(f"Unsupported spec YAML structure in {yaml_path}")


def spec_from_natural_prompt(
    prompt_text: str,
    name: str,
    board_preset: str = "DE2-115",
) -> DigitalSpec:
    """Convert a natural-language university FPGA lab prompt into a validated DigitalSpec."""
    low = prompt_text.lower()
    clean_name = re.sub(r"[^A-Za-z0-9_]", "_", name).strip("_") or "custom_lab_top"

    if any(k in low for k in ("adder", "subtractor", "7-seg", "7seg", "seven-segment")):
        return DigitalSpec(
            name=clean_name,
            top_module=clean_name,
            title=prompt_text.strip()[:90],
            description=prompt_text.strip(),
            archetype="adder_sub_7seg",
            clock_port=None,
            reset_port=None,
            board_preset=board_preset,  # type: ignore[arg-type]
            ports=[
                PortSpec(name="a", direction="input", width=4, signed=True, description="Signed 4-bit input A"),
                PortSpec(name="b", direction="input", width=4, signed=True, description="Signed 4-bit input B"),
                PortSpec(name="sub_mode", direction="input", width=1, description="0=Add, 1=Subtract"),
                PortSpec(name="result", direction="output", width=4, signed=True, description="Signed 4-bit output"),
                PortSpec(name="cout", direction="output", width=1, description="Carry out"),
                PortSpec(name="overflow", direction="output", width=1, description="Signed overflow"),
                PortSpec(name="zero", direction="output", width=1, description="Zero flag"),
                PortSpec(name="seg_sign", direction="output", width=7, active_low=True, description="7-seg sign"),
                PortSpec(name="seg_mag", direction="output", width=7, active_low=True, description="7-seg magnitude"),
            ],
        )

    if any(k in low for k in ("uart", "baud", "transceiver", "rs232")):
        return DigitalSpec(
            name=clean_name,
            top_module=clean_name,
            title=prompt_text.strip()[:90],
            description=prompt_text.strip(),
            archetype="uart_fifo_top",
            board_preset=board_preset,  # type: ignore[arg-type]
            ports=[
                PortSpec(name="clk", direction="input", width=1, description="System clock"),
                PortSpec(name="rst_n", direction="input", width=1, active_low=True, description="Async reset"),
                PortSpec(name="wr_en", direction="input", width=1, description="TX FIFO write"),
                PortSpec(name="wr_data", direction="input", width=8, description="TX byte"),
                PortSpec(name="rd_en", direction="input", width=1, description="RX FIFO read"),
                PortSpec(name="rx_serial", direction="input", width=1, description="UART RX"),
                PortSpec(name="clr_err", direction="input", width=1, description="Clear error"),
                PortSpec(name="tx_serial", direction="output", width=1, description="UART TX"),
                PortSpec(name="rd_data", direction="output", width=8, description="RX byte"),
                PortSpec(name="tx_full", direction="output", width=1, description="TX full"),
                PortSpec(name="tx_empty", direction="output", width=1, description="TX empty"),
                PortSpec(name="rx_full", direction="output", width=1, description="RX full"),
                PortSpec(name="rx_empty", direction="output", width=1, description="RX empty"),
                PortSpec(name="tx_busy", direction="output", width=1, description="TX busy"),
                PortSpec(name="framing_error", direction="output", width=1, description="Framing error"),
            ],
        )

    if any(k in low for k in ("traffic", "intersection", "pedestrian")):
        return DigitalSpec(
            name=clean_name,
            top_module=clean_name,
            title=prompt_text.strip()[:90],
            description=prompt_text.strip(),
            archetype="traffic_fsm",
            board_preset=board_preset,  # type: ignore[arg-type]
            ports=[
                PortSpec(name="clk", direction="input", width=1, description="System clock"),
                PortSpec(name="rst_n", direction="input", width=1, active_low=True, description="Async reset"),
                PortSpec(name="ped_btn_raw", direction="input", width=1, description="Pedestrian button"),
                PortSpec(name="emergency_ovr", direction="input", width=1, description="Emergency override"),
                PortSpec(name="ns_light", direction="output", width=3, description="NS lights"),
                PortSpec(name="ew_light", direction="output", width=3, description="EW lights"),
                PortSpec(name="ped_walk", direction="output", width=1, description="Walk indicator"),
                PortSpec(name="countdown", direction="output", width=4, description="Countdown seconds"),
            ],
        )

    return DigitalSpec(
        name=clean_name,
        top_module=clean_name,
        title=prompt_text.strip()[:90],
        description=prompt_text.strip(),
        archetype="generic_sync",
        board_preset=board_preset,  # type: ignore[arg-type]
        ports=[
            PortSpec(name="clk", direction="input", width=1, description="System clock"),
            PortSpec(name="rst_n", direction="input", width=1, active_low=True, description="Async active-low reset"),
            PortSpec(name="din", direction="input", width=8, description="8-bit input bus"),
            PortSpec(name="dout", direction="output", width=8, description="8-bit registered output bus"),
        ],
    )


def execute_autopilot_for_spec(
    spec: DigitalSpec,
    base_output_dir: Path | None = None,
    audit_dir: Path | None = None,
    enable_gui: bool = True,
    enable_quartus_gui: bool = True,
    compile_pdf: bool = True,
    prompt_context: str | None = None,
) -> AutopilotRunSummary:
    """Execute Phases 1–4 end-to-end for a single DigitalSpec."""
    out_root = (base_output_dir or (ROOT_DIR / "outputs")) / spec.name
    rtl_dir = out_root / "rtl"
    tb_dir = out_root / "tb"
    sim_dir = out_root / "sim"
    quartus_dir = out_root / "quartus"
    gui_audit_dir = audit_dir or (ROOT_DIR / "artifacts" / "gui_audit")

    for d in (out_root, rtl_dir, tb_dir, sim_dir, quartus_dir, gui_audit_dir):
        d.mkdir(parents=True, exist_ok=True)

    top = spec.top_module or spec.name
    print(f"\n=== [{spec.name}] Phase 1: Generating SystemVerilog RTL & Self-Checking TB ===")
    rtl_files = generate_rtl(spec, rtl_dir, prompt_context=prompt_context)
    tb_file, _golden = generate_testbench(spec, tb_dir, vcd_filename=f"{top}.vcd")

    print(f"=== [{spec.name}] Phase 2: Running Static Lint & Closed-Loop Simulation ===")
    heal = run_self_healing_loop(
        rtl_files=rtl_files,
        tb_file=tb_file,
        work_dir=sim_dir,
        spec=spec,
        max_iterations=6,
        timeout_sec=20.0,
    )
    print(
        f"    Lint passed={heal.lint_report.passed} (latches={heal.lint_report.inferred_latches}), "
        f"Sim passed={heal.sim_result.sim_passed} ({heal.sim_result.passed_vectors}/{heal.sim_result.total_vectors})"
    )

    print(f"=== [{spec.name}] Phase 3A: Running Quartus II Synthesis & STA ({spec.board_preset}) ===")
    synth_report = run_synthesis(
        spec=spec,
        rtl_files=heal.rtl_files,
        project_dir=quartus_dir,
        backend="auto",
    )
    print(
        f"    Backend={synth_report.backend}, Compile={synth_report.compile_passed}, "
        f"LEs/ALMs={synth_report.resources.logic_elements_or_alms}, "
        f"Regs={synth_report.resources.dedicated_logic_registers}, "
        f"Latches={synth_report.resources.inferred_latches}, "
        f"Fmax={synth_report.timing.fmax_mhz}"
    )

    visual_captures: list[VisualCapture] = []
    if enable_gui and heal.sim_result.vcd_path:
        print(f"=== [{spec.name}] Phase 3B: Capturing & Auditing GTKWave Waveform ===")
        inspector = SafeGuiInspector(audit_dir=gui_audit_dir)
        wave_png = out_root / f"{top}_waveform.png"
        wave_cap = inspector.capture_gtkwave(
            spec=spec,
            vcd_path=Path(heal.sim_result.vcd_path),
            output_png_path=wave_png,
        )
        visual_captures.append(wave_cap)
        print(
            f"    GTKWave audit={wave_cap.visual_audit_passed} "
            f"(transitions={wave_cap.transition_columns_detected}, zoom_adj={wave_cap.zoom_adjustments})"
        )

        if (
            enable_quartus_gui
            and synth_report.backend == "quartus"
            and synth_report.compile_passed
            and synth_report.qpf_path
        ):
            print(f"=== [{spec.name}] Phase 3C: Capturing Quartus II RTL/FSM Viewers ===")
            has_fsm = bool(spec.fsm_states) or spec.archetype in ("traffic_fsm", "uart_fifo_top")
            q_caps = inspector.capture_quartus_viewers(
                spec=spec,
                qpf_path=Path(synth_report.qpf_path),
                output_dir=out_root,
                capture_fsm=has_fsm,
            )
            visual_captures.extend(q_caps)

    overall_ok = (
        heal.lint_report.passed
        and heal.lint_report.inferred_latches == 0
        and heal.sim_result.sim_passed
        and heal.sim_result.failed_vectors == 0
        and synth_report.compile_passed
        and synth_report.resources.inferred_latches == 0
        and (not enable_gui or any(c.capture_type == "gtkwave_waveform" and c.visual_audit_passed for c in visual_captures))
    )

    summary = AutopilotRunSummary(
        spec_name=spec.name,
        top_module=top,
        board_preset=spec.board_preset,
        rtl_paths=[str(p.resolve()) for p in heal.rtl_files],
        tb_path=str(tb_file.resolve()),
        healing_iterations=heal.iterations,
        lint_report=heal.lint_report,
        sim_result=heal.sim_result,
        synthesis_report=synth_report,
        visual_captures=visual_captures,
        overall_passed=overall_ok,
    )

    print(f"=== [{spec.name}] Phase 4: Generating Engineering Markdown & LaTeX/PDF Reports ===")
    _md, _tex, pdf_path, tex_issues = build_lab_reports(
        spec=spec,
        run=summary,
        output_dir=out_root,
        compile_pdf=compile_pdf,
    )
    if pdf_path:
        print(f"    Compiled PDF: {pdf_path} (LaTeX warnings={len(tex_issues)})")

    run_json = out_root / "run_summary.json"
    run_json.write_text(summary.model_dump_json(indent=2), encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Digital Design & Quartus II Autopilot CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_audit = sub.add_parser("audit", help="Audit local EDA toolchain and save artifacts/toolchain_audit.json")
    p_audit.add_argument(
        "--out",
        type=Path,
        default=ROOT_DIR / "artifacts" / "toolchain_audit.json",
        help="Path to output JSON",
    )

    p_run = sub.add_parser("run", help="Run end-to-end autopilot on YAML specification(s)")
    p_run.add_argument("--spec", type=Path, required=True, help="Path to YAML spec file")
    p_run.add_argument("--benchmark", type=str, default=None, help="Specific benchmark name to run")
    p_run.add_argument("--all", action="store_true", help="Run all benchmarks in YAML")
    p_run.add_argument("--no-gui", action="store_true", help="Skip desktop GUI capture")
    p_run.add_argument("--no-quartus-gui", action="store_true", help="Skip Quartus GUI viewer capture")
    p_run.add_argument("--no-pdf", action="store_true", help="Skip xelatex/pdflatex PDF build")

    p_prompt = sub.add_parser("prompt", help="Generate spec + full FPGA flow from a natural-language lab prompt")
    p_prompt.add_argument("text", type=str, help="University FPGA lab specification prompt")
    p_prompt.add_argument("--name", type=str, default="custom_lab_top", help="Top module name")
    p_prompt.add_argument(
        "--board",
        type=str,
        choices=["DE2-115", "DE10-Lite", "DE1-SoC"],
        default="DE2-115",
        help="Target student FPGA board preset",
    )
    p_prompt.add_argument("--no-gui", action="store_true", help="Skip desktop GUI capture")
    p_prompt.add_argument("--no-quartus-gui", action="store_true", help="Skip Quartus GUI viewer capture")

    args = parser.parse_args(argv)

    if args.command == "audit":
        report: dict[str, Any] = audit_toolchain(args.out)
        print(f"Saved toolchain audit -> {args.out}")
        for tname, tinfo in report["tools"].items():
            status = "FOUND" if tinfo["available"] else "MISSING"
            print(f"  {tname:<14} : {status:<7} {tinfo['path'] or ''}")
        return 0

    if args.command == "run":
        specs = load_specs_from_yaml(args.spec)
        if args.benchmark:
            specs = [s for s in specs if s.name == args.benchmark]
            if not specs:
                print(f"Benchmark '{args.benchmark}' not found in {args.spec}", file=sys.stderr)
                return 1
        elif not args.all:
            specs = specs[:1]

        all_ok = True
        for sp in specs:
            res = execute_autopilot_for_spec(
                spec=sp,
                enable_gui=not args.no_gui,
                enable_quartus_gui=not args.no_quartus_gui,
                compile_pdf=not args.no_pdf,
            )
            if not res.overall_passed:
                all_ok = False
        return 0 if all_ok else 1

    if args.command == "prompt":
        spec = spec_from_natural_prompt(args.text, name=args.name, board_preset=args.board)
        spec_out = ROOT_DIR / "outputs" / spec.name / f"{spec.name}_spec.yaml"
        spec_out.parent.mkdir(parents=True, exist_ok=True)
        spec_out.write_text(yaml.safe_dump(spec.model_dump(), sort_keys=False), encoding="utf-8")
        res = execute_autopilot_for_spec(
            spec=spec,
            enable_gui=not args.no_gui,
            enable_quartus_gui=not args.no_quartus_gui,
            prompt_context=args.text,
        )
        return 0 if res.overall_passed else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
