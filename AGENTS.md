# Digital Design & Quartus II Autopilot (`fpga_autopilot/`)

## Architecture & Engineering Mandates

1. **Strict Synthesizable SystemVerilog Rules (`rtl_studio/`)**
   - Always use SystemVerilog-2012 constructs: `logic`, `always_ff @(posedge clk or negedge rst_n)`, `always_comb`, and typed `typedef enum logic [...]` for FSM states.
   - Use non-blocking assignments (`<=`) exclusively in sequential (`always_ff`) blocks, and blocking assignments (`=`) exclusively in combinational (`always_comb`) blocks.
   - Include explicit default assignments at the top of every `always_comb` block to guarantee **0 inferred latches**.

2. **Self-Checking Verification & Closed-Loop Self-Healing (`sim_loop/`)**
   - Every DUT is paired with a self-checking SystemVerilog testbench with cycle-accurate golden reference comparison, corner-case vectors, constrained-random stimulus, and `.vcd` waveform generation.
   - Structured output markers:
     - `[FAIL] cycle=%0d input=%h exp=%h got=%h`
     - `[SUMMARY] passed=%0d failed=%0d`
   - `self_healer.py` never weakens or deletes testbench assertions; it only patches genuine RTL lint/functional issues (up to 6 iterations).

3. **Quartus II Compilation & Fallback Synthesis (`quartus_driver/`)**
   - Generates `.qpf`, `.qsf` (with presets for `DE2-115`, `DE10-Lite`, `DE1-SoC`), `.sdc` timing constraints, and Tcl automation scripts.
   - Runs real `quartus_map` -> `quartus_fit` -> `quartus_sta` when Quartus II supports the target family, with automatic `yosys` fallback if Quartus CLI or target device family is unavailable.

4. **Desktop Mouse/Keyboard GUI Safety Protocol (`quartus_driver/gui_inspector.py`)**
   - `pyautogui.FAILSAFE = True` globally (`(0, 0)` immediately aborts).
   - **Strict Window Confinement:** Every mouse move/click verifies the target coordinates fall strictly inside the active target EDA window (`gtkwave`, `quartus`, `vsim`). Any out-of-bounds action raises `WindowConfinementError`.
   - Every screenshot, detected UI region, and mouse/keyboard action is logged to `./artifacts/gui_audit/`.
   - Deterministic CLI flags, `.gtkw` savefiles, and keyboard shortcuts take priority over mouse clicks.

5. **CLI Quickstart**
   ```powershell
   .\.venv\Scripts\python.exe -m cli audit
   .\.venv\Scripts\python.exe -m cli run --spec benchmarks/lab_specs.yaml --all
   .\.venv\Scripts\pytest.exe -q
   ```
