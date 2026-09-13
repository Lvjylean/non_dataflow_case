set_param general.maxThreads 2
open_checkpoint /Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/orb_u250_5ns_fanout256_20260911_01/pu64/post_opt.dcp
source reset_buffer.tcl
report_drc -file preflight_drc.rpt
write_checkpoint buffered_post_opt.dcp
