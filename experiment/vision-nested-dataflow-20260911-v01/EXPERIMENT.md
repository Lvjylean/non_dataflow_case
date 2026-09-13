# Vision top non-dataflow screening

User requested batch Vitis compilation, especially vision, including internal DATAFLOW, LUT 108000–864000 (0.25–2 U250 SLR). Size=max(LUT/432000,FF/864000,DSP/3072,BRAM18K/1344,URAM/320), label dominant resource and percentage separately from LUT eligibility. 5 ns HLS clock, U250, Vitis HLS 2023.2. Two workers, 1800 seconds per HLS trial; never terminate Vivado.

Server: /Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/vision-nested-dataflow-20260911-v01

Seven initial trials: BFMatcher PU256/512 (no internal DATAFLOW); MeanShift objects10/64, Rotate tile256 NPC2, Flip RGB NPC8 8192x4320, Harris corner tracker 4K filter7/block7 (internal DATAFLOW expected). Preserve upstream tops and library implementations; modify only case-local configuration parameters. No outer non-dataflow wrapper or artificial replicated copies. Confirm compiled top pipeline type and child DATAFLOW from HLS reports; source pragma alone does not establish synthesized hierarchy. Small or failed trials are diagnostic, not accepted results. No numerical correctness/RTL cosimulation or physical fit claims.

User reference to second/third groups is pending clarification; initial selection is independently grounded in inspected vision source.

Completed; see reports/vision-summary.md. Qualified runs were moved to independent resource-labeled directories; current paths in reports/vision-cases.json. Original batch run paths are historical.
