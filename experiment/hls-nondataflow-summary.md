# Non-dataflow HLS 整理后清单

保留 27 个综合成功且未发现已知有效性问题的配置，删除 9 个失败、超时、无效或超器件容量配置。4 个通过的 C 仿真已合并至对应 case 的 validation/。小规模成功配置保留作对照，其中 8 个配置满足此前计算资源 60% 门槛。

目录命名：case_YYYYMMDD_HHMMSS_vNN；时间为原始 HLS 启动时间（香港时区），版本按各 case 的启动时间递增。具体参数见 case.json；版本号不表示规模大小。

服务器根目录：/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment。每个 case 的 RTL 为 hls/sol/syn/verilog，复跑使用 launch.sh，并设置新的绝对 HLS_OUTPUT_DIR。源代码和 RTL 内容未修改。历史日志保留原始路径；旧批次的简短元数据在 .history/nondataflow-batches。

HLS 2023.2，U250，HLS 目标 5 ns。除 trtrs 大规模配置另有 Vivado 10 ns 基线外，这些为 HLS 估算，不代表布线或数值验证通过。

| 目录 | 原配置 | 资源分类 | 数值仿真 |
|---|---|---|---|
| geqrf_20260911_103020_v01 | geqrf_baseline | BELOW_60 | 未验证 |
| geqrf_20260911_103129_v02 | geqrf_n256_u32 | BELOW_60 | 未验证 |
| geqrf_20260911_103401_v03 | geqrf_n256_u128 | PASS_COMPUTE_60 | 未验证 |
| geqrf_20260911_105014_v04 | geqrf_n512_u256 | PASS_COMPUTE_60 | 未验证 |
| geqrf_20260911_105252_v05 | geqrf_n768_u384 | PASS_COMPUTE_60 | PASS |
| gesvdj_20260911_103045_v01 | gesvdj_baseline | BELOW_60 | 未验证 |
| gesvdj_20260911_103156_v02 | gesvdj_n64_u8 | BELOW_60 | 未验证 |
| gesvdj_20260911_103438_v03 | gesvdj_n128_u16 | BELOW_60 | 未验证 |
| getrf_20260911_103020_v01 | getrf_baseline | BELOW_60 | 未验证 |
| getrf_20260911_103129_v02 | getrf_n256_u32 | BELOW_60 | 未验证 |
| getrf_20260911_103401_v03 | getrf_n256_u128 | BELOW_60 | 未验证 |
| getrf_20260911_103710_v04 | getrf_n1024_u512 | PASS_COMPUTE_60 | PASS |
| getrf_20260911_105014_v05 | getrf_n512_u256 | PASS_COMPUTE_60 | 未验证 |
| getrf_nopivot_20260911_103020_v01 | getrf_nopivot_baseline | BELOW_60 | 未验证 |
| getrf_nopivot_20260911_103129_v02 | getrf_nopivot_n256_u32 | BELOW_60 | 未验证 |
| getrf_nopivot_20260911_103401_v03 | getrf_nopivot_n256_u128 | BELOW_60 | 未验证 |
| getrf_nopivot_20260911_104359_v04 | getrf_nopivot_n1024_u512 | PASS_COMPUTE_60 | PASS |
| getrf_nopivot_20260911_105014_v05 | getrf_nopivot_n512_u256 | PASS_COMPUTE_60 | 未验证 |
| gtsv_20260911_103106_v01 | gtsv_baseline | BELOW_60 | 未验证 |
| gtsv_20260911_103218_v02 | gtsv_n256_u32 | BELOW_60 | 未验证 |
| rsa_20260911_103107_v01 | rsa_w2048 | BELOW_60 | 未验证 |
| rsa_20260911_103221_v02 | rsa_w4096 | BELOW_60 | 未验证 |
| trtrs_20260911_103043_v01 | trtrs_baseline | BELOW_60 | 未验证 |
| trtrs_20260911_103154_v02 | trtrs_n256_u32 | BELOW_60 | 未验证 |
| trtrs_20260911_103437_v03 | trtrs_n256_u128 | BELOW_60 | 未验证 |
| trtrs_20260911_105125_v04 | trtrs_n512_u256 | STORAGE_ONLY_60 | 未验证 |
| trtrs_20260911_110300_v05 | trtrs_n1024_u512 | PASS_COMPUTE_60 | PASS |

TRTRS 1024/512 的独立 Vivado 目录保持 vivado-trtrs-baseline-10ns-20260911-01，routed DCP 不移动，WNS +0.008 ns、WHS +0.030 ns，使用三个 SLR。
