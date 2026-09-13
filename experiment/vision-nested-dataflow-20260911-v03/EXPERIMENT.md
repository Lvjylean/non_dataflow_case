# Vision ISP parameter scaling

User-authorized follow-up to v02 under identical LUT108000–864000, U250,5ns criteria. Demosaic source supports NPC1/2/4 only; do not use8. GTM supports1/2 only and is not increased. This batch: Bayer ISP NPC4 with128-bit ports; HDR ISP NPC4 with128-bit ports; all-in-one1080p NPC2 andNPC4 (output256 bits for4*RGB16 pixel lanes). Original pipeline functions and DATAFLOW placement unchanged; no manual replicas. Check compiled top/no and nested DATAFLOW. Numeric and physical validity not established by HLS alone. Server case/experiment/vision-nested-dataflow-20260911-v03. Two workers with1800s HLS trial limit.

Completed; see reports/vision-summary.md. Qualified runs were moved to independent resource-labeled directories; current paths in reports/vision-cases.json. Original batch run paths are historical.
