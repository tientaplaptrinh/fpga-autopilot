"""Unit tests for strict Pydantic v2 contracts in contracts/hdl_models.py."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from contracts.hdl_models import DigitalSpec, PortSpec


def test_port_spec_sv_decl_and_validation() -> None:
    p_signed = PortSpec(name="operand_a", direction="input", width=4, signed=True)
    assert p_signed.sv_decl(is_last=False) == "    input  logic signed [3:0] operand_a,"

    p_scalar = PortSpec(name="zero_flag", direction="output", width=1)
    assert p_scalar.sv_decl(is_last=True) == "    output logic zero_flag"

    with pytest.raises(ValidationError):
        PortSpec(name="9bad_ident", direction="input", width=1)

    with pytest.raises(ValidationError):
        PortSpec(name="clk", direction="input", width=0)


def test_digital_spec_forbids_duplicate_ports_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        DigitalSpec(
            name="dup_mod",
            title="Duplicate Port Test",
            description="Should fail",
            ports=[
                PortSpec(name="clk", direction="input", width=1),
                PortSpec(name="clk", direction="output", width=1),
            ],
        )

    with pytest.raises(ValidationError):
        DigitalSpec.model_validate(
            {
                "name": "extra_mod",
                "title": "Extra Field Test",
                "description": "Should fail",
                "ports": [{"name": "a", "direction": "input", "width": 1}],
                "unexpected_key": 123,
            }
        )
