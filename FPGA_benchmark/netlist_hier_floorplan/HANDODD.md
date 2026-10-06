# 10 月 6 日源码发布交接

发布范围、入口和可选能力见 RELEASE_10_6.md，验收范围见 RELEASE_10_6_VALIDATION.md，文件身份见 release_10_6_manifest.json。

物理后端的规范入口是 backend_broadcast_scope_repair100/run_case.py；joint_eco 等内部历史适配源码保留在完整依赖快照中，不代替该入口。原生证明必须匹配全部153文件及请求启用的能力；不能把模拟测试结果当作 native PASS。

Partition C+L 与后续物理成本分开；累计跨 SLR 惩罚启用 macro_timing_v2 并要求单 SLR core。当前常规物理流程仍为三次 placement、一次完整 routing、独立重开，条件修复/回退另计。

下一步只按用户明确实验要求运行新目录；发布操作不重跑、不热更新已有实验。phase_memory_scheduler 的协调器仅适用于已说明的两组 GETRF 接管场景，跨会话 discovery 缓存尚未生产准入。历史脚本与结果应保留，不能以本快照覆盖已冻结的运行源码。
