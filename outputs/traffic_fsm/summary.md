# Engineering Verification Summary — `traffic_fsm`

**Title:** Parameterized Clock Divider + Smart Traffic Light Moore FSM  
**Top Module:** `traffic_fsm`  
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
- **Vectors Passed:** `230 / 230` (`0` failures)
- **Runtime:** `0.095 s`
- **Waveform VCD:** `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\traffic_fsm\sim\traffic_fsm.vcd`

## 3. Hardware Resource Utilization & Timing (`quartus`)

| Metric | Value |
| :--- | ---: |
| Logic Elements / ALMs | 133 |
| Combinational Functions (LUTs) | 132 |
| Dedicated Logic Registers | 81 |
| Memory Bits | 0 |
| DSP / Multiplier Elements | 0 |
| Total I/O Pins | 15 |
| Inferred Latches | 0 |
| Worst-Case Fmax | 71.69 MHz |
| Worst Setup Slack | 6.051 ns |
| Worst Hold Slack | 0.181 ns |

## 4. Generated Artifacts & Visual Captures
- **Quartus Project (`.qpf`):** `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\traffic_fsm\quartus\traffic_fsm.qpf`
- **Quartus Settings (`.qsf`):** `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\traffic_fsm\quartus\traffic_fsm.qsf`
- **Timing Constraints (`.sdc`):** `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\traffic_fsm\quartus\traffic_fsm.sdc`
- **gtkwave_waveform** (`1420x820`, audit=`True`): `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\traffic_fsm\traffic_fsm_waveform.png`
- **quartus_rtl_viewer** (`1460x860`, audit=`True`): `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\traffic_fsm\traffic_fsm_rtl_viewer.png`
- **quartus_fsm_viewer** (`1460x860`, audit=`True`): `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\traffic_fsm\traffic_fsm_fsm_viewer.png`
