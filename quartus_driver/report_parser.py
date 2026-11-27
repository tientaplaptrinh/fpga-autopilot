"""Parser for Quartus II .map.rpt, .fit.rpt, and .sta.rpt hardware reports."""

from __future__ import annotations

import re
from pathlib import Path

from contracts.hdl_models import ResourceMetrics, SynthesisReport, TimingMetrics


def _extract_first_int(text: str, patterns: list[str]) -> int | None:
    """Extract first integer from semicolon-delimited Quartus summary rows."""
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE | re.MULTILINE)
        if m:
            raw = m.group(1).replace(",", "").strip()
            int_m = re.match(r"(\d+)", raw)
            if int_m:
                return int(int_m.group(1))
    return None


def _count_inferred_latches_in_map(map_text: str) -> int:
    """Count inferred latches reported in Quartus Analysis & Synthesis (.map.rpt)."""
    latch_count = 0

    # 1. Check explicit Warning (10240) / Warning (10631) inferred latch diagnostics
    warn_matches = re.findall(
        r"Warning\s*\((?:10240|102300|10631)\)[^\n]*inferring latch",
        map_text,
        re.IGNORECASE,
    )
    latch_count += len(warn_matches)

    # 2. Check summary line `; Total latches ; <N> ;` if present
    summary_latches = _extract_first_int(
        map_text,
        [r";\s*Number of user-specified and inferred latches\s*;\s*([0-9,]+)"],
    )
    if summary_latches is not None:
        latch_count = max(latch_count, summary_latches)

    # 3. Parse `; User-Specified and Inferred Latches ;` table rows
    table_m = re.search(
        r";\s*User-Specified and Inferred Latches\s*;.*?\n\+[-+]+\+\n(.*?)\n\+[-+]+\+",
        map_text,
        re.DOTALL | re.IGNORECASE,
    )
    if table_m:
        body = table_m.group(1)
        rows = [
            ln
            for ln in body.splitlines()
            if ln.strip().startswith(";") and "Latch Name" not in ln and "---" not in ln
        ]
        latch_count = max(latch_count, len(rows))

    return latch_count


def _parse_fmax_from_sta(sta_text: str) -> tuple[float | None, float | None]:
    """Extract worst-case Fmax and Restricted Fmax (minimum across all timing models) from .sta.rpt."""
    # Match rows inside Fmax Summary tables: `; 254.19 MHz ; 250.0 MHz ; clk ;`
    fmax_vals: list[float] = []
    rfmax_vals: list[float] = []

    section_re = re.compile(
        r";\s*(?:Slow|Fast)?[^;\n]*Fmax Summary\s*;.*?\n(\+[-+]+\+.*?\n\+[-+]+\+\n.*?\n\+[-+]+\+)",
        re.DOTALL | re.IGNORECASE,
    )
    row_re = re.compile(
        r";\s*([0-9]+(?:\.[0-9]+)?)\s*MHz\s*;\s*([0-9]+(?:\.[0-9]+)?)\s*MHz\s*;\s*([^;\n]+?)\s*;",
        re.IGNORECASE,
    )

    blocks = [m.group(1) for m in section_re.finditer(sta_text)]
    search_targets = blocks if blocks else [sta_text]

    for blk in search_targets:
        for rm in row_re.finditer(blk):
            fmax_vals.append(float(rm.group(1)))
            rfmax_vals.append(float(rm.group(2)))

    worst_fmax = min(fmax_vals) if fmax_vals else None
    worst_rfmax = min(rfmax_vals) if rfmax_vals else None
    return worst_fmax, worst_rfmax


def _parse_worst_slack(sta_text: str, kind: str) -> float | None:
    """Extract worst-case Setup/Hold/Recovery/Removal slack across all corners in .sta.rpt."""
    # Look for `<Corner> <kind> Summary` table followed by `; <clock> ; <slack> ; <tns> ;`
    slacks: list[float] = []
    sec_re = re.compile(
        rf";\s*[^;\n]*\b{re.escape(kind)}\s+Summary\s*;.*?\n\+[-+]+\+\n;\s*Clock\s*;\s*Slack.*?\n\+[-+]+\+\n(.*?)\n\+[-+]+\+",
        re.DOTALL | re.IGNORECASE,
    )
    row_re = re.compile(r"^;\s*[^;]+;\s*([+-]?[0-9]+(?:\.[0-9]+)?)\s*;", re.MULTILINE)
    for sm in sec_re.finditer(sta_text):
        for rm in row_re.finditer(sm.group(1)):
            slacks.append(float(rm.group(1)))
    return min(slacks) if slacks else None


def parse_quartus_reports(
    project_dir: Path,
    top_module: str,
    family: str = "",
    device: str = "",
    map_rpt_path: Path | None = None,
    fit_rpt_path: Path | None = None,
    sta_rpt_path: Path | None = None,
) -> SynthesisReport:
    """Parse Quartus II .map.rpt, .fit.rpt, and .sta.rpt into a SynthesisReport."""
    out_dir = project_dir / "output_files"
    m_path = map_rpt_path or (out_dir / f"{top_module}.map.rpt")
    f_path = fit_rpt_path or (out_dir / f"{top_module}.fit.rpt")
    s_path = sta_rpt_path or (out_dir / f"{top_module}.sta.rpt")

    map_text = m_path.read_text(encoding="utf-8", errors="replace") if m_path.exists() else ""
    fit_text = f_path.read_text(encoding="utf-8", errors="replace") if f_path.exists() else ""
    sta_text = s_path.read_text(encoding="utf-8", errors="replace") if s_path.exists() else ""

    combined_res_text = fit_text + "\n" + map_text

    # Extract Family & Device from report if not explicitly passed
    if not family:
        fm = re.search(r";\s*Family\s*;\s*([^;\n]+?)\s*;", combined_res_text)
        family = fm.group(1).strip() if fm else "Unknown"
    if not device:
        dm = re.search(r";\s*Device\s*;\s*([^;\n]+?)\s*;", combined_res_text)
        device = dm.group(1).strip() if dm else "Unknown"

    le_or_alms = _extract_first_int(
        combined_res_text,
        [
            r";\s*Total logic elements\s*;\s*([0-9,]+)",
            r";\s*Logic utilization \(in ALMs\)\s*;\s*([0-9,]+)",
            r";\s*Estimate of Logic utilization \(ALMs needed\)\s*;\s*([0-9,]+)",
        ],
    ) or 0

    comb_funcs = _extract_first_int(
        combined_res_text,
        [
            r";\s*Total combinational functions\s*;\s*([0-9,]+)",
            r";\s*Combinational ALUT usage for logic\s*;\s*([0-9,]+)",
        ],
    ) or 0

    ded_regs = _extract_first_int(
        combined_res_text,
        [
            r";\s*Dedicated logic registers\s*;\s*([0-9,]+)",
            r";\s*Total registers\s*;\s*([0-9,]+)",
        ],
    ) or 0

    mem_bits = _extract_first_int(
        combined_res_text,
        [
            r";\s*Total memory bits\s*;\s*([0-9,]+)",
            r";\s*Total block memory bits\s*;\s*([0-9,]+)",
        ],
    ) or 0

    dsp_elems = _extract_first_int(
        combined_res_text,
        [
            r";\s*Embedded Multiplier 9-bit elements\s*;\s*([0-9,]+)",
            r";\s*Total DSP Blocks\s*;\s*([0-9,]+)",
        ],
    ) or 0

    total_pins = _extract_first_int(
        combined_res_text,
        [r";\s*Total pins\s*;\s*([0-9,]+)"],
    ) or 0

    inferred_latches = _count_inferred_latches_in_map(map_text)

    fmax_mhz, rfmax_mhz = _parse_fmax_from_sta(sta_text)
    setup_slack = _parse_worst_slack(sta_text, "Setup")
    hold_slack = _parse_worst_slack(sta_text, "Hold")
    rec_slack = _parse_worst_slack(sta_text, "Recovery")
    rem_slack = _parse_worst_slack(sta_text, "Removal")

    # Extract combinational propagation delay if virtual clock / set_max_delay was used without register-to-register Fmax
    max_comb_ns: float | None = None
    if fmax_mhz is None and setup_slack is not None:
        # Check period of virt_clk in sta_text if present
        pm = re.search(r";\s*virt_clk\s*;\s*Base\s*;\s*([0-9]+(?:\.[0-9]+)?)\s*;", sta_text)
        if pm:
            period = float(pm.group(1))
            max_comb_ns = round(max(0.0, period - setup_slack), 3)

    timing_met = True
    for slk in (setup_slack, hold_slack, rec_slack, rem_slack):
        if slk is not None and slk < 0.0:
            timing_met = False

    errors: list[str] = []
    warnings: list[str] = []
    for line in (map_text + "\n" + fit_text + "\n" + sta_text).splitlines():
        s = line.strip()
        if s.startswith("Error (") or s.startswith("Critical Warning ("):
            errors.append(s)
        elif "inferring latch" in s.lower():
            warnings.append(s)

    compile_passed = bool(m_path.exists() and f_path.exists() and s_path.exists()) and not any(
        e.startswith("Error (") for e in errors
    )

    qpf = project_dir / f"{top_module}.qpf"
    qsf = project_dir / f"{top_module}.qsf"
    sdc = project_dir / f"{top_module}.sdc"
    tcl = project_dir / f"compile_{top_module}.tcl"

    return SynthesisReport(
        backend="quartus",
        compile_passed=compile_passed,
        family=family,
        device=device,
        top_module=top_module,
        project_dir=str(project_dir.resolve()),
        qpf_path=str(qpf.resolve()) if qpf.exists() else None,
        qsf_path=str(qsf.resolve()) if qsf.exists() else None,
        sdc_path=str(sdc.resolve()) if sdc.exists() else None,
        tcl_path=str(tcl.resolve()) if tcl.exists() else None,
        map_rpt_path=str(m_path.resolve()) if m_path.exists() else None,
        fit_rpt_path=str(f_path.resolve()) if f_path.exists() else None,
        sta_rpt_path=str(s_path.resolve()) if s_path.exists() else None,
        resources=ResourceMetrics(
            logic_elements_or_alms=le_or_alms,
            combinational_functions=comb_funcs,
            dedicated_logic_registers=ded_regs,
            memory_bits=mem_bits,
            dsp_elements=dsp_elems,
            total_pins=total_pins,
            inferred_latches=inferred_latches,
        ),
        timing=TimingMetrics(
            fmax_mhz=fmax_mhz,
            restricted_fmax_mhz=rfmax_mhz,
            worst_setup_slack_ns=setup_slack,
            worst_hold_slack_ns=hold_slack,
            worst_recovery_slack_ns=rec_slack,
            worst_removal_slack_ns=rem_slack,
            max_comb_delay_ns=max_comb_ns,
            timing_met=timing_met,
        ),
        warnings=warnings[:50],
        errors=errors[:50],
    )
