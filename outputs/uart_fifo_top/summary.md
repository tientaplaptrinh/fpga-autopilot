# Engineering Verification Summary — `uart_fifo_top`

**Title:** Configurable UART TX/RX Transceiver with 8-Byte Sync FIFO  
**Top Module:** `uart_fifo_top`  
**Target Board / Device:** `DE1-SoC` (`Cyclone V` — `5CSEMA5F31C6`)  
**Overall Gate Status:** **PASS**

## 1. Static Lint & Synchronous Design Audit
- **Lint Status:** `PASS` (Tools: `static_analyzer, verilator, iverilog`)
- **Inferred Latches:** `0` (Synthesis Latches: `0`)
- **Blocking in `always_ff`:** `0`
- **Width Mismatches:** `0`
- **Self-Healing Patch Iterations:** `0`

## 2. Cycle-Accurate Self-Checking Simulation
- **Simulator:** `iverilog`
- **Vectors Passed:** `66 / 66` (`0` failures)
- **Runtime:** `0.413 s`
- **Waveform VCD:** `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\uart_fifo_top\sim\uart_fifo_top.vcd`

## 3. Hardware Resource Utilization & Timing (`quartus`)

| Metric | Value |
| :--- | ---: |
| Logic Elements / ALMs | 182 |
| Combinational Functions (LUTs) | 269 |
| Dedicated Logic Registers | 283 |
| Memory Bits | 0 |
| DSP / Multiplier Elements | 0 |
| Total I/O Pins | 29 |
| Inferred Latches | 0 |
| Worst-Case Fmax | 70.46 MHz |
| Worst Setup Slack | 5.808 ns |
| Worst Hold Slack | 0.159 ns |

## 4. Generated Artifacts & Visual Captures
- **Quartus Project (`.qpf`):** `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\uart_fifo_top\quartus\uart_fifo_top.qpf`
- **Quartus Settings (`.qsf`):** `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\uart_fifo_top\quartus\uart_fifo_top.qsf`
- **Timing Constraints (`.sdc`):** `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\uart_fifo_top\quartus\uart_fifo_top.sdc`
- **gtkwave_waveform** (`1420x820`, audit=`True`): `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\uart_fifo_top\uart_fifo_top_waveform.png`
- **quartus_rtl_viewer** (`1460x860`, audit=`True`): `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\uart_fifo_top\uart_fifo_top_rtl_viewer.png`
- **quartus_fsm_viewer** (`1460x860`, audit=`True`): `C:\Users\DELL INSPIRON 5515\.gemini\antigravity\scratch\fpga_autopilot\outputs\uart_fifo_top\uart_fifo_top_fsm_viewer.png`
