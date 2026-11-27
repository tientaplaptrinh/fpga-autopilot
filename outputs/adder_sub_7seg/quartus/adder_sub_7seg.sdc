# Auto-generated Synopsys Design Constraints (.sdc) — fpga_autopilot
set_time_format -unit ns -decimal_places 3

create_clock -name {virt_clk} -period 20.000
derive_clock_uncertainty

set_input_delay -clock {virt_clk} -max 2.000 [get_ports {a[*]}]
set_input_delay -clock {virt_clk} -min 0.400 [get_ports {a[*]}]
set_input_delay -clock {virt_clk} -max 2.000 [get_ports {b[*]}]
set_input_delay -clock {virt_clk} -min 0.400 [get_ports {b[*]}]
set_input_delay -clock {virt_clk} -max 2.000 [get_ports {sub_mode}]
set_input_delay -clock {virt_clk} -min 0.400 [get_ports {sub_mode}]
set_output_delay -clock {virt_clk} -max 2.000 [get_ports {result[*]}]
set_output_delay -clock {virt_clk} -min 0.400 [get_ports {result[*]}]
set_output_delay -clock {virt_clk} -max 2.000 [get_ports {cout}]
set_output_delay -clock {virt_clk} -min 0.400 [get_ports {cout}]
set_output_delay -clock {virt_clk} -max 2.000 [get_ports {overflow}]
set_output_delay -clock {virt_clk} -min 0.400 [get_ports {overflow}]
set_output_delay -clock {virt_clk} -max 2.000 [get_ports {zero}]
set_output_delay -clock {virt_clk} -min 0.400 [get_ports {zero}]
set_output_delay -clock {virt_clk} -max 2.000 [get_ports {seg_sign[*]}]
set_output_delay -clock {virt_clk} -min 0.400 [get_ports {seg_sign[*]}]
set_output_delay -clock {virt_clk} -max 2.000 [get_ports {seg_mag[*]}]
set_output_delay -clock {virt_clk} -min 0.400 [get_ports {seg_mag[*]}]

set_max_delay -from [all_inputs] -to [all_outputs] 20.000
