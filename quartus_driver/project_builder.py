"""Quartus II .qpf, .qsf (student kit presets), .sdc constraints, and Tcl script generator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from contracts.hdl_models import DigitalSpec, PortSpec

BOARD_PRESETS: dict[str, dict[str, Any]] = {
    "DE2-115": {
        "family": "Cyclone IV E",
        "device": "EP4CE115F29C7",
        "clock_pin": "PIN_Y2",
        "reset_pin": "PIN_M23",
        "input_pins": [
            "PIN_AB28", "PIN_AC28", "PIN_AC27", "PIN_AD27",
            "PIN_AB27", "PIN_AC26", "PIN_AD26", "PIN_AB26",
            "PIN_AC25", "PIN_AB25", "PIN_AC24", "PIN_AB24",
            "PIN_AB23", "PIN_AA24", "PIN_AA23", "PIN_AA22",
            "PIN_Y24",  "PIN_Y23",
        ],
        "output_pins": [
            # HEX0[0..6], HEX1[0..6], LEDR[0..15]
            "PIN_G18", "PIN_F22", "PIN_E17", "PIN_L26", "PIN_L25", "PIN_J22", "PIN_H22",
            "PIN_M24", "PIN_Y22", "PIN_W21", "PIN_W22", "PIN_W25", "PIN_U23", "PIN_U24",
            "PIN_G19", "PIN_F19", "PIN_E19", "PIN_F21", "PIN_F18", "PIN_E18", "PIN_J19", "PIN_H19",
            "PIN_J17", "PIN_G17", "PIN_J15", "PIN_H16", "PIN_J16", "PIN_H17", "PIN_F15", "PIN_G15",
        ],
    },
    "DE10-Lite": {
        "family": "MAX 10",
        "device": "10M50DAF484C7G",
        "clock_pin": "PIN_P11",
        "reset_pin": "PIN_B8",
        "input_pins": [
            "PIN_C10", "PIN_C11", "PIN_D12", "PIN_C12", "PIN_A12",
            "PIN_B12", "PIN_A13", "PIN_A14", "PIN_B14", "PIN_F15",
        ],
        "output_pins": [
            "PIN_C14", "PIN_E15", "PIN_C15", "PIN_C16", "PIN_E16", "PIN_D17", "PIN_C17",
            "PIN_C18", "PIN_D18", "PIN_E18", "PIN_B16", "PIN_A17", "PIN_A18", "PIN_B17",
            "PIN_A8",  "PIN_A9",  "PIN_A10", "PIN_B10", "PIN_D13", "PIN_C13", "PIN_E14", "PIN_D14",
        ],
    },
    "DE1-SoC": {
        "family": "Cyclone V",
        "device": "5CSEMA5F31C6",
        "clock_pin": "PIN_AF14",
        "reset_pin": "PIN_AA14",
        "input_pins": [
            "PIN_AB12", "PIN_AC12", "PIN_AF9",  "PIN_AF10", "PIN_AD11",
            "PIN_AD12", "PIN_AE11", "PIN_AC9",  "PIN_AD10", "PIN_AE12",
            "PIN_AA15", "PIN_W15",  "PIN_Y16",
        ],
        "output_pins": [
            "PIN_AE26", "PIN_AE27", "PIN_AE28", "PIN_AG27", "PIN_AF28", "PIN_AG28", "PIN_AH28",
            "PIN_AJ29", "PIN_AH29", "PIN_AH30", "PIN_AG30", "PIN_AF29", "PIN_AF30", "PIN_AD27",
            "PIN_V16",  "PIN_W16",  "PIN_V17",  "PIN_V18",  "PIN_W17",  "PIN_W19",  "PIN_Y19",
            "PIN_W20",  "PIN_W21",  "PIN_Y21",
        ],
    },
}


@dataclass
class QuartusProjectArtifacts:
    """Paths to generated Quartus II project files."""

    project_dir: Path
    top_module: str
    family: str
    device: str
    qpf_path: Path
    qsf_path: Path
    sdc_path: Path
    tcl_path: Path


def _expand_port_targets(port: PortSpec) -> list[str]:
    if port.width == 1 and not port.width_expr:
        return [port.name]
    return [f"{port.name}[{idx}]" for idx in range(port.width)]


def _generate_pin_assignments(spec: DigitalSpec, preset: dict[str, Any]) -> list[str]:
    """Assign board kit pins without collisions across scalar & bus ports."""
    used_pins: set[str] = set()
    lines: list[str] = []

    in_pool = list(preset.get("input_pins", []))
    out_pool = list(preset.get("output_pins", []))
    in_cursor = 0
    out_cursor = 0

    for port in spec.ports:
        if port.pin_assignment and port.width == 1:
            if port.pin_assignment not in used_pins:
                used_pins.add(port.pin_assignment)
                lines.append(f"set_location_assignment {port.pin_assignment} -to {port.name}")
            continue

        if spec.clock_port and port.name == spec.clock_port:
            cpin = preset["clock_pin"]
            used_pins.add(cpin)
            lines.append(f"set_location_assignment {cpin} -to {port.name}")
            continue

        if spec.reset_port and port.name == spec.reset_port:
            rpin = preset["reset_pin"]
            if rpin not in used_pins:
                used_pins.add(rpin)
                lines.append(f"set_location_assignment {rpin} -to {port.name}")
            continue

        targets = _expand_port_targets(port)
        if port.direction == "input":
            for t in targets:
                while in_cursor < len(in_pool) and in_pool[in_cursor] in used_pins:
                    in_cursor += 1
                if in_cursor < len(in_pool):
                    pin = in_pool[in_cursor]
                    used_pins.add(pin)
                    in_cursor += 1
                    lines.append(f"set_location_assignment {pin} -to {t}")
        elif port.direction == "output":
            for t in targets:
                while out_cursor < len(out_pool) and out_pool[out_cursor] in used_pins:
                    out_cursor += 1
                if out_cursor < len(out_pool):
                    pin = out_pool[out_cursor]
                    used_pins.add(pin)
                    out_cursor += 1
                    lines.append(f"set_location_assignment {pin} -to {t}")

    return lines


def _generate_sdc(spec: DigitalSpec) -> str:
    """Generate clean Synopsys Design Constraints (.sdc) for TimeQuest STA."""
    period_ns = round(1000.0 / spec.clock_freq_mhz, 3)
    in_delay_max = round(period_ns * 0.10, 3)
    in_delay_min = round(period_ns * 0.02, 3)
    out_delay_max = round(period_ns * 0.10, 3)
    out_delay_min = round(period_ns * 0.02, 3)

    port_names = {p.name for p in spec.ports}
    has_clk = bool(spec.clock_port and spec.clock_port in port_names)
    has_rst = bool(spec.reset_port and spec.reset_port in port_names)

    lines = [
        "# Auto-generated Synopsys Design Constraints (.sdc) — fpga_autopilot",
        "set_time_format -unit ns -decimal_places 3",
        "",
    ]

    clk_ref = spec.clock_port if has_clk else "virt_clk"
    if has_clk:
        lines.append(
            f"create_clock -name {{{clk_ref}}} -period {period_ns:.3f} [get_ports {{{clk_ref}}}]"
        )
    else:
        lines.append(f"create_clock -name {{{clk_ref}}} -period {period_ns:.3f}")
    lines.append("derive_clock_uncertainty")
    lines.append("")

    if has_rst:
        if has_clk:
            lines.append(f"set_false_path -from [get_ports {{{spec.reset_port}}}] -to [all_registers]")
        else:
            lines.append(f"set_false_path -from [get_ports {{{spec.reset_port}}}]")
        lines.append("")

    data_inputs = [
        p
        for p in spec.ports
        if p.direction == "input" and p.name not in {spec.clock_port, spec.reset_port}
    ]
    data_outputs = [p for p in spec.ports if p.direction == "output"]

    for inp in data_inputs:
        flt = f"{inp.name}[*]" if (inp.width > 1 or inp.width_expr) else inp.name
        lines.append(f"set_input_delay -clock {{{clk_ref}}} -max {in_delay_max:.3f} [get_ports {{{flt}}}]")
        lines.append(f"set_input_delay -clock {{{clk_ref}}} -min {in_delay_min:.3f} [get_ports {{{flt}}}]")

    for outp in data_outputs:
        flt = f"{outp.name}[*]" if (outp.width > 1 or outp.width_expr) else outp.name
        lines.append(f"set_output_delay -clock {{{clk_ref}}} -max {out_delay_max:.3f} [get_ports {{{flt}}}]")
        lines.append(f"set_output_delay -clock {{{clk_ref}}} -min {out_delay_min:.3f} [get_ports {{{flt}}}]")

    if not has_clk and data_inputs and data_outputs:
        lines.append("")
        lines.append(f"set_max_delay -from [all_inputs] -to [all_outputs] {period_ns:.3f}")

    return "\n".join(lines) + "\n"


def build_quartus_project(
    spec: DigitalSpec,
    rtl_files: list[Path],
    project_dir: Path,
    assign_kit_pins: bool = True,
) -> QuartusProjectArtifacts:
    """Create valid Quartus II .qpf, .qsf, .sdc, and headless Tcl compilation script."""
    project_dir.mkdir(parents=True, exist_ok=True)
    top = spec.top_module or spec.name
    preset = BOARD_PRESETS[spec.board_preset]
    family = spec.fpga_family or preset["family"]
    device = spec.fpga_device or preset["device"]

    qpf_path = project_dir / f"{top}.qpf"
    qsf_path = project_dir / f"{top}.qsf"
    sdc_path = project_dir / f"{top}.sdc"
    tcl_path = project_dir / f"compile_{top}.tcl"

    qpf_content = "\n".join(
        [
            "# Auto-generated Quartus II Project File — fpga_autopilot",
            'QUARTUS_VERSION = "13.0"',
            f'PROJECT_REVISION = "{top}"',
            "",
        ]
    )
    qpf_path.write_text(qpf_content, encoding="utf-8")

    sdc_path.write_text(_generate_sdc(spec), encoding="utf-8")

    qsf_lines = [
        "# Auto-generated Quartus II Settings File (.qsf) — fpga_autopilot",
        f'set_global_assignment -name FAMILY "{family}"',
        f"set_global_assignment -name DEVICE {device}",
        f"set_global_assignment -name TOP_LEVEL_ENTITY {top}",
        "set_global_assignment -name PROJECT_OUTPUT_DIRECTORY output_files",
        "set_global_assignment -name MIN_CORE_JUNCTION_TEMP 0",
        "set_global_assignment -name MAX_CORE_JUNCTION_TEMP 85",
        "set_global_assignment -name ERROR_CHECK_FREQUENCY_DIVISOR 1",
        "set_global_assignment -name VERILOG_INPUT_VERSION SYSTEMVERILOG_2005",
        f"set_global_assignment -name SDC_FILE {sdc_path.name}",
        "",
    ]

    import os

    for rf in rtl_files:
        try:
            sv_ref = os.path.relpath(rf.resolve(), project_dir.resolve()).replace("\\", "/")
        except ValueError:
            sv_ref = rf.resolve().as_posix()
        qsf_lines.append(f'set_global_assignment -name SYSTEMVERILOG_FILE "{sv_ref}"')

    if assign_kit_pins:
        qsf_lines.append("")
        qsf_lines.append(f"# Board Pinout Preset: {spec.board_preset} ({device})")
        qsf_lines.extend(_generate_pin_assignments(spec, preset))

    qsf_lines.append("")
    qsf_lines.append("set_global_assignment -name PARTITION_NETLIST_TYPE SOURCE -section_id Top")
    qsf_lines.append("set_global_assignment -name PARTITION_FITTER_PRESERVATION_LEVEL PLACEMENT_AND_ROUTING -section_id Top")
    qsf_lines.append("set_global_assignment -name PARTITION_COLOR 16764057 -section_id Top")
    qsf_lines.append("set_instance_assignment -name PARTITION_HIERARCHY root_partition -to | -section_id Top")
    qsf_lines.append("")
    qsf_path.write_text("\n".join(qsf_lines), encoding="utf-8")

    tcl_content = "\n".join(
        [
            "# Headless Quartus II Compilation Tcl Script — fpga_autopilot",
            "package require ::quartus::project",
            "package require ::quartus::flow",
            f'project_open "{top}" -revision "{top}"',
            "execute_module -tool map",
            "execute_module -tool fit",
            "execute_module -tool sta",
            "project_close",
            "",
        ]
    )
    tcl_path.write_text(tcl_content, encoding="utf-8")

    return QuartusProjectArtifacts(
        project_dir=project_dir,
        top_module=top,
        family=family,
        device=device,
        qpf_path=qpf_path,
        qsf_path=qsf_path,
        sdc_path=sdc_path,
        tcl_path=tcl_path,
    )
