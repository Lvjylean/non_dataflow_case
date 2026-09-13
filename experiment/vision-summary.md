# Vision 顶层 non-dataflow 编译结果

完成 22 个配置试编译，21 个生成 Verilog，1 个因原始源码错误失败。7 个配置满足本次筛选条件，其中 4 个内部存在 DATAFLOW，3 个为无内部 DATAFLOW 的对照。未收到“第二组/第三组”的明确清单，本轮按本地 Vitis Libraries 函数作用域检查筛选 vision 示例。

Vitis HLS 2023.2，xcu250-figd2104-2L-e，HLS 时钟 5 ns。所有成功顶层的 XML PipelineType 为 no；内部 DATAFLOW 依据子模块 XML 确认。没有通过新包裹函数把 DATAFLOW 顶层伪装成 non-dataflow，也没有手工复制多个核凑资源。源库不变，只修改独立副本的配置参数。

LUT 门槛：108000–864000（单 SLR 432000 LUT 的 25%–200%）。规模标签=max(LUT/432000, FF/864000, DSP/3072, BRAM18K/1344, URAM/320)，互不相加。其他资源同时检查不超过全器件容量。这是 HLS 估算；不是实际 SLR 放置结果。当前七个达标配置的主导资源均为 LUT。

## 达标配置

| Case | LUT | FF | DSP | BRAM18K | URAM | 规模：最高资源/单SLR | 内部 DATAFLOW |
|---|---:|---:|---:|---:|---:|---|---|
| 综合 ISP：1080p，4 像素/周期 | 128,123 | 96,724 | 614 | 100 | 2 | LUT 29.7% | 有 |
| TV-L1 光流：1024×1024，内核 2 路 | 257,500 | 136,532 | 345 | 258 | 6 | LUT 59.6% | 有 |
| TV-L1 光流：512×512，内核 2 路 | 259,512 | 135,879 | 302 | 203 | 6 | LUT 60.1% | 有 |
| TV-L1 光流：512×512，最大光流范围 10 | 312,300 | 146,022 | 302 | 227 | 6 | LUT 72.3% | 有 |
| ORB 暴力匹配：8192 关键点，64 路 | 214,043 | 32,603 | 3 | 148 | 0 | LUT 49.5% | 无 |
| ORB 暴力匹配：8192 关键点，128 路 | 421,004 | 57,306 | 3 | 148 | 0 | LUT 97.5% | 无 |
| ORB 暴力匹配：8192 关键点，256 路 | 834,528 | 106,665 | 3 | 148 | 0 | LUT 193.2% | 无 |

## 算法与参数变化

- 综合 ISP：坏点/黑电平校正、去伽马、自动曝光、增益、去马赛克、白平衡、颜色校正、局部色调映射等原有阶段；原始1080p、1像素/周期，改为4像素/周期，输出端口128→256 bit，适配4路RGB16数据。功能开关保持原值。
- TV-L1：稠密光流、多尺度和迭代求解，外层控制多轮迭代，内层阶段使用DATAFLOW。原始512×512、内核2路、最大光流范围6；分别保留原始版、分辨率上限改1024×1024版，以及最大光流范围改10版。后三者分别是独立变体，未同时改多项。
- ORB匹配：256-bit描述子汉明距离、最近邻选择与比值筛选。原始MAX_KEYPOINTS=10000、PU=10；改为8192关键点，PU=64/128/256。没有内部DATAFLOW。

## 目录与复跑

服务器根目录：`/Projects/jinyang/workspace/non_dataflow_crossSLR/case/experiment/`。
达标case在根目录下独立存放，名称包含算法、关键参数、最高资源占比、日期和版本。各目录的 `case.json` 保存完整配置、资源、顶层/内部DATAFLOW证据及原始路径。

RTL：`hls/sol/syn/verilog/`（需保留全部Verilog/IP Tcl及配套文件）；源文件：`sources/`；头文件：`library/`。`launch.sh` + `rerun.tcl` 要求设置新的绝对 `HLS_OUTPUT_DIR`，避免覆盖已有成功产物。

- `vision_orb_matcher_k8192_pu256__LUT_193p2pctSLR__20260911_v01`
- `vision_tvl1_optical_flow_512x512_npc2__LUT_60p1pctSLR__20260911_v02`
- `vision_orb_matcher_k8192_pu64__LUT_49p5pctSLR__20260911_v02`
- `vision_orb_matcher_k8192_pu128__LUT_97p5pctSLR__20260911_v02`
- `vision_isp_all_in_one_1080p_npc4__LUT_29p7pctSLR__20260911_v03`
- `vision_tvl1_optical_flow_512x512_flow10__LUT_72p3pctSLR__20260911_v04`
- `vision_tvl1_optical_flow_1024x1024_npc2__LUT_59p6pctSLR__20260911_v04`

## 不达标及失败

- vision_orb_matcher_k8192_pu512: LUT_ABOVE_MAX；LUT=1661564, 最高资源=LUT 384.6%。
- vision_meanshift_1080p_objects10: LUT_BELOW_MIN；LUT=14593, 最高资源=BRAM_18K 5.1%。
- vision_meanshift_1080p_objects64: LUT_BELOW_MIN；LUT=14599, 最高资源=BRAM_18K 8.7%。
- vision_rotate_4k_tile256_npc2: LUT_BELOW_MIN；LUT=12441, 最高资源=BRAM_18K 9.8%。
- vision_flip_8k_rgb_npc8: LUT_BELOW_MIN；LUT=23667, 最高资源=BRAM_18K 6.8%。
- vision_harris_corners_4k_filter7: LUT_BELOW_MIN；LUT=37421, 最高资源=BRAM_18K 9.5%。
- vision_isp_bayer_4k_npc2: LUT_BELOW_MIN；LUT=39797, 最高资源=LUT 9.2%。
- vision_isp_hdr_4k_npc1: LUT_BELOW_MIN；LUT=46399, 最高资源=BRAM_18K 14.6%。
- vision_isp_rgbir_4k_npc1: FAILED；RGBIR原始示例的bformat未定义、ISPpipeline调用签名不一致。
- vision_isp_global_tonemap_4k: LUT_BELOW_MIN；LUT=61604, 最高资源=LUT 14.3%。
- vision_isp_all_in_one_1080p: LUT_BELOW_MIN；LUT=67739, 最高资源=LUT 15.7%。
- vision_isp_bayer_4k_npc4: LUT_BELOW_MIN；LUT=58321, 最高资源=LUT 13.5%。
- vision_isp_hdr_4k_npc4: LUT_BELOW_MIN；LUT=106480, 最高资源=BRAM_18K 50.4%。
- vision_isp_all_in_one_1080p_npc2: LUT_BELOW_MIN；LUT=88350, 最高资源=LUT 20.5%。
- vision_isp_hdr_8k_npc4: LUT_BELOW_MIN；LUT=106513, 最高资源=BRAM_18K 51.6%。

## 验证和范围

所有21个成功RTL目录验证顶层模块存在并记录文件哈希；全部批次249等输入文件按各自清单验证。7个达标目录迁移前后逐文件校验，仅工程路径元数据更新，RTL/IP负载不变。HLS资源XML与单SLR/全器件容量复核；未进行数值C仿真、RTL协同仿真、Vivado实现或板级验证。部分循环可能未达到目标II，综合成功不代表吞吐目标达成。失败与小规模诊断实验保留在批次目录，不混入达标清单。
