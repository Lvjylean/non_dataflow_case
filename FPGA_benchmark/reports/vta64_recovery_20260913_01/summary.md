# VTA64 routed-checkpoint recovery

Current acceptance: **REVIEW_REQUIRED**. See [complete results](../recovery_summary_zh.md) and platform_validation.json.

Native bitstream generation succeeded. The raw v++ recovery exited 1 at rtdgen because the fresh reuse directory lacked address_map.xml; that failure remains recorded. The generated bitstream was successfully packaged in vta64_container_20260913_01 using the same-source corrected address map and native cf2sw/xclbinutil commands. First and second physical audit outcomes, unchanged checkpoint hashes, resource comparisons, timing coverage and remaining review findings are recorded separately. Legacy REF_NAME DSP/BRAM leaf counters are not physical resource totals; native utilization is authoritative.

Server directory: /Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark/runs/vta64_recovery_20260913_01
Source DCP: /Projects/jinyang/workspace/non_dataflow_crossSLR/case/FPGA_benchmark/runs/vta64_platform_20260913_02/physical/routed.dcp
