# Retained Vitis HLS cases

Only these four successful public cases remain after cleanup on 2026-09-11.

| Case | Source path | Server run, relative to case/experiment/ |
|---|---|---|
| 01 2mm, U250 | allo-pldi24-artifact/polybench/vitis/2mm/ | 01_2mm_vitis_u250/ |
| 02 3mm, U250 | allo-pldi24-artifact/polybench/vitis/3mm/ | 02_3mm_vitis_u250/ |
| 03 Jacobi-2D, U280 | allo-pldi24-artifact/polybench/vitis/jacobi-2d/ | 03_jacobi_2d_vitis_u280/ |
| 09 Minimap2, U250 | minimap2-acceleration/kernel/hls/ | 09_minimap2_vitis_u250/ |

Server case root: /Projects/jinyang/workspace/non_dataflow_crossSLR/case/ on eda070.
Each run contains run.tcl, run.log, status.json, hls/sol/syn/verilog/ and hls/sol/syn/report/.
The repository name allo-pldi24-artifact identifies provenance; only Vitis implementations remain. Source revisions are recorded in sources.json. Source files and retained generated artifacts are unchanged. Experiment directories were renamed by case and board; public-cases.json under experiment records current and original paths. These are curated source snapshots, not complete Git checkouts.

Allo implementations, failed APFP/GPT cases, retries and unrelated variants were removed at user request. Minimap2 testbed is kept for future validation. The earlier Vitis_Libraries experiments are separate and unaffected.

PASS means Vitis HLS 2023.2 synthesis with generated RTL. It does not establish numerical correctness, physical fit, timing closure or board execution. Raw generated artifacts remain server-only; compact reports are in the workspace reports/ directory.

完整来源索引：[source.md](source.md)，包含 Vitis Libraries、公共 GitHub case 及派生实验。
