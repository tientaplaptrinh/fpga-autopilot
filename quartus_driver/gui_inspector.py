"""Safe Desktop Mouse & Keyboard GUI Inspector for GTKWave and Quartus II Viewers.

Safety Guarantees:
1. `pyautogui.FAILSAFE = True` globally (moving mouse to (0, 0) immediately aborts).
2. Strict Window Confinement: every mouse/keyboard interaction verifies the target
   window belongs to an allowlisted EDA tool (`gtkwave`, `quartus`, `rtl viewer`,
   `state machine viewer`, `vsim`) and blocks any coordinate outside its bounding box.
3. Full audit trail: every action, UI region detection, and screenshot is recorded
   in `./artifacts/gui_audit/gui_audit_log.jsonl`.
"""

from __future__ import annotations

import contextlib
import ctypes
import ctypes.wintypes
import json
import math
import os
import re
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pyautogui
from PIL import ImageGrab

from contracts.hdl_models import DigitalSpec, VisualCapture
from contracts.toolchain import build_eda_env, find_tool

# Mandatory Safety Rule #1: Global PyAutoGUI FailSafe
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.08

# Enable Per-Monitor DPI Awareness on Windows so Win32 rects match physical pixels 1:1
if os.name == "nt":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        with contextlib.suppress(AttributeError, OSError):
            ctypes.windll.user32.SetProcessDPIAware()

ALLOWED_EDA_TOOLS = (
    "gtkwave",
    "quartus",
    "rtl viewer",
    "state machine viewer",
    "modelsim",
    "vsim",
)


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.wintypes.LONG),
        ("biHeight", ctypes.wintypes.LONG),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.wintypes.LONG),
        ("biYPelsPerMeter", ctypes.wintypes.LONG),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]


class WindowConfinementError(RuntimeError):
    """Raised whenever an attempted GUI action violates EDA window confinement."""


def verify_point_in_bbox(
    x: int,
    y: int,
    bbox: tuple[int, int, int, int],
    window_title: str,
    margin: int = 4,
) -> None:
    """Enforce Strict Window Confinement for target coordinate (x, y)."""
    if not pyautogui.FAILSAFE:
        raise WindowConfinementError("CRITICAL: pyautogui.FAILSAFE was disabled! Aborting GUI action.")

    title_lower = window_title.lower()
    if not any(tok in title_lower for tok in ALLOWED_EDA_TOOLS):
        raise WindowConfinementError(
            f"Target window '{window_title}' is not an allowlisted EDA tool {ALLOWED_EDA_TOOLS}."
        )

    left, top, width, height = bbox
    if width <= margin * 2 or height <= margin * 2:
        raise WindowConfinementError(f"Window '{window_title}' bounding box {bbox} is too small.")

    min_x = left + margin
    max_x = left + width - margin
    min_y = top + margin
    max_y = top + height - margin
    if not (min_x <= x <= max_x and min_y <= y <= max_y):
        raise WindowConfinementError(
            f"Blocked out-of-bounds GUI coordinate ({x}, {y}) outside '{window_title}' bbox={bbox}."
        )


def _is_interactive_desktop() -> bool:
    """Detect whether current Win32 process has an interactive input desktop vs background HDESK."""
    if os.name != "nt":
        return True
    try:
        ImageGrab.grab(bbox=(0, 0, 8, 8))
        pos = pyautogui.position()
        return (pos.x, pos.y) not in pyautogui.FAILSAFE_POINTS
    except OSError:
        return False


def _enum_win32_windows() -> list[dict[str, Any]]:
    """Query visible top-level Win32 windows with HWND, PID, title, and screen bounding box."""
    if os.name != "nt":
        return []

    user32 = ctypes.windll.user32
    results: list[dict[str, Any]] = []

    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def _callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        title = buf.value.strip()
        if not title:
            return True

        rect = ctypes.wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 40 or height <= 40:
            return True

        pid = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        results.append(
            {
                "hwnd": int(hwnd),
                "pid": int(pid.value),
                "title": title,
                "bbox": (int(rect.left), int(rect.top), int(width), int(height)),
            }
        )
        return True

    user32.EnumWindows(WNDENUMPROC(_callback), 0)
    return results


def _focus_and_position_win32(
    hwnd: int,
    x: int = 40,
    y: int = 40,
    w: int = 1440,
    h: int = 860,
) -> tuple[int, int, int, int]:
    """Restore, resize, and bring target EDA HWND to foreground safely."""
    user32 = ctypes.windll.user32
    SW_RESTORE = 9
    user32.ShowWindow(hwnd, SW_RESTORE)
    scr_w, scr_h = pyautogui.size()
    eff_w = min(w, max(640, scr_w - x - 20))
    eff_h = min(h, max(480, scr_h - y - 60))
    user32.MoveWindow(hwnd, x, y, eff_w, eff_h, True)
    with contextlib.suppress(OSError):
        user32.SetForegroundWindow(hwnd)
    time.sleep(0.35)
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    return (
        int(rect.left),
        int(rect.top),
        int(rect.right - rect.left),
        int(rect.bottom - rect.top),
    )


def _grab_hwnd_printwindow(hwnd: int, width: int, height: int) -> np.ndarray:
    """Capture rendered Win32 HWND surface directly via PrintWindow(PW_RENDERFULLCONTENT)."""
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hdc_win = user32.GetWindowDC(hwnd)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_win)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_win, width, height)
    old_obj = gdi32.SelectObject(hdc_mem, hbmp)
    try:
        ok = user32.PrintWindow(hwnd, hdc_mem, 2)
        if not ok:
            user32.PrintWindow(hwnd, hdc_mem, 0)
        bmi = _BITMAPINFOHEADER(
            ctypes.sizeof(_BITMAPINFOHEADER),
            width,
            -height,
            1,
            32,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        buf = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(hdc_mem, hbmp, 0, height, buf, ctypes.byref(bmi), 0)
        arr = np.frombuffer(buf, dtype=np.uint8).reshape((height, width, 4))[:, :, :3].copy()
        return arr
    finally:
        gdi32.SelectObject(hdc_mem, old_obj)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_win)


def _post_click_client(hwnd: int, cx: int, cy: int) -> None:
    """Deliver mouse move + left click directly to target HWND client coordinates."""
    user32 = ctypes.windll.user32
    lparam = ((cy & 0xFFFF) << 16) | (cx & 0xFFFF)
    user32.PostMessageW(hwnd, 0x0200, 0, lparam)  # WM_MOUSEMOVE
    time.sleep(0.04)
    user32.PostMessageW(hwnd, 0x0201, 1, lparam)  # WM_LBUTTONDOWN
    time.sleep(0.05)
    user32.PostMessageW(hwnd, 0x0202, 0, lparam)  # WM_LBUTTONUP


def _post_click_screen_confined(root_hwnd: int, sx: int, sy: int) -> tuple[int, tuple[int, int]]:
    """Resolve child control inside root_hwnd at screen (sx, sy) and post confined click."""
    user32 = ctypes.windll.user32
    pt = ctypes.wintypes.POINT(sx, sy)
    target = root_hwnd
    while True:
        cpt = ctypes.wintypes.POINT(pt.x, pt.y)
        user32.ScreenToClient(target, ctypes.byref(cpt))
        child = user32.ChildWindowFromPointEx(target, cpt, 1)  # CWP_SKIPINVISIBLE
        if not child or child == target:
            _post_click_client(target, int(cpt.x), int(cpt.y))
            return int(target), (int(cpt.x), int(cpt.y))
        target = child


def parse_vcd_signals_and_timespan(vcd_path: Path) -> tuple[list[dict[str, Any]], int]:
    """Extract hierarchical signal names/widths and max timestamp from a .vcd file."""
    text = vcd_path.read_text(encoding="utf-8", errors="replace")
    scope_stack: list[str] = []
    signals: list[dict[str, Any]] = []
    seen_full: set[str] = set()

    var_re = re.compile(r"^\$var\s+(\w+)\s+(\d+)\s+\S+\s+(\S+)(?:\s+(\[[^\]]+\]))?\s+\$end")
    scope_re = re.compile(r"^\$scope\s+\w+\s+(\S+)\s+\$end")

    in_header = True
    max_time = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if in_header:
            if line.startswith("$scope"):
                sm = scope_re.match(line)
                if sm:
                    scope_stack.append(sm.group(1))
            elif line.startswith("$upscope"):
                if scope_stack:
                    scope_stack.pop()
            elif line.startswith("$var"):
                vm = var_re.match(line)
                if vm:
                    vtype, width_s, name, range_s = vm.groups()
                    width = int(width_s)
                    leaf = f"{name}{range_s}" if (range_s and "[" not in name) else name
                    full_name = ".".join([*scope_stack, leaf])
                    if full_name not in seen_full:
                        seen_full.add(full_name)
                        signals.append(
                            {
                                "full_name": full_name,
                                "base_name": name,
                                "depth": len(scope_stack),
                                "width": width,
                                "vtype": vtype,
                            }
                        )
            elif line.startswith("$enddefinitions"):
                in_header = False
        elif line.startswith("#"):
            with contextlib.suppress(ValueError):
                t_val = int(line[1:])
                max_time = max(max_time, t_val)

    return signals, max_time


def generate_gtkw_savefile(
    spec: DigitalSpec,
    vcd_path: Path,
    gtkw_path: Path,
    zoom_pow: float = -16.0,
) -> Path:
    """Programmatically build a .gtkw layout selecting key DUT signals & radices."""
    signals, _max_time = parse_vcd_signals_and_timespan(vcd_path)

    dut_sigs = [s for s in signals if ".dut." in s["full_name"] and s["depth"] <= 3]
    pool = dut_sigs if dut_sigs else signals

    selected: list[dict[str, Any]] = []
    used_names: set[str] = set()

    priority_names: list[str] = []
    if spec.clock_port:
        priority_names.append(spec.clock_port)
    if spec.reset_port:
        priority_names.append(spec.reset_port)
    priority_names.extend(spec.gtkwave_signals)
    priority_names.extend(["state", "ped_pending", "sec_tick"])
    priority_names.extend([p.name for p in spec.ports])

    for target in priority_names:
        for s in pool:
            if s["base_name"] == target and s["full_name"] not in used_names:
                if s["width"] >= 32 and target not in {p.name for p in spec.ports}:
                    continue
                selected.append(s)
                used_names.add(s["full_name"])
                break

    for s in pool:
        if len(selected) >= 14:
            break
        if s["full_name"] not in used_names and s["width"] <= 16 and s["vtype"] != "integer":
            selected.append(s)
            used_names.add(s["full_name"])

    port_meta = {p.name: p for p in spec.ports}
    lines = [
        "[*]",
        "[*] Auto-generated GTKWave layout — fpga_autopilot",
        "[*]",
        f'[dumpfile] "{vcd_path.name}"',
        "[sst_width] 220",
        "[signals_width] 240",
        "[sst_expanded] 1",
        "[sst_vpaned_height] 240",
        f"*{zoom_pow:.6f} 0 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1 -1",
    ]

    for s in selected:
        bname = s["base_name"]
        w = s["width"]
        p = port_meta.get(bname)
        if w == 1:
            flag = "@28"
        elif p and p.signed:
            flag = "@420"
        elif bname in ("countdown",):
            flag = "@24"
        else:
            flag = "@22"
        lines.append(flag)
        lines.append(s["full_name"])

    lines.append("[pattern_trace] 1")
    lines.append("[pattern_trace] 0")
    gtkw_path.parent.mkdir(parents=True, exist_ok=True)
    gtkw_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return gtkw_path


def audit_waveform_canvas(image_bgr: np.ndarray) -> dict[str, Any]:
    """OpenCV visual audit verifying waveform transitions are crisp, non-blank, and not solid bars."""
    h, w = image_bgr.shape[:2]
    # Crop strictly inside waveform trace area (skipping top time ruler and t=0 initial radix labels)
    x0 = int(w * 0.34)
    x1 = int(w * 0.96)
    y0 = int(h * 0.19)
    y1 = int(h * 0.86)
    roi = image_bgr[y0:y1, x0:x1]
    rh, rw = roi.shape[:2]
    if rh < 40 or rw < 80:
        return {
            "passed": False,
            "edge_density": 0.0,
            "transition_columns": 0,
            "solid_green_ratio": 0.0,
            "reason": "ROI too small",
            "roi_bbox": [x0, y0, x1 - x0, y1 - y0],
        }

    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.count_nonzero(edges)) / float(rh * rw)

    b_ch, g_ch, r_ch = cv2.split(roi)
    bright_mask = (g_ch > 100) | (r_ch > 130) | (b_ch > 150)
    bright_ratio = float(np.count_nonzero(bright_mask)) / float(rh * rw)

    # Vertical transition edges across digital traces
    horiz_diff = np.abs(gray[:, 1:].astype(np.int16) - gray[:, :-1].astype(np.int16))
    col_edge_hits = np.sum(horiz_diff > 45, axis=0)
    transition_columns = int(np.sum(col_edge_hits >= 6))

    # Solid green bar detector (survives 7x9 morphological erosion only when traces collapse into solid blocks)
    green_dominant = (g_ch > 130) & (r_ch < 90) & (b_ch < 90)
    kernel = np.ones((7, 9), dtype=np.uint8)
    solid_blobs = cv2.erode(green_dominant.astype(np.uint8) * 255, kernel, iterations=1)
    solid_green_ratio = float(np.count_nonzero(solid_blobs)) / float(rh * rw)

    is_not_blank = (bright_ratio >= 0.002) and (edge_density >= 0.003)
    has_transitions = transition_columns >= 5
    not_solid_bars = solid_green_ratio < 0.06

    passed = bool(is_not_blank and has_transitions and not_solid_bars)
    if not is_not_blank:
        reason = f"Waveform canvas appears blank (bright_ratio={bright_ratio:.4f}, edge_density={edge_density:.4f})"
    elif not not_solid_bars:
        reason = f"Zoomed out too far into solid green bars (solid_green_ratio={solid_green_ratio:.4f})"
    elif not has_transitions:
        reason = f"Too few visible signal transitions (transition_columns={transition_columns})"
    else:
        reason = "Crisp digital signal transitions verified"

    return {
        "passed": passed,
        "edge_density": round(edge_density, 5),
        "bright_ratio": round(bright_ratio, 5),
        "transition_columns": transition_columns,
        "solid_green_ratio": round(solid_green_ratio, 5),
        "reason": reason,
        "roi_bbox": [x0, y0, x1 - x0, y1 - y0],
    }


def audit_schematic_canvas(image_bgr: np.ndarray) -> dict[str, Any]:
    """OpenCV visual audit verifying Quartus RTL/FSM Viewer diagram rendered schematic content."""
    h, w = image_bgr.shape[:2]
    x0, x1 = int(w * 0.18), int(w * 0.96)
    y0, y1 = int(h * 0.16), int(h * 0.86)
    roi = image_bgr[y0:y1, x0:x1]
    rh, rw = roi.shape[:2]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 130)
    edge_density = float(np.count_nonzero(edges)) / float(rh * rw)
    std_val = float(np.std(gray))
    col_hits = int(np.sum(np.sum(edges > 0, axis=0) >= 4))
    passed = bool(edge_density >= 0.004 and std_val >= 8.0 and col_hits >= 15)
    return {
        "passed": passed,
        "edge_density": round(edge_density, 5),
        "intensity_std": round(std_val, 3),
        "transition_columns": col_hits,
        "roi_bbox": [x0, y0, x1 - x0, y1 - y0],
        "reason": "Schematic symbols and nets verified" if passed else "Schematic canvas sparse/empty",
    }


class SafeGuiInspector:
    """Strict window-confined GUI automation controller for GTKWave & Quartus II."""

    def __init__(self, audit_dir: Path) -> None:
        pyautogui.FAILSAFE = True
        self.audit_dir = audit_dir
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.audit_dir / "gui_audit_log.jsonl"

    def _log_event(self, event_type: str, payload: dict[str, Any]) -> None:
        entry = {
            "timestamp": datetime.now(UTC).isoformat(),
            "failsafe_enabled": bool(pyautogui.FAILSAFE),
            "event": event_type,
            **payload,
        }
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")

    def safe_click(
        self,
        x: int,
        y: int,
        bbox: tuple[int, int, int, int],
        window_title: str,
        purpose: str,
        hwnd: int | None = None,
    ) -> None:
        """Click strictly inside an allowlisted EDA window bounding box."""
        try:
            verify_point_in_bbox(x, y, bbox, window_title)
        except WindowConfinementError as exc:
            self._log_event(
                "BLOCKED_CLICK",
                {"x": x, "y": y, "bbox": list(bbox), "window_title": window_title, "error": str(exc)},
            )
            raise

        delivery = "pyautogui"
        if _is_interactive_desktop():
            pyautogui.moveTo(x, y, duration=0.10)
            pyautogui.click(x, y)
        elif hwnd is not None and os.name == "nt":
            delivery = "win32_confined_postmessage"
            _post_click_screen_confined(hwnd, x, y)

        self._log_event(
            "CONFINED_CLICK",
            {
                "x": x,
                "y": y,
                "bbox": list(bbox),
                "window_title": window_title,
                "delivery": delivery,
                "purpose": purpose,
            },
        )

    def _grab_window_bgr(self, hwnd: int, bbox: tuple[int, int, int, int]) -> np.ndarray:
        """Grab high-DPI BGR image of target EDA window via PrintWindow or desktop ImageGrab."""
        left, top, width, height = bbox
        if os.name == "nt":
            for _retry in range(5):
                arr = _grab_hwnd_printwindow(hwnd, width, height)
                if arr.max() > 0:
                    return arr
                time.sleep(0.5)
            if not _is_interactive_desktop():
                return np.zeros((height, width, 3), dtype=np.uint8)
        scr_w, scr_h = pyautogui.size()
        pil_img = ImageGrab.grab(bbox=(max(0, left), max(0, top), min(scr_w, left + width), min(scr_h, top + height)))
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    def _save_annotated_audit_image(
        self,
        image_bgr: np.ndarray,
        roi_bbox: list[int],
        tag: str,
        passed: bool,
    ) -> Path:
        vis = image_bgr.copy()
        rx, ry, rw, rh = roi_bbox
        color = (0, 220, 0) if passed else (0, 0, 230)
        cv2.rectangle(vis, (rx, ry), (rx + rw, ry + rh), color, 2)
        cv2.putText(
            vis,
            f"AUDIT: {'PASS' if passed else 'RETRY'} ({tag})",
            (rx + 8, max(24, ry - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            color,
            2,
        )
        out_p = self.audit_dir / f"{tag}_audit.png"
        cv2.imwrite(str(out_p), vis)
        return out_p

    def _wait_for_eda_window(
        self,
        proc_pid: int,
        keyword: str,
        timeout_sec: float = 20.0,
        min_width: int = 420,
    ) -> dict[str, Any] | None:
        deadline = time.time() + timeout_sec
        kw = keyword.lower()
        while time.time() < deadline:
            wins = _enum_win32_windows()
            for w in wins:
                if w["pid"] == proc_pid and kw in w["title"].lower() and w["bbox"][2] >= min_width:
                    return w
            for w in wins:
                if kw in w["title"].lower() and w["bbox"][2] >= min_width:
                    return w
            time.sleep(0.40)
        return None

    def capture_gtkwave(
        self,
        spec: DigitalSpec,
        vcd_path: Path,
        output_png_path: Path,
    ) -> VisualCapture:
        """Launch GTKWave with programmatic .gtkw layout, confine GUI actions, and audit transitions."""
        env = build_eda_env()
        gtkwave_bin = find_tool("gtkwave", env)
        if not gtkwave_bin:
            raise RuntimeError("gtkwave binary not found on host.")

        output_png_path.parent.mkdir(parents=True, exist_ok=True)
        _sigs, max_time_ps = parse_vcd_signals_and_timespan(vcd_path)

        if spec.archetype == "adder_sub_7seg":
            visible_span_ps = 320_000  # ~32 truth-table vectors
        elif spec.archetype == "traffic_fsm":
            visible_span_ps = 1_600_000  # ~160 clocks showing multi-state FSM & countdown transitions
        elif spec.archetype == "uart_fifo_top":
            visible_span_ps = 4_200_000  # ~1.3 UART frames showing start/8-data/stop bits + FIFO strobes
        else:
            visible_span_ps = max(200_000, min(max_time_ps, 1_000_000))

        # Calibrated GTKWave logarithmic zoom factor (1ps timescale offset -7.55)
        current_zoom = math.log2(920.0 / max(1.0, float(visible_span_ps))) - 7.55
        local_vcd = output_png_path.parent / vcd_path.name
        if vcd_path.resolve() != local_vcd.resolve():
            shutil.copy2(vcd_path, local_vcd)

        gtkw_path = output_png_path.parent / f"{spec.top_module or spec.name}.gtkw"
        best_img: np.ndarray | None = None
        best_audit: dict[str, Any] = {}
        last_title = f"GTKWave - {local_vcd.name}"
        last_bbox = (50, 40, 1420, 820)
        zoom_adjustments = 0

        for attempt in range(4):
            generate_gtkw_savefile(spec, local_vcd, gtkw_path, zoom_pow=current_zoom)
            cmd = [gtkwave_bin, local_vcd.name, gtkw_path.name]
            self._log_event(
                "LAUNCH_GTKWAVE",
                {"attempt": attempt, "cmd": cmd, "zoom_pow": round(current_zoom, 4)},
            )

            proc = subprocess.Popen(
                cmd,
                cwd=str(output_png_path.parent),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                win = self._wait_for_eda_window(proc.pid, "gtkwave", timeout_sec=18.0)
                if not win:
                    raise RuntimeError("GTKWave GUI window did not appear within timeout.")

                hwnd = win["hwnd"]
                last_title = win["title"]
                last_bbox = _focus_and_position_win32(hwnd, x=50, y=40, w=1420, h=820)
                time.sleep(1.0)

                canvas_cx = last_bbox[0] + int(last_bbox[2] * 0.62)
                canvas_cy = last_bbox[1] + int(last_bbox[3] * 0.50)
                self.safe_click(
                    canvas_cx,
                    canvas_cy,
                    last_bbox,
                    last_title,
                    purpose="Focus GTKWave waveform canvas",
                    hwnd=hwnd,
                )
                time.sleep(0.35)

                img_bgr = self._grab_window_bgr(hwnd, last_bbox)
                audit = audit_waveform_canvas(img_bgr)
                audit_img = self._save_annotated_audit_image(
                    img_bgr,
                    audit["roi_bbox"],
                    tag=f"{spec.name}_gtkwave_try{attempt}",
                    passed=audit["passed"],
                )
                self._log_event(
                    "OPENCV_WAVEFORM_AUDIT",
                    {
                        "attempt": attempt,
                        "window_title": last_title,
                        "bbox": list(last_bbox),
                        "zoom_pow": round(current_zoom, 4),
                        "audit": audit,
                        "audit_image": str(audit_img),
                    },
                )

                best_img = img_bgr
                best_audit = audit
                if audit["passed"]:
                    break

                # Closed-loop zoom adjustment
                zoom_adjustments += 1
                if audit.get("solid_green_ratio", 0.0) >= 0.06:
                    current_zoom += 2.0  # Zoom in 4x when compressed into solid green bars
                else:
                    current_zoom -= 2.0  # Zoom out 4x when too few transitions are visible
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                self._log_event("CLOSE_GTKWAVE", {"pid": proc.pid, "attempt": attempt})

        assert best_img is not None
        cv2.imwrite(str(output_png_path), best_img)
        shutil.copy2(output_png_path, self.audit_dir / f"{spec.name}_waveform_verified.png")

        h_px, w_px = best_img.shape[:2]
        return VisualCapture(
            capture_type="gtkwave_waveform",
            tool_name="gtkwave",
            image_path=str(output_png_path.resolve()),
            window_title=last_title,
            window_bbox=last_bbox,
            width_px=w_px,
            height_px=h_px,
            visual_audit_passed=bool(best_audit.get("passed", False)),
            edge_density=float(best_audit.get("edge_density", 0.0)),
            transition_columns_detected=int(best_audit.get("transition_columns", 0)),
            zoom_adjustments=zoom_adjustments,
            audit_log_path=str(self.log_path.resolve()),
            notes=str(best_audit.get("reason", "")),
        )

    def _open_quartus_netlist_submenu_item(
        self,
        main_hwnd: int,
        main_title: str,
        main_bbox: tuple[int, int, int, int],
        proc_pid: int,
        submenu_y_ratio: float,
        item_label: str,
    ) -> None:
        """Confined navigation: Quartus Tools -> Netlist Viewers -> <item_label>."""
        # 1. Click 'Tools' on main Quartus menu bar (dx=372, dy=52 on 1460x860 frame)
        tools_x = main_bbox[0] + 372
        tools_y = main_bbox[1] + 52
        self.safe_click(
            tools_x,
            tools_y,
            main_bbox,
            main_title,
            purpose=f"Open Quartus Tools menu for {item_label}",
            hwnd=main_hwnd,
        )
        time.sleep(0.55)

        popups = [
            w for w in _enum_win32_windows() if w["pid"] == proc_pid and w["hwnd"] != main_hwnd
        ]
        if not popups:
            return
        tools_popup = popups[0]
        p_hwnd = tools_popup["hwnd"]
        p_bbox = tools_popup["bbox"]
        p_title = tools_popup["title"]

        # 2. Click 'Netlist Viewers' inside Tools popup (y_ratio = 0.317)
        nv_x = p_bbox[0] + min(120, p_bbox[2] // 2)
        nv_y = p_bbox[1] + int(p_bbox[3] * 0.317)
        verify_point_in_bbox(nv_x, nv_y, p_bbox, p_title)
        _post_click_client(p_hwnd, nv_x - p_bbox[0], nv_y - p_bbox[1])
        self._log_event(
            "CONFINED_CLICK",
            {
                "x": nv_x,
                "y": nv_y,
                "bbox": list(p_bbox),
                "window_title": p_title,
                "purpose": "Expand Netlist Viewers submenu",
            },
        )
        time.sleep(0.55)

        sub_popups = [
            w
            for w in _enum_win32_windows()
            if w["pid"] == proc_pid and w["hwnd"] not in (main_hwnd, p_hwnd) and w["bbox"][3] < 260
        ]
        if not sub_popups:
            return
        sub = sub_popups[0]
        s_hwnd = sub["hwnd"]
        s_bbox = sub["bbox"]
        s_title = sub["title"]

        # 3. Click target viewer item inside Netlist Viewers submenu
        item_x = s_bbox[0] + min(100, s_bbox[2] // 2)
        item_y = s_bbox[1] + int(s_bbox[3] * submenu_y_ratio)
        verify_point_in_bbox(item_x, item_y, s_bbox, s_title)
        _post_click_client(s_hwnd, item_x - s_bbox[0], item_y - s_bbox[1])
        self._log_event(
            "CONFINED_CLICK",
            {
                "x": item_x,
                "y": item_y,
                "bbox": list(s_bbox),
                "window_title": s_title,
                "purpose": f"Launch {item_label}",
            },
        )

    def capture_quartus_viewers(
        self,
        spec: DigitalSpec,
        qpf_path: Path,
        output_dir: Path,
        capture_fsm: bool = False,
    ) -> list[VisualCapture]:
        """Open compiled .qpf in Quartus II GUI, capture RTL Viewer (& State Machine Viewer), and close."""
        env = build_eda_env()
        quartus_gui = find_tool("quartus", env)
        if not quartus_gui or not qpf_path.exists():
            return []

        output_dir.mkdir(parents=True, exist_ok=True)
        captures: list[VisualCapture] = []

        cmd = [quartus_gui, qpf_path.name]
        self._log_event("LAUNCH_QUARTUS_GUI", {"cmd": cmd, "qpf": str(qpf_path)})

        proc = subprocess.Popen(
            cmd,
            cwd=str(qpf_path.parent),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        try:
            top = spec.top_module or spec.name
            deadline = time.time() + 35.0
            win: dict[str, Any] | None = None
            while time.time() < deadline:
                for w in _enum_win32_windows():
                    t_low = w["title"].lower()
                    if "quartus ii" in t_low and (top.lower() in t_low or w["pid"] == proc.pid):
                        win = w
                        break
                if win and top.lower() in win["title"].lower():
                    break
                time.sleep(0.8)

            if not win:
                win = self._wait_for_eda_window(proc.pid, "quartus", timeout_sec=8.0)
            if not win:
                self._log_event("QUARTUS_GUI_TIMEOUT", {"qpf": str(qpf_path)})
                return []

            main_hwnd = win["hwnd"]
            main_title = win["title"]
            time.sleep(2.8)
            main_bbox = _focus_and_position_win32(main_hwnd, x=30, y=30, w=1460, h=860)
            time.sleep(0.6)

            # 1. Open Tools -> Netlist Viewers -> RTL Viewer (submenu y_ratio = 0.14)
            self._open_quartus_netlist_submenu_item(
                main_hwnd=main_hwnd,
                main_title=main_title,
                main_bbox=main_bbox,
                proc_pid=proc.pid,
                submenu_y_ratio=0.14,
                item_label="RTL Viewer",
            )

            rtl_win: dict[str, Any] | None = None
            rtl_deadline = time.time() + 12.0
            while time.time() < rtl_deadline:
                for w in _enum_win32_windows():
                    if w["pid"] == proc.pid and "rtl viewer" in w["title"].lower():
                        rtl_win = w
                        break
                if rtl_win:
                    break
                time.sleep(0.5)

            target_rtl = rtl_win or win
            r_hwnd = target_rtl["hwnd"]
            r_title = target_rtl["title"]
            r_bbox = _focus_and_position_win32(r_hwnd, x=30, y=30, w=1460, h=860)
            time.sleep(0.8)

            # Fit schematic in viewport via RTL Viewer toolbar 'Fit in Window' icon (dx=561, dy=92)
            if "rtl viewer" in r_title.lower():
                self.safe_click(
                    r_bbox[0] + 561,
                    r_bbox[1] + 92,
                    r_bbox,
                    r_title,
                    purpose="Fit RTL Viewer schematic in viewport",
                    hwnd=r_hwnd,
                )
                time.sleep(0.7)

            rtl_img = self._grab_window_bgr(r_hwnd, r_bbox)
            rtl_audit = audit_schematic_canvas(rtl_img)
            rtl_png = output_dir / f"{top}_rtl_viewer.png"
            cv2.imwrite(str(rtl_png), rtl_img)
            self._save_annotated_audit_image(
                rtl_img, rtl_audit["roi_bbox"], tag=f"{spec.name}_quartus_rtl", passed=rtl_audit["passed"]
            )
            shutil.copy2(rtl_png, self.audit_dir / f"{spec.name}_rtl_viewer_verified.png")

            captures.append(
                VisualCapture(
                    capture_type="quartus_rtl_viewer",
                    tool_name="quartus",
                    image_path=str(rtl_png.resolve()),
                    window_title=r_title,
                    window_bbox=r_bbox,
                    width_px=int(rtl_img.shape[1]),
                    height_px=int(rtl_img.shape[0]),
                    visual_audit_passed=bool(rtl_audit["passed"]),
                    edge_density=float(rtl_audit["edge_density"]),
                    transition_columns_detected=int(rtl_audit["transition_columns"]),
                    audit_log_path=str(self.log_path.resolve()),
                    notes=str(rtl_audit["reason"]),
                )
            )

            # 2. Open Tools -> Netlist Viewers -> State Machine Viewer for FSM designs (y_ratio = 0.38)
            if capture_fsm:
                main_bbox = _focus_and_position_win32(main_hwnd, x=30, y=30, w=1460, h=860)
                time.sleep(0.4)
                self._open_quartus_netlist_submenu_item(
                    main_hwnd=main_hwnd,
                    main_title=main_title,
                    main_bbox=main_bbox,
                    proc_pid=proc.pid,
                    submenu_y_ratio=0.38,
                    item_label="State Machine Viewer",
                )

                fsm_win: dict[str, Any] | None = None
                fsm_deadline = time.time() + 12.0
                while time.time() < fsm_deadline:
                    for w in _enum_win32_windows():
                        if w["pid"] == proc.pid and "state machine viewer" in w["title"].lower():
                            fsm_win = w
                            break
                    if fsm_win:
                        break
                    time.sleep(0.5)

                if fsm_win:
                    f_hwnd = fsm_win["hwnd"]
                    f_title = fsm_win["title"]
                    f_bbox = _focus_and_position_win32(f_hwnd, x=30, y=30, w=1460, h=860)
                    time.sleep(0.8)

                    fsm_img = self._grab_window_bgr(f_hwnd, f_bbox)
                    fsm_audit = audit_schematic_canvas(fsm_img)
                    fsm_png = output_dir / f"{top}_fsm_viewer.png"
                    cv2.imwrite(str(fsm_png), fsm_img)
                    self._save_annotated_audit_image(
                        fsm_img,
                        fsm_audit["roi_bbox"],
                        tag=f"{spec.name}_quartus_fsm",
                        passed=fsm_audit["passed"],
                    )
                    shutil.copy2(fsm_png, self.audit_dir / f"{spec.name}_fsm_viewer_verified.png")

                    captures.append(
                        VisualCapture(
                            capture_type="quartus_fsm_viewer",
                            tool_name="quartus",
                            image_path=str(fsm_png.resolve()),
                            window_title=f_title,
                            window_bbox=f_bbox,
                            width_px=int(fsm_img.shape[1]),
                            height_px=int(fsm_img.shape[0]),
                            visual_audit_passed=bool(fsm_audit["passed"]),
                            edge_density=float(fsm_audit["edge_density"]),
                            transition_columns_detected=int(fsm_audit["transition_columns"]),
                            audit_log_path=str(self.log_path.resolve()),
                            notes=str(fsm_audit["reason"]),
                        )
                    )

            return captures
        finally:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True,
                    check=False,
                )
            else:
                proc.terminate()
            self._log_event("CLOSE_QUARTUS_GUI", {"pid": proc.pid})
