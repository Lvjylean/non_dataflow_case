# Vision nested DATAFLOW second batch

Same user-authorized 108000–864000 LUT window, max-resource/SLR size label, U250, Vitis HLS2023.2 at5ns and two workers as v01. Server case/experiment/vision-nested-dataflow-20260911-v02. Function-scope source inspection identifies non-DATAFLOW tops calling DATAFLOW helpers: Bayer ISP, HDR ISP, RGBIR ISP, global-tonemap ISP, all-in-one ISP, TV-L1 optical flow. Compile original configurations first. Add BFMatcher PU64/128 because PU256 measured834528 LUT (near upper limit); these controls have no internal DATAFLOW. Only BFMatcher config parameters changed; preserve all vision pipeline architecture. Compile outputs and hierarchy evidence required; no numerical/physical validation claimed.

Completed; see reports/vision-summary.md. Qualified runs were moved to independent resource-labeled directories; current paths in reports/vision-cases.json. Original batch run paths are historical.
