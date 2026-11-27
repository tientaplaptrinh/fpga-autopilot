"""Pydantic v2 contracts for Digital Design & Quartus II Autopilot."""

from .hdl_models import (
    AutopilotRunSummary,
    DigitalSpec,
    FsmStateSpec,
    LintReport,
    LintWarning,
    ParameterSpec,
    PortSpec,
    ResourceMetrics,
    SimResult,
    SynthesisReport,
    TimingMetrics,
    VectorMismatch,
    VisualCapture,
)

__all__ = [
    "AutopilotRunSummary",
    "DigitalSpec",
    "FsmStateSpec",
    "LintReport",
    "LintWarning",
    "ParameterSpec",
    "PortSpec",
    "ResourceMetrics",
    "SimResult",
    "SynthesisReport",
    "TimingMetrics",
    "VectorMismatch",
    "VisualCapture",
]
