# Auto-generated Synopsys Design Constraints (.sdc) — fpga_autopilot
set_time_format -unit ns -decimal_places 3

create_clock -name {clk} -period 20.000 [get_ports {clk}]
derive_clock_uncertainty

set_false_path -from [get_ports {rst_n}] -to [all_registers]

set_input_delay -clock {clk} -max 2.000 [get_ports {wr_en}]
set_input_delay -clock {clk} -min 0.400 [get_ports {wr_en}]
set_input_delay -clock {clk} -max 2.000 [get_ports {wr_data[*]}]
set_input_delay -clock {clk} -min 0.400 [get_ports {wr_data[*]}]
set_input_delay -clock {clk} -max 2.000 [get_ports {rd_en}]
set_input_delay -clock {clk} -min 0.400 [get_ports {rd_en}]
set_input_delay -clock {clk} -max 2.000 [get_ports {rx_serial}]
set_input_delay -clock {clk} -min 0.400 [get_ports {rx_serial}]
set_input_delay -clock {clk} -max 2.000 [get_ports {clr_err}]
set_input_delay -clock {clk} -min 0.400 [get_ports {clr_err}]
set_output_delay -clock {clk} -max 2.000 [get_ports {tx_serial}]
set_output_delay -clock {clk} -min 0.400 [get_ports {tx_serial}]
set_output_delay -clock {clk} -max 2.000 [get_ports {rd_data[*]}]
set_output_delay -clock {clk} -min 0.400 [get_ports {rd_data[*]}]
set_output_delay -clock {clk} -max 2.000 [get_ports {tx_full}]
set_output_delay -clock {clk} -min 0.400 [get_ports {tx_full}]
set_output_delay -clock {clk} -max 2.000 [get_ports {tx_empty}]
set_output_delay -clock {clk} -min 0.400 [get_ports {tx_empty}]
set_output_delay -clock {clk} -max 2.000 [get_ports {rx_full}]
set_output_delay -clock {clk} -min 0.400 [get_ports {rx_full}]
set_output_delay -clock {clk} -max 2.000 [get_ports {rx_empty}]
set_output_delay -clock {clk} -min 0.400 [get_ports {rx_empty}]
set_output_delay -clock {clk} -max 2.000 [get_ports {tx_busy}]
set_output_delay -clock {clk} -min 0.400 [get_ports {tx_busy}]
set_output_delay -clock {clk} -max 2.000 [get_ports {framing_error}]
set_output_delay -clock {clk} -min 0.400 [get_ports {framing_error}]
