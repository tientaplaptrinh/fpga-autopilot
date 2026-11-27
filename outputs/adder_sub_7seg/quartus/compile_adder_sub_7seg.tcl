# Headless Quartus II Compilation Tcl Script — fpga_autopilot
package require ::quartus::project
package require ::quartus::flow
project_open "adder_sub_7seg" -revision "adder_sub_7seg"
execute_module -tool map
execute_module -tool fit
execute_module -tool sta
project_close
