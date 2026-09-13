# Vision borderline and optical-flow scaling

Same U250/5ns HLS criteria and 108000–864000 LUT requirement. HDR4 at4K measured106480 LUT (below108000); try8192x4320 atNPC4 within uint16 dimensions,128-bit interfaces. TV-L1 original512²/NPC2 measured259512 LUT and13 childDATAFLOW reports; additional trials change max supported flow6→10 (larger remap neighborhood) or max resolution512²→1024² (unchanged flow6,NPC2). No pipeline/algorithm source edits or artificial copies. Parameter modifications only in copied configuration headers. Source/dataflow/size/report validation required. Not numerical or physical validation. Server case/experiment/vision-nested-dataflow-20260911-v04; two workers,1800s HLS limit.

Completed; see reports/vision-summary.md. Qualified runs were moved to independent resource-labeled directories; current paths in reports/vision-cases.json. Original batch run paths are historical.
