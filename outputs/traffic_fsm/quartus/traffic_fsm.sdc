# Auto-generated Synopsys Design Constraints (.sdc) — fpga_autopilot
set_time_format -unit ns -decimal_places 3

create_clock -name {clk} -period 20.000 [get_ports {clk}]
derive_clock_uncertainty

set_false_path -from [get_ports {rst_n}] -to [all_registers]

set_input_delay -clock {clk} -max 2.000 [get_ports {ped_btn_raw}]
set_input_delay -clock {clk} -min 0.400 [get_ports {ped_btn_raw}]
set_input_delay -clock {clk} -max 2.000 [get_ports {emergency_ovr}]
set_input_delay -clock {clk} -min 0.400 [get_ports {emergency_ovr}]
set_output_delay -clock {clk} -max 2.000 [get_ports {ns_light[*]}]
set_output_delay -clock {clk} -min 0.400 [get_ports {ns_light[*]}]
set_output_delay -clock {clk} -max 2.000 [get_ports {ew_light[*]}]
set_output_delay -clock {clk} -min 0.400 [get_ports {ew_light[*]}]
set_output_delay -clock {clk} -max 2.000 [get_ports {ped_walk}]
set_output_delay -clock {clk} -min 0.400 [get_ports {ped_walk}]
set_output_delay -clock {clk} -max 2.000 [get_ports {countdown[*]}]
set_output_delay -clock {clk} -min 0.400 [get_ports {countdown[*]}]
