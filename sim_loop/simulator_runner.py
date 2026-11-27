"""Isolated CLI runner for Icarus Verilog (iverilog/vvp), ModelSim (vlog/vsim), or Verilator."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path
from typing import Literal

from contracts.hdl_models import SimResult, VectorMismatch
from contracts.toolchain import build_eda_env, find_tool

_FAIL_RE = re.compile(
    r"\[FAIL\]\s*cycle=(\d+)\s+input=([0-9a-fA-FxXzZ]+)\s+exp=([0-9a-fA-FxXzZ]+)\s+got=([0-9a-fA-FxXzZ]+)"
)
_SUMMARY_RE = re.compile(r"\[SUMMARY\]\s*passed=(\d+)\s+failed=(\d+)")


def parse_sim_output(
    simulator: str,
    compile_passed: bool,
    timed_out: bool,
    stdout: str,
    stderr: str,
    vcd_path: Path | None,
    runtime_sec: float,
    sim_exit_ok: bool,
) -> SimResult:
    """Parse structured testbench logs ([FAIL] and [SUMMARY]) into SimResult."""
    mismatches: list[VectorMismatch] = []
    for m in _FAIL_RE.finditer(stdout):
        mismatches.append(
            VectorMismatch(
                cycle=int(m.group(1)),
                input_hex=m.group(2),
                expected_hex=m.group(3),
                got_hex=m.group(4),
            )
        )

    passed_vectors = 0
    failed_vectors = len(mismatches)
    has_summary = False
    sum_m = _SUMMARY_RE.search(stdout)
    if sum_m:
        has_summary = True
        passed_vectors = int(sum_m.group(1))
        failed_vectors = max(failed_vectors, int(sum_m.group(2)))

    total_vectors = passed_vectors + failed_vectors
    resolved_vcd = str(vcd_path.resolve()) if (vcd_path and vcd_path.exists()) else None

    sim_passed = (
        compile_passed
        and not timed_out
        and sim_exit_ok
        and has_summary
        and failed_vectors == 0
        and passed_vectors > 0
    )

    return SimResult(
        simulator=simulator,
        compile_passed=compile_passed,
        sim_passed=sim_passed,
        timed_out=timed_out,
        total_vectors=total_vectors,
        passed_vectors=passed_vectors,
        failed_vectors=failed_vectors,
        mismatches=mismatches,
        vcd_path=resolved_vcd,
        stdout=stdout,
        stderr=stderr,
        runtime_sec=round(runtime_sec, 4),
    )


def _run_iverilog(
    rtl_files: list[Path],
    tb_file: Path,
    work_dir: Path,
    tb_top: str,
    vcd_name: str,
    timeout_sec: float,
    env: dict[str, str],
) -> SimResult:
    iverilog = find_tool("iverilog", env)
    vvp = find_tool("vvp", env)
    if not iverilog or not vvp:
        raise RuntimeError("iverilog/vvp not found in environment.")

    # Stage RTL & TB into work_dir and pass relative space-free filenames (Windows iverilog requirement)
    import shutil

    staged_sources: list[str] = []
    for src_f in [*rtl_files, tb_file]:
        dst_f = work_dir / src_f.name
        if src_f.resolve() != dst_f.resolve():
            shutil.copy2(src_f, dst_f)
        staged_sources.append(dst_f.name)

    sim_bin_name = f"{tb_top}.vvp"
    compile_cmd = [
        iverilog,
        "-g2012",
        "-Wall",
        "-s",
        tb_top,
        "-o",
        sim_bin_name,
        *staged_sources,
    ]
    t0 = time.perf_counter()
    cproc = subprocess.run(
        compile_cmd,
        cwd=str(work_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=max(15.0, timeout_sec),
        check=False,
    )
    if cproc.returncode != 0:
        return SimResult(
            simulator="iverilog",
            compile_passed=False,
            sim_passed=False,
            stdout=cproc.stdout or "",
            stderr=cproc.stderr or "",
            runtime_sec=round(time.perf_counter() - t0, 4),
        )

    try:
        sproc = subprocess.run(
            [vvp, sim_bin_name],
            cwd=str(work_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        elapsed = time.perf_counter() - t0
        return parse_sim_output(
            simulator="iverilog",
            compile_passed=True,
            timed_out=False,
            stdout=sproc.stdout or "",
            stderr=(cproc.stderr or "") + (sproc.stderr or ""),
            vcd_path=work_dir / vcd_name,
            runtime_sec=elapsed,
            sim_exit_ok=(sproc.returncode == 0),
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - t0
        out_str = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err_str = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return parse_sim_output(
            simulator="iverilog",
            compile_passed=True,
            timed_out=True,
            stdout=out_str,
            stderr=err_str + f"\nSimulation timed out after {timeout_sec}s.",
            vcd_path=work_dir / vcd_name,
            runtime_sec=elapsed,
            sim_exit_ok=False,
        )


def _run_modelsim(
    rtl_files: list[Path],
    tb_file: Path,
    work_dir: Path,
    tb_top: str,
    vcd_name: str,
    timeout_sec: float,
    env: dict[str, str],
) -> SimResult:
    vlib = find_tool("vlib", env)
    vlog = find_tool("vlog", env)
    vsim = find_tool("vsim", env)
    if not (vlib and vlog and vsim):
        raise RuntimeError("ModelSim (vlib/vlog/vsim) not found in environment.")

    t0 = time.perf_counter()
    subprocess.run([vlib, "work"], cwd=str(work_dir), env=env, capture_output=True, text=True, timeout=15, check=False)
    cproc = subprocess.run(
        [vlog, "-sv", *[str(f.resolve()) for f in rtl_files], str(tb_file.resolve())],
        cwd=str(work_dir),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_sec,
        check=False,
    )
    if cproc.returncode != 0:
        return SimResult(
            simulator="modelsim",
            compile_passed=False,
            sim_passed=False,
            stdout=cproc.stdout or "",
            stderr=cproc.stderr or "",
            runtime_sec=round(time.perf_counter() - t0, 4),
        )

    try:
        sproc = subprocess.run(
            [vsim, "-c", "-do", "run -all; quit -f", f"work.{tb_top}"],
            cwd=str(work_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            check=False,
        )
        elapsed = time.perf_counter() - t0
        # Strip ModelSim '# ' transcript prefix on each line for clean parsing
        cleaned_lines = [
            ln[2:] if ln.startswith("# ") else ln
            for ln in (sproc.stdout or "").splitlines()
        ]
        cleaned_stdout = "\n".join(cleaned_lines)
        return parse_sim_output(
            simulator="modelsim",
            compile_passed=True,
            timed_out=False,
            stdout=cleaned_stdout,
            stderr=sproc.stderr or "",
            vcd_path=work_dir / vcd_name,
            runtime_sec=elapsed,
            sim_exit_ok=(sproc.returncode == 0),
        )
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - t0
        out_str = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return parse_sim_output(
            simulator="modelsim",
            compile_passed=True,
            timed_out=True,
            stdout=out_str,
            stderr=f"ModelSim timed out after {timeout_sec}s.",
            vcd_path=work_dir / vcd_name,
            runtime_sec=elapsed,
            sim_exit_ok=False,
        )


def run_simulation(
    rtl_files: list[Path] | Path,
    tb_file: Path,
    work_dir: Path,
    tb_top: str | None = None,
    vcd_filename: str | None = None,
    timeout_sec: float = 20.0,
    preferred_simulator: Literal["auto", "iverilog", "modelsim"] = "auto",
) -> SimResult:
    """Compile and run SystemVerilog RTL + self-checking testbench with strict timeout."""
    files = [rtl_files] if isinstance(rtl_files, Path) else list(rtl_files)
    work_dir.mkdir(parents=True, exist_ok=True)
    env = build_eda_env()

    resolved_tb_top = tb_top or tb_file.stem
    if vcd_filename is None:
        m = re.search(r'\$dumpfile\(\s*"([^"]+)"\s*\)', tb_file.read_text(encoding="utf-8"))
        vcd_filename = m.group(1) if m else f"{resolved_tb_top.removeprefix('tb_')}.vcd"

    if preferred_simulator in ("auto", "iverilog") and find_tool("iverilog", env) and find_tool("vvp", env):
        return _run_iverilog(files, tb_file, work_dir, resolved_tb_top, vcd_filename, timeout_sec, env)

    if preferred_simulator in ("auto", "modelsim") and find_tool("vsim", env):
        return _run_modelsim(files, tb_file, work_dir, resolved_tb_top, vcd_filename, timeout_sec, env)

    raise RuntimeError("No supported HDL simulator (iverilog or ModelSim vsim) detected on host.")
