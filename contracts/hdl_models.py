"""Strict Pydantic v2 schemas for Digital Design & Quartus II Autopilot."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SV_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ParameterSpec(BaseModel):
    """Compile-time SystemVerilog parameter specification."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str
    default_value: int | str
    sim_value: int | str | None = None
    sv_type: str = "int"
    description: str = ""

    @field_validator("name")
    @classmethod
    def _valid_ident(cls, value: str) -> str:
        if not _SV_IDENT_RE.match(value):
            raise ValueError(f"Invalid SystemVerilog parameter identifier: {value!r}")
        return value


class PortSpec(BaseModel):
    """Hardware module port specification."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str
    direction: Literal["input", "output", "inout"]
    width: int = Field(default=1, ge=1)
    width_expr: str | None = None
    signed: bool = False
    active_low: bool = False
    description: str = ""
    pin_assignment: str | None = None

    @field_validator("name")
    @classmethod
    def _valid_ident(cls, value: str) -> str:
        if not _SV_IDENT_RE.match(value):
            raise ValueError(f"Invalid SystemVerilog port identifier: {value!r}")
        return value

    def sv_decl(self, is_last: bool = False) -> str:
        """Render clean SystemVerilog ANSI port declaration."""
        sign_str = " signed" if self.signed else ""
        if self.width_expr:
            range_str = f" [{self.width_expr}-1:0]"
        elif self.width > 1:
            range_str = f" [{self.width - 1}:0]"
        else:
            range_str = ""
        comma = "" if is_last else ","
        return f"    {self.direction:<6} logic{sign_str}{range_str} {self.name}{comma}"


class FsmStateSpec(BaseModel):
    """Finite State Machine state metadata for documentation and RTL templates."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str
    encoding: str | None = None
    outputs: dict[str, str] = Field(default_factory=dict)
    transitions: list[dict[str, str]] = Field(default_factory=list)
    description: str = ""


class DigitalSpec(BaseModel):
    """Complete hardware design and verification specification."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str
    top_module: str | None = None
    title: str
    description: str
    archetype: Literal["adder_sub_7seg", "traffic_fsm", "uart_fifo_top", "generic_sync", "custom"] = "custom"
    clock_port: str | None = "clk"
    reset_port: str | None = "rst_n"
    reset_active_low: bool = True
    clock_freq_mhz: float = Field(default=50.0, gt=0.0)
    board_preset: Literal["DE2-115", "DE10-Lite", "DE1-SoC"] = "DE2-115"
    fpga_family: str | None = None
    fpga_device: str | None = None
    parameters: list[ParameterSpec] = Field(default_factory=list)
    ports: list[PortSpec] = Field(min_length=1)
    fsm_states: list[FsmStateSpec] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    gtkwave_signals: list[str] = Field(default_factory=list)
    custom_rtl_sv: str | None = None

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _SV_IDENT_RE.match(value):
            raise ValueError(f"Invalid spec/module name: {value!r}")
        return value

    @model_validator(mode="after")
    def _populate_top_module_and_unique_ports(self) -> DigitalSpec:
        if not self.top_module:
            self.top_module = self.name
        if not _SV_IDENT_RE.match(self.top_module):
            raise ValueError(f"Invalid top_module identifier: {self.top_module!r}")
        seen: set[str] = set()
        for port in self.ports:
            if port.name in seen:
                raise ValueError(f"Duplicate port name {port.name!r} in spec {self.name!r}")
            seen.add(port.name)
        return self


class LintWarning(BaseModel):
    """Single lint or static RTL rule diagnostic."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    severity: Literal["error", "warning", "info"]
    code: str
    message: str
    file: str | None = None
    line: int | None = None
    signal: str | None = None


class LintReport(BaseModel):
    """Aggregated static analysis and compiler lint report."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    inferred_latches: int = Field(default=0, ge=0)
    blocking_in_seq: int = Field(default=0, ge=0)
    nonblocking_in_comb: int = Field(default=0, ge=0)
    missing_reset_clauses: int = Field(default=0, ge=0)
    undriven_nets: int = Field(default=0, ge=0)
    multidriven_nets: int = Field(default=0, ge=0)
    width_mismatches: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    warning_count: int = Field(default=0, ge=0)
    tools_used: list[str] = Field(default_factory=list)
    warnings: list[LintWarning] = Field(default_factory=list)


class VectorMismatch(BaseModel):
    """Cycle-accurate testbench golden comparison failure."""

    model_config = ConfigDict(extra="forbid")

    cycle: int = Field(ge=0)
    input_hex: str
    expected_hex: str
    got_hex: str
    detail: str = ""


class SimResult(BaseModel):
    """Structured HDL simulation execution result."""

    model_config = ConfigDict(extra="forbid")

    simulator: str
    compile_passed: bool
    sim_passed: bool
    timed_out: bool = False
    total_vectors: int = Field(default=0, ge=0)
    passed_vectors: int = Field(default=0, ge=0)
    failed_vectors: int = Field(default=0, ge=0)
    mismatches: list[VectorMismatch] = Field(default_factory=list)
    vcd_path: str | None = None
    stdout: str = ""
    stderr: str = ""
    runtime_sec: float = Field(default=0.0, ge=0.0)


class ResourceMetrics(BaseModel):
    """FPGA hardware utilization metrics extracted from synthesis/fitter reports."""

    model_config = ConfigDict(extra="forbid")

    logic_elements_or_alms: int = Field(default=0, ge=0)
    combinational_functions: int = Field(default=0, ge=0)
    dedicated_logic_registers: int = Field(default=0, ge=0)
    memory_bits: int = Field(default=0, ge=0)
    dsp_elements: int = Field(default=0, ge=0)
    total_pins: int = Field(default=0, ge=0)
    inferred_latches: int = Field(default=0, ge=0)


class TimingMetrics(BaseModel):
    """Static Timing Analysis (TimeQuest STA) metrics."""

    model_config = ConfigDict(extra="forbid")

    fmax_mhz: float | None = None
    restricted_fmax_mhz: float | None = None
    worst_setup_slack_ns: float | None = None
    worst_hold_slack_ns: float | None = None
    worst_recovery_slack_ns: float | None = None
    worst_removal_slack_ns: float | None = None
    max_comb_delay_ns: float | None = None
    timing_met: bool = True


class SynthesisReport(BaseModel):
    """Quartus II or Yosys synthesis + timing compilation report."""

    model_config = ConfigDict(extra="forbid")

    backend: Literal["quartus", "yosys"]
    compile_passed: bool
    family: str
    device: str
    top_module: str
    project_dir: str
    qpf_path: str | None = None
    qsf_path: str | None = None
    sdc_path: str | None = None
    tcl_path: str | None = None
    map_rpt_path: str | None = None
    fit_rpt_path: str | None = None
    sta_rpt_path: str | None = None
    resources: ResourceMetrics = Field(default_factory=ResourceMetrics)
    timing: TimingMetrics = Field(default_factory=TimingMetrics)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class VisualCapture(BaseModel):
    """Desktop GUI screenshot and OpenCV visual verification record."""

    model_config = ConfigDict(extra="forbid")

    capture_type: Literal["gtkwave_waveform", "quartus_rtl_viewer", "quartus_fsm_viewer"]
    tool_name: str
    image_path: str
    window_title: str
    window_bbox: tuple[int, int, int, int]
    width_px: int = Field(gt=0)
    height_px: int = Field(gt=0)
    visual_audit_passed: bool
    edge_density: float = Field(default=0.0, ge=0.0)
    transition_columns_detected: int = Field(default=0, ge=0)
    zoom_adjustments: int = Field(default=0, ge=0)
    audit_log_path: str | None = None
    notes: str = ""


class AutopilotRunSummary(BaseModel):
    """End-to-end execution artifact summary for one digital design benchmark."""

    model_config = ConfigDict(extra="forbid")

    spec_name: str
    top_module: str
    board_preset: str
    rtl_paths: list[str]
    tb_path: str
    healing_iterations: int = Field(default=0, ge=0)
    lint_report: LintReport
    sim_result: SimResult
    synthesis_report: SynthesisReport
    visual_captures: list[VisualCapture] = Field(default_factory=list)
    summary_md_path: str | None = None
    latex_tex_path: str | None = None
    latex_pdf_path: str | None = None
    overall_passed: bool
