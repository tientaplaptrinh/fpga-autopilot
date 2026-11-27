# Headless Quartus II Compilation Tcl Script — fpga_autopilot
package require ::quartus::project
package require ::quartus::flow
project_open "traffic_fsm" -revision "traffic_fsm"
execute_module -tool map
execute_module -tool fit
execute_module -tool sta
project_close
