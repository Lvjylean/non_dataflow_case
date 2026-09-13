# Case 来源索引

更新日期：2026-09-11。服务器：`eda070`；根目录：`/Projects/jinyang/workspace/non_dataflow_crossSLR/case/`。

本文件覆盖当前 `case/` 下的源码库和已登记实验，包括参数化版本、Vision 批次及派生的 Vivado 实验。来源登记不表示实验已通过；执行结果以各实验日志及状态文件为准。表格中的实验路径均相对于 `case/`。

## 上游仓库与版本

| 本地源码目录 | 上游仓库 | 使用版本（commit） |
|---|---|---|
| `Vitis_Libraries/` | [AMD/Xilinx Vitis Libraries](https://github.com/Xilinx/Vitis_Libraries) | [`3ab1ecd20cf338b3f8f2824fdfeee115f3398889`](https://github.com/Xilinx/Vitis_Libraries/commit/3ab1ecd20cf338b3f8f2824fdfeee115f3398889) |
| `allo-pldi24-artifact/` | [allo-pldi24-artifact](https://github.com/cornell-zhang/allo-pldi24-artifact) | [`f7e3fa200049ff9bf3cc730d68b1a162c1a63f31`](https://github.com/cornell-zhang/allo-pldi24-artifact/commit/f7e3fa200049ff9bf3cc730d68b1a162c1a63f31) |
| `minimap2-acceleration/` | [minimap2-acceleration](https://github.com/UCLA-VAST/minimap2-acceleration) | [`a50f8c503c3e25b7babe6c78367cd4b672fcb395`](https://github.com/UCLA-VAST/minimap2-acceleration/commit/a50f8c503c3e25b7babe6c78367cd4b672fcb395) |

Vitis Libraries 官方文档：[Vitis Libraries](https://docs.amd.com/r/en-US/Vitis_Libraries)。上方 commit 用于准确定位本次下载版本，不以持续更新的主分支替代。

`allo-pldi24-artifact` 是上游仓库名；当前仅使用其中 `polybench/vitis/` 的 C++ 实现，不使用 Allo 生成版本。公共仓库已精简为源码快照，版本信息由 `sources.json` 保留；Vitis Libraries 版本从服务器 Git checkout 核对。

## 公共 Vitis HLS case

| Case / 板卡 | 当前实验目录 | 固定版本的上游源文件 |
|---|---|---|
| 01_2mm_vitis_u250 / U250 | `experiment/01_2mm_vitis_u250/` | [polybench/vitis/2mm/2mm.cpp](https://github.com/cornell-zhang/allo-pldi24-artifact/blob/f7e3fa200049ff9bf3cc730d68b1a162c1a63f31/polybench/vitis/2mm/2mm.cpp) |
| 02_3mm_vitis_u250 / U250 | `experiment/02_3mm_vitis_u250/` | [polybench/vitis/3mm/3mm.cpp](https://github.com/cornell-zhang/allo-pldi24-artifact/blob/f7e3fa200049ff9bf3cc730d68b1a162c1a63f31/polybench/vitis/3mm/3mm.cpp) |
| 03_jacobi_2d_vitis_u280 / U280 | `experiment/03_jacobi_2d_vitis_u280/` | [polybench/vitis/jacobi-2d/jacobi-2d.cpp](https://github.com/cornell-zhang/allo-pldi24-artifact/blob/f7e3fa200049ff9bf3cc730d68b1a162c1a63f31/polybench/vitis/jacobi-2d/jacobi-2d.cpp) |
| 09_minimap2_vitis_u250 / U250 | `experiment/09_minimap2_vitis_u250/` | [kernel/hls/src/device_kernel.cpp](https://github.com/UCLA-VAST/minimap2-acceleration/blob/a50f8c503c3e25b7babe6c78367cd4b672fcb395/kernel/hls/src/device_kernel.cpp) |

这四项的源代码保持上游内容；板卡选择、时钟和运行入口由实验目录中的 `run.tcl` 记录。Minimap2 原工程面向 VCU1525，当前 U250 目录记录的是 HLS 综合配置；该路径本身不代表完整跑板移植。

Minimap2 的主机端代码及头文件与内核放在 `kernel/hls/src/`；保留的 [`testbed/`](https://github.com/UCLA-VAST/minimap2-acceleration/tree/a50f8c503c3e25b7babe6c78367cd4b672fcb395/testbed) 来自同一仓库，用于后续测试。

## Vitis Libraries：数值计算及安全 case

以下实验来自 Vitis Libraries。上游入口链接指向原始文件；实验中的矩阵规模、并行度或位宽是本地配置，不应视为上游默认参数。

| 实验目录 | Case | 参数 | 上游入口（固定版本） |
|---|---|---|
| `experiment/geqrf_20260911_103020_v01/` | geqrf | `MA=16, NA=16, NCU=4` | [solver/L2/tests/hw/geqrf/kernel_geqrf.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/geqrf/kernel_geqrf.cpp) |
| `experiment/geqrf_20260911_103129_v02/` | geqrf | `MA=256, NA=256, NCU=32` | [solver/L2/tests/hw/geqrf/kernel_geqrf.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/geqrf/kernel_geqrf.cpp) |
| `experiment/geqrf_20260911_103401_v03/` | geqrf | `MA=256, NA=256, NCU=128` | [solver/L2/tests/hw/geqrf/kernel_geqrf.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/geqrf/kernel_geqrf.cpp) |
| `experiment/geqrf_20260911_105014_v04/` | geqrf | `MA=512, NA=512, NCU=256` | [solver/L2/tests/hw/geqrf/kernel_geqrf.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/geqrf/kernel_geqrf.cpp) |
| `experiment/geqrf_20260911_105252_v05/` | geqrf | `MA=768, NA=768, NCU=384` | [solver/L2/tests/hw/geqrf/kernel_geqrf.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/geqrf/kernel_geqrf.cpp) |
| `experiment/gesvdj_20260911_103045_v01/` | gesvdj | `MA=16` | [solver/L2/benchmarks/gesvdj/kernel_gesvdj.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/benchmarks/gesvdj/kernel_gesvdj.cpp) |
| `experiment/gesvdj_20260911_103156_v02/` | gesvdj | `MA=64, UN=8` | [solver/L2/benchmarks/gesvdj/kernel_gesvdj.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/benchmarks/gesvdj/kernel_gesvdj.cpp) |
| `experiment/gesvdj_20260911_103438_v03/` | gesvdj | `MA=128, UN=16` | [solver/L2/benchmarks/gesvdj/kernel_gesvdj.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/benchmarks/gesvdj/kernel_gesvdj.cpp) |
| `experiment/getrf_20260911_103020_v01/` | getrf | `NRC=16, NCU=1` | [solver/L2/tests/hw/getrf/kernel_getrf.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/getrf/kernel_getrf.cpp) |
| `experiment/getrf_20260911_103129_v02/` | getrf | `NRC=256, NCU=32` | [solver/L2/tests/hw/getrf/kernel_getrf.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/getrf/kernel_getrf.cpp) |
| `experiment/getrf_20260911_103401_v03/` | getrf | `NRC=256, NCU=128` | [solver/L2/tests/hw/getrf/kernel_getrf.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/getrf/kernel_getrf.cpp) |
| `experiment/getrf_20260911_103710_v04/` | getrf | `NRC=1024, NCU=512` | [solver/L2/tests/hw/getrf/kernel_getrf.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/getrf/kernel_getrf.cpp) |
| `experiment/getrf_20260911_105014_v05/` | getrf | `NRC=512, NCU=256` | [solver/L2/tests/hw/getrf/kernel_getrf.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/getrf/kernel_getrf.cpp) |
| `experiment/getrf_nopivot_20260911_103020_v01/` | getrf_nopivot | `NRC=16, NCU=1` | [solver/L2/tests/hw/getrf_nopivot/kernel_getrf_nopivot.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/getrf_nopivot/kernel_getrf_nopivot.cpp) |
| `experiment/getrf_nopivot_20260911_103129_v02/` | getrf_nopivot | `NRC=256, NCU=32` | [solver/L2/tests/hw/getrf_nopivot/kernel_getrf_nopivot.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/getrf_nopivot/kernel_getrf_nopivot.cpp) |
| `experiment/getrf_nopivot_20260911_103401_v03/` | getrf_nopivot | `NRC=256, NCU=128` | [solver/L2/tests/hw/getrf_nopivot/kernel_getrf_nopivot.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/getrf_nopivot/kernel_getrf_nopivot.cpp) |
| `experiment/getrf_nopivot_20260911_104359_v04/` | getrf_nopivot | `NRC=1024, NCU=512` | [solver/L2/tests/hw/getrf_nopivot/kernel_getrf_nopivot.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/getrf_nopivot/kernel_getrf_nopivot.cpp) |
| `experiment/getrf_nopivot_20260911_105014_v05/` | getrf_nopivot | `NRC=512, NCU=256` | [solver/L2/tests/hw/getrf_nopivot/kernel_getrf_nopivot.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/getrf_nopivot/kernel_getrf_nopivot.cpp) |
| `experiment/gtsv_20260911_103106_v01/` | gtsv | `NRC=16, NCU=1` | [solver/L2/benchmarks/gtsv/kernel_gtsv.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/benchmarks/gtsv/kernel_gtsv.cpp) |
| `experiment/gtsv_20260911_103218_v02/` | gtsv | `NRC=256, NCU=32` | [solver/L2/benchmarks/gtsv/kernel_gtsv.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/benchmarks/gtsv/kernel_gtsv.cpp) |
| `experiment/rsa_20260911_103107_v01/` | rsa | `N=2048, L=20` | [security/L1/tests/rsa/test.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/security/L1/tests/rsa/test.cpp) |
| `experiment/rsa_20260911_103221_v02/` | rsa | `N=4096, L=20` | [security/L1/tests/rsa/test.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/security/L1/tests/rsa/test.cpp) |
| `experiment/trtrs_20260911_103043_v01/` | trtrs | `NCU=2, MAXN=16, LDA=16, LDB=2` | [solver/L2/tests/hw/trtrs/kernel_trtrs.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/trtrs/kernel_trtrs.cpp) |
| `experiment/trtrs_20260911_103154_v02/` | trtrs | `NCU=32, MAXN=256, LDA=256, LDB=2` | [solver/L2/tests/hw/trtrs/kernel_trtrs.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/trtrs/kernel_trtrs.cpp) |
| `experiment/trtrs_20260911_103437_v03/` | trtrs | `NCU=128, MAXN=256, LDA=256, LDB=2` | [solver/L2/tests/hw/trtrs/kernel_trtrs.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/trtrs/kernel_trtrs.cpp) |
| `experiment/trtrs_20260911_105125_v04/` | trtrs | `NCU=256, MAXN=512, LDA=512, LDB=2` | [solver/L2/tests/hw/trtrs/kernel_trtrs.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/trtrs/kernel_trtrs.cpp) |
| `experiment/trtrs_20260911_110300_v05/` | trtrs | `NCU=512, MAXN=1024, LDA=1024, LDB=2` | [solver/L2/tests/hw/trtrs/kernel_trtrs.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/solver/L2/tests/hw/trtrs/kernel_trtrs.cpp) |

对应算法实现和依赖头文件来自同一版本的 `solver/L2/include/`、`solver/L1/include/` 或 `security/L1/include/`。每个实验的 `case.json`、源文件和配置记录本地派生关系；`experiment/hls-nondataflow-results.json` 提供汇总。

## Vitis Libraries：Vision case

下列 case 按现有 `jobs.json` 登记。源码与依赖来自同一 Vitis Libraries checkout；参数调整及 HLS 适配配置来自本地实验。原始入口文件与参数化副本应分开理解。

| 实验批次 / Case | 上游入口（固定版本） | 显式参数修改 |
|---|---|---|
| `experiment/vision-nested-dataflow-20260911-v01/` → `vision_orb_matcher_k8192_pu256` | [vision/L2/examples/bfmatcher/xf_bfmatcher_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L2/examples/bfmatcher/xf_bfmatcher_accel.cpp) | PARALLEL_COMPUTEUNIT=256, MAX_KEYPOINTS=8192 |
| `experiment/vision-nested-dataflow-20260911-v01/` → `vision_orb_matcher_k8192_pu512` | [vision/L2/examples/bfmatcher/xf_bfmatcher_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L2/examples/bfmatcher/xf_bfmatcher_accel.cpp) | PARALLEL_COMPUTEUNIT=512, MAX_KEYPOINTS=8192 |
| `experiment/vision-nested-dataflow-20260911-v01/` → `vision_meanshift_1080p_objects10` | [vision/L2/examples/meanshifttracking/xf_mean_shift_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L2/examples/meanshifttracking/xf_mean_shift_accel.cpp) | 未登记参数修改 |
| `experiment/vision-nested-dataflow-20260911-v01/` → `vision_meanshift_1080p_objects64` | [vision/L2/examples/meanshifttracking/xf_mean_shift_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L2/examples/meanshifttracking/xf_mean_shift_accel.cpp) | XF_MAX_OBJECTS=64 |
| `experiment/vision-nested-dataflow-20260911-v01/` → `vision_rotate_4k_tile256_npc2` | [vision/L2/examples/rotate/xf_rotate_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L2/examples/rotate/xf_rotate_accel.cpp) | TILE_SIZE=256, NPPCX=XF_NPPC2, INPUT_PTR_WIDTH=16, OUTPUT_PTR_WIDTH=16 |
| `experiment/vision-nested-dataflow-20260911-v01/` → `vision_flip_8k_rgb_npc8` | [vision/L2/examples/flip/xf_flip_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L2/examples/flip/xf_flip_accel.cpp) | HEIGHT=4320, WIDTH=8192, NPPCX=XF_NPPC8, IN_TYPE=XF_8UC3, OUT_TYPE=XF_8UC3, INPUT_PTR_WIDTH=256, OUTPUT_PTR_WIDTH=256, RGB=1, GRAY=0 |
| `experiment/vision-nested-dataflow-20260911-v01/` → `vision_harris_corners_4k_filter7` | [vision/L3/examples/cornertracker/xf_corner_tracker_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L3/examples/cornertracker/xf_corner_tracker_accel.cpp) | HEIGHT=2160, WIDTH=3840, FILTER_WIDTH=7, BLOCK_WIDTH=7 |
| `experiment/vision-nested-dataflow-20260911-v02/` → `vision_isp_bayer_4k_npc2` | [vision/L3/examples/isppipeline/xf_isp_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L3/examples/isppipeline/xf_isp_accel.cpp) | 未登记参数修改 |
| `experiment/vision-nested-dataflow-20260911-v02/` → `vision_isp_hdr_4k_npc1` | [vision/L3/examples/isppipeline_hdr/xf_isp_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L3/examples/isppipeline_hdr/xf_isp_accel.cpp) | 未登记参数修改 |
| `experiment/vision-nested-dataflow-20260911-v02/` → `vision_isp_rgbir_4k_npc1` | [vision/L3/examples/isppipeline_rgbir/xf_isp_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L3/examples/isppipeline_rgbir/xf_isp_accel.cpp) | 未登记参数修改 |
| `experiment/vision-nested-dataflow-20260911-v02/` → `vision_isp_global_tonemap_4k` | [vision/L3/examples/isppipeline_gtm/xf_isp_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L3/examples/isppipeline_gtm/xf_isp_accel.cpp) | 未登记参数修改 |
| `experiment/vision-nested-dataflow-20260911-v02/` → `vision_isp_all_in_one_1080p` | [vision/L3/examples/all_in_one/xf_isp_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L3/examples/all_in_one/xf_isp_accel.cpp) | 未登记参数修改 |
| `experiment/vision-nested-dataflow-20260911-v02/` → `vision_tvl1_optical_flow_512x512_npc2` | [vision/L3/examples/tvl1/xf_tvl1_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L3/examples/tvl1/xf_tvl1_accel.cpp) | 未登记参数修改 |
| `experiment/vision-nested-dataflow-20260911-v02/` → `vision_orb_matcher_k8192_pu64` | [vision/L2/examples/bfmatcher/xf_bfmatcher_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L2/examples/bfmatcher/xf_bfmatcher_accel.cpp) | PARALLEL_COMPUTEUNIT=64, MAX_KEYPOINTS=8192 |
| `experiment/vision-nested-dataflow-20260911-v02/` → `vision_orb_matcher_k8192_pu128` | [vision/L2/examples/bfmatcher/xf_bfmatcher_accel.cpp](https://github.com/Xilinx/Vitis_Libraries/blob/3ab1ecd20cf338b3f8f2824fdfeee115f3398889/vision/L2/examples/bfmatcher/xf_bfmatcher_accel.cpp) | PARALLEL_COMPUTEUNIT=128, MAX_KEYPOINTS=8192 |

Vision 批次中 `cases/<case>/` 存放配置副本，具体综合入口和参数以各批次 `jobs.json`、`prepare.py` 及运行 Tcl 为准。

## 本地派生实验及辅助目录

| 目录 | 来源与用途 |
|---|---|
| `experiment/vivado-trtrs-baseline-10ns-20260911-01/` | 本地 Vivado 脚本；RTL 来自 `experiment/trtrs_20260911_110300_v05/hls/sol/syn/verilog/`。算法最终来源为上表 Vitis Libraries 的 `solver/L2/tests/hw/trtrs/kernel_trtrs.cpp`。这是同一 TRTRS 的物理实验，不是独立第三方算法。 |
| `experiment/nondataflow-cleanup-20260911/` | 本地清理脚本与审计记录，不是算法 case。 |
| `experiment/.history/` | 本地历史批次元数据，不是新的上游源码来源。 |

已按用户要求删除的 APFP、Allo 实现及 GPT 不列为当前保留 case。后续增加 case 时，应同时补充仓库 URL、准确 commit、上游文件路径、实验目录及本地修改说明。
