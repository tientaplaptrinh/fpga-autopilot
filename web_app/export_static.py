"""Build standalone `docs/` static bundle for permanent GitHub Pages hosting."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from web_app.server import ARTIFACTS_DIR, OUTPUTS_DIR, ROOT_DIR, STATIC_DIR, serialize_run_detail


def build_github_pages_bundle(live_tunnel_url: str | None = None) -> Path:
    """Export static Web Studio + verified FPGA artifacts into `./docs/` for GitHub Pages."""
    docs_dir = ROOT_DIR / "docs"
    if docs_dir.exists():
        shutil.rmtree(docs_dir)
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / ".nojekyll").write_text("", encoding="utf-8")

    # 1. Copy static frontend files (rewriting /static/ -> ./static/ so subpath /fpga-autopilot/ works!)
    static_dst = docs_dir / "static"
    shutil.copytree(STATIC_DIR, static_dst)

    idx_html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    idx_html = idx_html.replace('href="/static/', 'href="./static/').replace('src="/static/', 'src="./static/')
    (docs_dir / "index.html").write_text(idx_html, encoding="utf-8")

    # 2. Serialize all benchmark runs & copy media/PDF/VCD/ZIP assets into docs/assets/
    assets_dir = docs_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    tc_file = ARTIFACTS_DIR / "toolchain_audit.json"
    toolchain = json.loads(tc_file.read_text(encoding="utf-8")) if tc_file.exists() else {}

    gui_log_file = ARTIFACTS_DIR / "gui_audit" / "gui_audit_log.jsonl"
    gui_events: list[dict[str, Any]] = []
    if gui_log_file.exists():
        for ln in gui_log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-60:]:
            if ln.strip():
                gui_events.append(json.loads(ln))

    priority = {"adder_sub_7seg": 0, "traffic_fsm": 1, "uart_fifo_top": 2}
    run_dirs = sorted(
        [d for d in OUTPUTS_DIR.iterdir() if d.is_dir()],
        key=lambda p: (priority.get(p.name, 99), p.name),
    )

    static_runs: list[dict[str, Any]] = []
    for rdir in run_dirs:
        detail = serialize_run_detail(rdir)
        if detail is None:
            continue
        sname = detail["name"]
        b_assets = assets_dir / sname
        b_assets.mkdir(parents=True, exist_ok=True)

        # Copy visual capture PNGs
        for cap in detail["captures"]:
            src_png = Path(cap["image_path"])
            if src_png.exists():
                shutil.copy2(src_png, b_assets / src_png.name)
                cap["url"] = f"./assets/{sname}/{src_png.name}"

        # Copy PDF & VCD
        summary_obj = detail["summary"]
        if summary_obj.get("latex_pdf_path") and Path(summary_obj["latex_pdf_path"]).exists():
            src_pdf = Path(summary_obj["latex_pdf_path"])
            shutil.copy2(src_pdf, b_assets / src_pdf.name)
            detail["downloads"]["pdf_url"] = f"./assets/{sname}/{src_pdf.name}"

        sim_vcd = summary_obj.get("sim_result", {}).get("vcd_path")
        if sim_vcd and Path(sim_vcd).exists():
            src_vcd = Path(sim_vcd)
            shutil.copy2(src_vcd, b_assets / src_vcd.name)
            detail["downloads"]["vcd_url"] = f"./assets/{sname}/{src_vcd.name}"

        # Build pre-packaged Quartus II project .zip
        zip_path = b_assets / f"{sname}_quartus_bundle.zip"
        with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
            for sub in ("rtl", "tb", "quartus"):
                sdir = rdir / sub
                if not sdir.is_dir():
                    continue
                for f in sdir.rglob("*"):
                    if f.is_file() and f.suffix.lower() in {".sv", ".v", ".qpf", ".qsf", ".sdc", ".tcl", ".rpt", ".sof"}:
                        zf.write(f, arcname=f"{sname}/{f.relative_to(rdir).as_posix()}")
            for root_f in ("summary.md", "lab_report.tex", "lab_report.pdf"):
                rf = rdir / root_f
                if rf.exists():
                    zf.write(rf, arcname=f"{sname}/{root_f}")
        detail["downloads"]["quartus_zip_url"] = f"./assets/{sname}/{zip_path.name}"

        static_runs.append(detail)

    data_dir = docs_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    bundle = {
        "mode": "static_showcase",
        "live_tunnel_url": live_tunnel_url or "",
        "toolchain": toolchain,
        "runs": static_runs,
        "gui_audit_events": gui_events,
    }
    (data_dir / "static_bundle.json").write_text(json.dumps(bundle, indent=2), encoding="utf-8")
    return docs_dir


if __name__ == "__main__":
    import sys

    tunnel = sys.argv[1] if len(sys.argv) > 1 else None
    out = build_github_pages_bundle(tunnel)
    print(f"Exported GitHub Pages bundle -> {out}")
