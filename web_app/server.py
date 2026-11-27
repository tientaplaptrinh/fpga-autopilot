"""FastAPI Live Hardware Execution Backend for Digital Design & Quartus II Autopilot."""

from __future__ import annotations

import io
import json
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from cli import execute_autopilot_for_spec, load_specs_from_yaml, spec_from_natural_prompt
from contracts.hdl_models import AutopilotRunSummary, DigitalSpec
from contracts.toolchain import audit_toolchain

ROOT_DIR = Path(__file__).resolve().parent.parent
OUTPUTS_DIR = ROOT_DIR / "outputs"
ARTIFACTS_DIR = ROOT_DIR / "artifacts"
STATIC_DIR = Path(__file__).resolve().parent / "static"

OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Digital Design & Quartus II Autopilot API",
    version="1.0.0",
    description="Live SystemVerilog RTL, Self-Checking TB, Quartus II Synthesis, GTKWave/RTL Viewer & LaTeX Engine",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

_JOB_LOCK = threading.Lock()
_JOBS: dict[str, dict[str, Any]] = {}


class PromptRunRequest(BaseModel):
    prompt: str = Field(min_length=4, max_length=4000)
    name: str = Field(default="custom_lab_top", min_length=2, max_length=64)
    board_preset: str = Field(default="DE2-115")
    enable_gui: bool = True
    enable_quartus_gui: bool = False


class YamlRunRequest(BaseModel):
    yaml_text: str = Field(min_length=10, max_length=30000)
    enable_gui: bool = True
    enable_quartus_gui: bool = False


def _find_spec_for_run(spec_name: str) -> DigitalSpec | None:
    bench_yaml = ROOT_DIR / "benchmarks" / "lab_specs.yaml"
    if bench_yaml.exists():
        for sp in load_specs_from_yaml(bench_yaml):
            if sp.name == spec_name:
                return sp
    custom_yaml = OUTPUTS_DIR / spec_name / f"{spec_name}_spec.yaml"
    if custom_yaml.exists():
        specs = load_specs_from_yaml(custom_yaml)
        if specs:
            return specs[0]
    return None


def serialize_run_detail(run_dir: Path, url_prefix: str = "") -> dict[str, Any] | None:
    """Build rich JSON payload for a completed benchmark run directory."""
    summary_file = run_dir / "run_summary.json"
    if not summary_file.exists():
        return None

    summary = AutopilotRunSummary.model_validate_json(summary_file.read_text(encoding="utf-8"))
    spec = _find_spec_for_run(summary.spec_name)

    rtl_sources: list[dict[str, str]] = []
    for rp in summary.rtl_paths:
        p = Path(rp)
        if p.exists():
            rtl_sources.append({"filename": p.name, "code": p.read_text(encoding="utf-8", errors="replace")})

    tb_code = ""
    tb_p = Path(summary.tb_path)
    if tb_p.exists():
        tb_code = tb_p.read_text(encoding="utf-8", errors="replace")

    qsf_code = ""
    if summary.synthesis_report.qsf_path and Path(summary.synthesis_report.qsf_path).exists():
        qsf_code = Path(summary.synthesis_report.qsf_path).read_text(encoding="utf-8", errors="replace")

    sdc_code = ""
    if summary.synthesis_report.sdc_path and Path(summary.synthesis_report.sdc_path).exists():
        sdc_code = Path(summary.synthesis_report.sdc_path).read_text(encoding="utf-8", errors="replace")

    tex_code = ""
    if summary.latex_tex_path and Path(summary.latex_tex_path).exists():
        tex_code = Path(summary.latex_tex_path).read_text(encoding="utf-8", errors="replace")

    md_code = ""
    if summary.summary_md_path and Path(summary.summary_md_path).exists():
        md_code = Path(summary.summary_md_path).read_text(encoding="utf-8", errors="replace")

    captures_out: list[dict[str, Any]] = []
    for cap in summary.visual_captures:
        cp = Path(cap.image_path)
        if cp.exists():
            rel = cp.resolve().relative_to(OUTPUTS_DIR.resolve()).as_posix()
            captures_out.append(
                {
                    **cap.model_dump(),
                    "url": f"{url_prefix}/files/outputs/{rel}",
                }
            )

    pdf_url = None
    if summary.latex_pdf_path and Path(summary.latex_pdf_path).exists():
        rel_pdf = Path(summary.latex_pdf_path).resolve().relative_to(OUTPUTS_DIR.resolve()).as_posix()
        pdf_url = f"{url_prefix}/files/outputs/{rel_pdf}"

    vcd_url = None
    if summary.sim_result.vcd_path and Path(summary.sim_result.vcd_path).exists():
        rel_vcd = Path(summary.sim_result.vcd_path).resolve().relative_to(OUTPUTS_DIR.resolve()).as_posix()
        vcd_url = f"{url_prefix}/files/outputs/{rel_vcd}"

    return {
        "name": summary.spec_name,
        "title": spec.title if spec else summary.spec_name,
        "description": spec.description if spec else "",
        "clock_freq_mhz": spec.clock_freq_mhz if spec else 50.0,
        "ports": [p.model_dump() for p in spec.ports] if spec else [],
        "fsm_states": [s.model_dump() for s in spec.fsm_states] if spec else [],
        "summary": summary.model_dump(),
        "sources": {
            "rtl": rtl_sources,
            "tb_filename": tb_p.name,
            "tb": tb_code,
            "qsf": qsf_code,
            "sdc": sdc_code,
            "tex": tex_code,
            "markdown": md_code,
        },
        "captures": captures_out,
        "downloads": {
            "pdf_url": pdf_url,
            "vcd_url": vcd_url,
            "quartus_zip_url": f"{url_prefix}/api/runs/{summary.spec_name}/quartus.zip",
        },
    }


@app.get("/api/status")
def get_status() -> dict[str, Any]:
    tc_path = ARTIFACTS_DIR / "toolchain_audit.json"
    if tc_path.exists():
        tc = json.loads(tc_path.read_text(encoding="utf-8"))
    else:
        tc = audit_toolchain(tc_path)
    active_jobs = [j for j in _JOBS.values() if j["status"] == "running"]
    return {
        "mode": "live_eda",
        "engine_busy": len(active_jobs) > 0,
        "toolchain": tc,
    }


@app.get("/api/runs")
def list_runs() -> dict[str, Any]:
    priority = {"adder_sub_7seg": 0, "traffic_fsm": 1, "uart_fifo_top": 2}
    dirs = sorted(
        [d for d in OUTPUTS_DIR.iterdir() if d.is_dir()],
        key=lambda p: (priority.get(p.name, 99), p.name),
    )
    items = []
    for d in dirs:
        detail = serialize_run_detail(d)
        if detail is not None:
            items.append(detail)
    return {"runs": items}


@app.get("/api/runs/{spec_name}/quartus.zip")
def download_quartus_zip(spec_name: str) -> StreamingResponse:
    run_dir = OUTPUTS_DIR / spec_name
    if not run_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Run '{spec_name}' not found.")

    mem_zip = io.BytesIO()
    with zipfile.ZipFile(mem_zip, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for sub in ("rtl", "tb", "quartus"):
            sdir = run_dir / sub
            if not sdir.is_dir():
                continue
            for f in sdir.rglob("*"):
                if f.is_file() and f.suffix.lower() in {".sv", ".v", ".qpf", ".qsf", ".sdc", ".tcl", ".rpt", ".sof"}:
                    arcname = f"{spec_name}/{f.relative_to(run_dir).as_posix()}"
                    zf.write(f, arcname=arcname)
        for root_f in ("summary.md", "lab_report.tex", "lab_report.pdf"):
            rf = run_dir / root_f
            if rf.exists():
                zf.write(rf, arcname=f"{spec_name}/{root_f}")

    mem_zip.seek(0)
    return StreamingResponse(
        mem_zip,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{spec_name}_quartus_bundle.zip"'},
    )


def _execute_job_worker(job_id: str, spec: DigitalSpec, enable_gui: bool, enable_quartus_gui: bool, prompt_ctx: str | None) -> None:
    job = _JOBS[job_id]
    job["logs"].append(f"[{time.strftime('%H:%M:%S')}] Acquiring hardware EDA engine lock for '{spec.name}'...")
    with _JOB_LOCK:
        t0 = time.perf_counter()
        try:
            job["logs"].append(f"[{time.strftime('%H:%M:%S')}] Phase 1–2: Generating SystemVerilog RTL, TB & running Verilator/Icarus simulation...")
            spec_out = OUTPUTS_DIR / spec.name / f"{spec.name}_spec.yaml"
            spec_out.parent.mkdir(parents=True, exist_ok=True)
            spec_out.write_text(yaml.safe_dump(spec.model_dump(), sort_keys=False), encoding="utf-8")

            summary = execute_autopilot_for_spec(
                spec=spec,
                enable_gui=enable_gui,
                enable_quartus_gui=enable_quartus_gui,
                compile_pdf=True,
                prompt_context=prompt_ctx,
            )
            elapsed = round(time.perf_counter() - t0, 2)
            job["logs"].append(
                f"[{time.strftime('%H:%M:%S')}] Completed in {elapsed}s — Overall={'PASS' if summary.overall_passed else 'FAIL'}, "
                f"Sim={summary.sim_result.passed_vectors}/{summary.sim_result.total_vectors}, "
                f"LEs/ALMs={summary.synthesis_report.resources.logic_elements_or_alms}, "
                f"Latches={summary.synthesis_report.resources.inferred_latches}."
            )
            job["status"] = "completed"
            job["spec_name"] = spec.name
            job["overall_passed"] = summary.overall_passed
        except Exception as exc:
            job["status"] = "failed"
            job["error"] = str(exc)
            job["logs"].append(f"[{time.strftime('%H:%M:%S')}] ERROR: {exc}")


@app.post("/api/run/prompt")
def trigger_prompt_run(req: PromptRunRequest) -> dict[str, Any]:
    board = req.board_preset if req.board_preset in ("DE2-115", "DE10-Lite", "DE1-SoC") else "DE2-115"
    spec = spec_from_natural_prompt(req.prompt, name=req.name, board_preset=board)
    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {
        "job_id": job_id,
        "status": "running",
        "spec_name": spec.name,
        "created_at": time.time(),
        "logs": [f"[{time.strftime('%H:%M:%S')}] Queued FPGA Autopilot run for '{spec.name}' ({board})"],
    }
    thread = threading.Thread(
        target=_execute_job_worker,
        args=(job_id, spec, req.enable_gui, req.enable_quartus_gui, req.prompt),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id, "spec_name": spec.name, "status": "running"}


@app.post("/api/run/yaml")
def trigger_yaml_run(req: YamlRunRequest) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(req.yaml_text)
        if isinstance(parsed, dict) and "benchmarks" in parsed:
            spec = DigitalSpec.model_validate(parsed["benchmarks"][0])
        else:
            spec = DigitalSpec.model_validate(parsed)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid DigitalSpec YAML: {exc}") from exc

    job_id = uuid.uuid4().hex[:12]
    _JOBS[job_id] = {
        "job_id": job_id,
        "status": "running",
        "spec_name": spec.name,
        "created_at": time.time(),
        "logs": [f"[{time.strftime('%H:%M:%S')}] Queued YAML spec '{spec.name}' ({spec.board_preset})"],
    }
    thread = threading.Thread(
        target=_execute_job_worker,
        args=(job_id, spec, req.enable_gui, req.enable_quartus_gui, None),
        daemon=True,
    )
    thread.start()
    return {"job_id": job_id, "spec_name": spec.name, "status": "running"}


@app.get("/api/jobs/{job_id}")
def get_job_status(job_id: str) -> dict[str, Any]:
    if job_id not in _JOBS:
        raise HTTPException(status_code=404, detail="Job not found")
    return _JOBS[job_id]


@app.get("/api/gui-audit-log")
def get_gui_audit_log() -> dict[str, Any]:
    log_file = ARTIFACTS_DIR / "gui_audit" / "gui_audit_log.jsonl"
    if not log_file.exists():
        return {"events": []}
    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
    events = []
    for ln in lines:
        if ln.strip():
            events.append(json.loads(ln))
    return {"events": events}


app.mount("/files/outputs", StaticFiles(directory=str(OUTPUTS_DIR)), name="outputs")


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
