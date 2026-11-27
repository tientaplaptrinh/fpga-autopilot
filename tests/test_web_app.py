"""Tests for FastAPI Web Studio endpoints and static GitHub Pages exporter."""

from __future__ import annotations

from fastapi.testclient import TestClient

from web_app.export_static import build_github_pages_bundle
from web_app.server import app


def test_web_api_status_runs_and_quartus_zip() -> None:
    client = TestClient(app)

    st = client.get("/api/status")
    assert st.status_code == 200
    assert st.json()["mode"] == "live_eda"

    runs_resp = client.get("/api/runs")
    assert runs_resp.status_code == 200
    runs = runs_resp.json()["runs"]
    names = {r["name"] for r in runs}
    assert {"adder_sub_7seg", "traffic_fsm", "uart_fifo_top"}.issubset(names)

    zip_resp = client.get("/api/runs/adder_sub_7seg/quartus.zip")
    assert zip_resp.status_code == 200
    assert zip_resp.headers["content-type"] == "application/zip"
    assert len(zip_resp.content) > 500


def test_github_pages_static_exporter() -> None:
    docs_dir = build_github_pages_bundle("https://testing-attractive-periods-telecom.trycloudflare.com")
    assert (docs_dir / "index.html").exists()
    assert (docs_dir / "data" / "static_bundle.json").exists()
    assert (docs_dir / "assets" / "adder_sub_7seg" / "lab_report.pdf").exists()
    assert (docs_dir / "assets" / "traffic_fsm" / "lab_report.pdf").exists()
    assert (docs_dir / "assets" / "uart_fifo_top" / "lab_report.pdf").exists()
