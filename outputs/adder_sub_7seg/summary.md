# Engineering Verification Summary — `adder_sub_7seg`

**Title:** 4-Bit Signed Adder/Subtractor + Dual 7-Segment Decoder  
**Top Module:** `adder_sub_7seg`  
**Target Board / Device:** `DE2-115` (`Cyclone IV E` — `EP4CE115F29C7`)  
**Overall Gate Status:** **PASS**

## 1. Static Lint & Synchronous Design Audit
- **Lint Status:** `PASS` (Tools: `static_analyzer, verilator, iverilog`)
- **Inferred Latches:** `0` (Synthesis Latches: `0`)
- **Blocking in `always_ff`:** `0`
- **Width Mismatches:** `0`
- **Self-Healing Patch Iterations:** `0`

## 2. Cycle-Accurate Self-Checking Simulation
- **Simulator:** `iverilog`
- **Vectors Passed:** `512 / 512` (`0` failures)
- **Runtime:** `0.095 s`
- **Waveform VCD:** `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\adder_sub_7seg\sim\adder_sub_7seg.vcd`

## 3. Hardware Resource Utilization & Timing (`quartus`)

| Metric | Value |
| :--- | ---: |
| Logic Elements / ALMs | 19 |
| Combinational Functions (LUTs) | 19 |
| Dedicated Logic Registers | 0 |
| Memory Bits | 0 |
| DSP / Multiplier Elements | 0 |
| Total I/O Pins | 30 |
| Inferred Latches | 0 |
| Worst-Case Fmax | 61.88 MHz |
| Worst Setup Slack | 3.840 ns |
| Worst Hold Slack | 4.439 ns |

## 4. Generated Artifacts & Visual Captures
- **Quartus Project (`.qpf`):** `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\adder_sub_7seg\quartus\adder_sub_7seg.qpf`
- **Quartus Settings (`.qsf`):** `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\adder_sub_7seg\quartus\adder_sub_7seg.qsf`
- **Timing Constraints (`.sdc`):** `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\adder_sub_7seg\quartus\adder_sub_7seg.sdc`
- **gtkwave_waveform** (`1420x820`, audit=`True`): `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\adder_sub_7seg\adder_sub_7seg_waveform.png`
- **quartus_rtl_viewer** (`1460x860`, audit=`True`): `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\adder_sub_7seg\adder_sub_7seg_rtl_viewer.png`
