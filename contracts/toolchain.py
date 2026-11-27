"""EDA Toolchain discovery, PATH injection, and JSON audit generator."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

EXTRA_SEARCH_DIRS: list[str] = [
    r"C:\msys64\ucrt64\bin",
    r"C:\altera\quartus\bin64",
    r"C:\altera\quartus\bin",
    r"C:\altera\13.0sp1\quartus\bin64",
    r"C:\intelFPGA_lite\23.1std\quartus\bin64",
    r"C:\intelFPGA_lite\20.1\quartus\bin64",
    r"C:\intelFPGA_lite\18.1\quartus\bin64",
    r"C:\altera\modelsim_ase\win32aloem",
    r"C:\iverilog\bin",
    r"C:\iverilog\gtkwave\bin",
    str(Path.home() / "AppData" / "Local" / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64"),
]

REQUIRED_TOOLS: list[str] = [
    "quartus_sh",
    "quartus_map",
    "quartus_fit",
    "quartus_sta",
    "quartus",
    "vsim",
    "vlog",
    "vlib",
    "iverilog",
    "vvp",
    "verilator",
    "yosys",
    "gtkwave",
    "xelatex",
    "pdflatex",
]


def build_eda_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    """Return environment dictionary with UCRT64 and detected EDA binary directories prioritized on PATH."""
    env = dict(base_env if base_env is not None else os.environ)
    raw_parts = [p for p in env.get("PATH", "").split(os.pathsep) if p]

    # Filter out conflicting MSVCRT mingw64 paths so UCRT64 binaries never load incompatible C++ runtimes
    conflict_dirs = {
        os.path.normcase(os.path.normpath(r"C:\mingw64\bin")),
        os.path.normcase(os.path.normpath(r"C:\msys64\mingw64\bin")),
    }

    ordered_parts: list[str] = []
    seen_norm: set[str] = set()

    for d in [*EXTRA_SEARCH_DIRS, *raw_parts]:
        norm_d = os.path.normcase(os.path.normpath(d))
        if norm_d in conflict_dirs or norm_d in seen_norm:
            continue
        if d in EXTRA_SEARCH_DIRS and not os.path.isdir(d):
            continue
        ordered_parts.append(d)
        seen_norm.add(norm_d)

    env["PATH"] = os.pathsep.join(ordered_parts)
    if os.path.isdir(r"C:\msys64\ucrt64\share"):
        env.setdefault("XDG_DATA_DIRS", r"C:\msys64\ucrt64\share")
    if os.path.isdir(r"C:\msys64\ucrt64\share\verilator"):
        env.setdefault("VERILATOR_ROOT", r"C:\msys64\ucrt64\share\verilator")
    return env


def find_tool(name: str, env: dict[str, str] | None = None) -> str | None:
    """Locate an executable across PATH and standard Windows/Linux EDA directories."""
    eff_env = build_eda_env(env)
    found = shutil.which(name, path=eff_env.get("PATH"))
    if found:
        return str(Path(found).resolve())
    # Verilator on MSYS2 Windows can also invoke verilator_bin.exe directly
    if name == "verilator":
        alt = shutil.which("verilator_bin", path=eff_env.get("PATH"))
        if alt:
            return str(Path(alt).resolve())
    return None


def _probe_version(tool_name: str, tool_path: str, env: dict[str, str]) -> str:
    """Best-effort version string probe with short timeout."""
    version_flags: dict[str, list[str]] = {
        "quartus_sh": ["--version"],
        "quartus_map": ["--version"],
        "quartus_fit": ["--version"],
        "quartus_sta": ["--version"],
        "quartus": ["--version"],
        "vsim": ["-version"],
        "vlog": ["-version"],
        "vlib": ["-version"],
        "iverilog": ["-V"],
        "vvp": ["-V"],
        "verilator": ["--version"],
        "yosys": ["-V"],
        "gtkwave": ["--version"],
        "xelatex": ["--version"],
        "pdflatex": ["--version"],
    }
    args = [tool_path] + version_flags.get(tool_name, ["--version"])
    # On Windows, verilator perl wrapper may need perl or verilator_bin.exe
    if tool_name == "verilator" and tool_path.lower().endswith("verilator"):
        perl = shutil.which("perl", path=env.get("PATH"))
        if perl:
            args = [perl, tool_path, "--version"]
    try:
        proc = subprocess.run(
            args,
            env=env,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        out = (proc.stdout or proc.stderr or "").strip()
        first_line = next((ln.strip() for ln in out.splitlines() if ln.strip()), "")
        return first_line[:200]
    except Exception as exc:
        return f"detected ({exc.__class__.__name__})"


def probe_quartus_families(env: dict[str, str] | None = None) -> list[str]:
    """Return list of FPGA device families installed in local Quartus II."""
    eff_env = build_eda_env(env)
    qsh = find_tool("quartus_sh", eff_env)
    if not qsh:
        return []
    tcl_cmd = "foreach f [get_family_list] { post_message $f }"
    try:
        proc = subprocess.run(
            [qsh, "--tcl_eval", tcl_cmd],
            env=eff_env,
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
        families: list[str] = []
        for line in (proc.stdout + "\n" + proc.stderr).splitlines():
            if "Info:" in line:
                fam = line.split("Info:", 1)[1].strip()
                if fam and not fam.startswith("****"):
                    families.append(fam)
        return families
    except Exception:
        return []


def audit_toolchain(output_json_path: Path | None = None) -> dict[str, Any]:
    """Audit all EDA binaries on the host and optionally persist toolchain_audit.json."""
    env = build_eda_env()
    tools_report: dict[str, dict[str, Any]] = {}
    for tool in REQUIRED_TOOLS:
        # Prefer verilator_bin.exe on Windows MSYS2 so subprocess doesn't require MSYS perl
        path = None
        if tool == "verilator":
            vbin = shutil.which("verilator_bin", path=env.get("PATH"))
            path = str(Path(vbin).resolve()) if vbin else find_tool(tool, env)
        else:
            path = find_tool(tool, env)

        if path:
            tools_report[tool] = {
                "available": True,
                "path": path,
                "version": _probe_version(tool, path, env),
            }
        else:
            tools_report[tool] = {
                "available": False,
                "path": None,
                "version": None,
            }

    quartus_families = probe_quartus_families(env)
    summary: dict[str, Any] = {
        "os": os.name,
        "platform": os.sys.platform,
        "tools": tools_report,
        "quartus_installed_families": quartus_families,
        "capabilities": {
            "has_simulator": any(
                tools_report[t]["available"] for t in ("iverilog", "verilator", "vsim")
            ),
            "has_quartus_cli": all(
                tools_report[t]["available"]
                for t in ("quartus_sh", "quartus_map", "quartus_fit", "quartus_sta")
            ),
            "has_quartus_gui": tools_report["quartus"]["available"],
            "has_yosys": tools_report["yosys"]["available"],
            "has_gtkwave": tools_report["gtkwave"]["available"],
            "has_latex": any(
                tools_report[t]["available"] for t in ("xelatex", "pdflatex")
            ),
        },
    }

    if output_json_path is not None:
        output_json_path.parent.mkdir(parents=True, exist_ok=True)
        output_json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    return summary
