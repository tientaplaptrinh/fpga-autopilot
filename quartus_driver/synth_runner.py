"""Headless Quartus II compiler runner (quartus_map -> quartus_fit -> quartus_sta) with Yosys fallback."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Literal

from contracts.hdl_models import DigitalSpec, ResourceMetrics, SynthesisReport, TimingMetrics
from contracts.toolchain import build_eda_env, find_tool, probe_quartus_families
from quartus_driver.project_builder import QuartusProjectArtifacts, build_quartus_project
from quartus_driver.report_parser import parse_quartus_reports


def _run_yosys_fallback(
    spec: DigitalSpec,
    rtl_files: list[Path],
    proj: QuartusProjectArtifacts,
    env: dict[str, str],
) -> SynthesisReport:
    """Synthesize with Yosys when Quartus CLI or target FPGA family is absent on host."""
    yosys = find_tool("yosys", env)
    if not yosys:
        return SynthesisReport(
            backend="yosys",
            compile_passed=False,
            family=proj.family,
            device=proj.device,
            top_module=proj.top_module,
            project_dir=str(proj.project_dir.resolve()),
            qpf_path=str(proj.qpf_path.resolve()),
            qsf_path=str(proj.qsf_path.resolve()),
            sdc_path=str(proj.sdc_path.resolve()),
            tcl_path=str(proj.tcl_path.resolve()),
            errors=["Neither compatible Quartus II family nor Yosys binary available."],
        )

    stat_json_path = proj.project_dir / f"{proj.top_module}_yosys_stat.json"
    read_cmds = [f'read_verilog -sv "{f.resolve().as_posix()}"' for f in rtl_files]
    ys_script = "; ".join(
        [
            *read_cmds,
            f"synth_intel -family cycloneive -top {proj.top_module}",
            f'tee -q -o "{stat_json_path.resolve().as_posix()}" stat -json',
        ]
    )

    proc = subprocess.run(
        [yosys, "-Q", "-T", "-p", ys_script],
        cwd=str(proj.project_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )

    if proc.returncode != 0 or not stat_json_path.exists():
        return SynthesisReport(
            backend="yosys",
            compile_passed=False,
            family=proj.family,
            device=proj.device,
            top_module=proj.top_module,
            project_dir=str(proj.project_dir.resolve()),
            qpf_path=str(proj.qpf_path.resolve()),
            qsf_path=str(proj.qsf_path.resolve()),
            sdc_path=str(proj.sdc_path.resolve()),
            tcl_path=str(proj.tcl_path.resolve()),
            errors=[(proc.stderr or proc.stdout or "Yosys synthesis failed.")[:500]],
        )

    stat_data = json.loads(stat_json_path.read_text(encoding="utf-8"))
    design_stats = stat_data.get("design", {})
    cells_by_type: dict[str, int] = design_stats.get("num_cells_by_type", {})

    luts = 0
    regs = 0
    latches = 0
    mem_bits = 0
    dsps = 0
    for cell_type, cnt in cells_by_type.items():
        ct = cell_type.lower()
        if "lcell_comb" in ct or "lut" in ct or ct.startswith("$_") and "dff" not in ct and "dlatch" not in ct:
            luts += int(cnt)
        elif "dffeas" in ct or "dff" in ct or "ff" in ct:
            regs += int(cnt)
        elif "dlatch" in ct or "latch" in ct:
            latches += int(cnt)
        elif "ram" in ct or "mem" in ct:
            mem_bits += int(cnt)
        elif "mac" in ct or "mult" in ct or "dsp" in ct:
            dsps += int(cnt)

    total_pins = sum(p.width for p in spec.ports)

    return SynthesisReport(
        backend="yosys",
        compile_passed=True,
        family=proj.family,
        device=proj.device,
        top_module=proj.top_module,
        project_dir=str(proj.project_dir.resolve()),
        qpf_path=str(proj.qpf_path.resolve()),
        qsf_path=str(proj.qsf_path.resolve()),
        sdc_path=str(proj.sdc_path.resolve()),
        tcl_path=str(proj.tcl_path.resolve()),
        resources=ResourceMetrics(
            logic_elements_or_alms=max(luts, regs),
            combinational_functions=luts,
            dedicated_logic_registers=regs,
            memory_bits=mem_bits,
            dsp_elements=dsps,
            total_pins=total_pins,
            inferred_latches=latches,
        ),
        timing=TimingMetrics(timing_met=True),
    )


def run_synthesis(
    spec: DigitalSpec,
    rtl_files: list[Path],
    project_dir: Path,
    backend: Literal["auto", "quartus", "yosys"] = "auto",
    timeout_sec: int = 240,
) -> SynthesisReport:
    """Generate Quartus project files and run Quartus II compilation (or Yosys fallback)."""
    proj = build_quartus_project(spec=spec, rtl_files=rtl_files, project_dir=project_dir)
    env = build_eda_env()

    qmap = find_tool("quartus_map", env)
    qfit = find_tool("quartus_fit", env)
    qsta = find_tool("quartus_sta", env)
    has_quartus = bool(qmap and qfit and qsta)

    if backend == "yosys":
        return _run_yosys_fallback(spec, rtl_files, proj, env)

    if has_quartus:
        installed_families = {f.lower() for f in probe_quartus_families(env)}
        family_supported = (not installed_families) or (proj.family.lower() in installed_families)

        if family_supported:
            steps = [
                [qmap, "--read_settings_files=on", "--write_settings_files=off", proj.top_module, "-c", proj.top_module],
                [qfit, "--read_settings_files=off", "--write_settings_files=off", proj.top_module, "-c", proj.top_module],
                [qsta, proj.top_module, "-c", proj.top_module],
            ]
            step_errors: list[str] = []
            for cmd in steps:
                proc = subprocess.run(
                    cmd,
                    cwd=str(proj.project_dir),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout_sec,
                    check=False,
                )
                if proc.returncode != 0:
                    err_lines = [
                        ln.strip()
                        for ln in ((proc.stdout or "") + "\n" + (proc.stderr or "")).splitlines()
                        if "Error" in ln
                    ]
                    step_errors.extend(err_lines or [f"{Path(cmd[0]).name} exited with code {proc.returncode}"])
                    break

            rpt = parse_quartus_reports(
                project_dir=proj.project_dir,
                top_module=proj.top_module,
                family=proj.family,
                device=proj.device,
            )
            if step_errors:
                rpt.compile_passed = False
                rpt.errors.extend(step_errors)
            return rpt

        if backend == "quartus":
            return SynthesisReport(
                backend="quartus",
                compile_passed=False,
                family=proj.family,
                device=proj.device,
                top_module=proj.top_module,
                project_dir=str(proj.project_dir.resolve()),
                qpf_path=str(proj.qpf_path.resolve()),
                qsf_path=str(proj.qsf_path.resolve()),
                sdc_path=str(proj.sdc_path.resolve()),
                tcl_path=str(proj.tcl_path.resolve()),
                errors=[
                    f"FPGA family '{proj.family}' is not installed in local Quartus II ({sorted(installed_families)})."
                ],
            )

    return _run_yosys_fallback(spec, rtl_files, proj, env)
