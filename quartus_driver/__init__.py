"""Quartus II project generation, headless synthesis, report parsing, and safe GUI inspection."""

from .gui_inspector import SafeGuiInspector, WindowConfinementError
from .project_builder import BOARD_PRESETS, build_quartus_project
from .report_parser import parse_quartus_reports
from .synth_runner import run_synthesis

__all__ = [
    "BOARD_PRESETS",
    "SafeGuiInspector",
    "WindowConfinementError",
    "build_quartus_project",
    "parse_quartus_reports",
    "run_synthesis",
]
