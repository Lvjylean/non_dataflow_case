# 本源码包变更记录

## 2026-10-06

- 汇总当前 connection_partition 与 backend_broadcast_scope_repair100，补充单周期累计跨 die 惩罚、macro_timing_v2、广播识别、FF/输入联合优化、物理合法化、编译提速及身份恢复说明。
- 保存 phase_memory_scheduler 的七个原始源码/测试/说明文件，另附适用范围，明确它是 GETRF affinity 两组协调器。
- 变更范围：上述目录、balanced_implementation/adapter.tcl、RELEASE_10_6.md、RELEASE_10_6_VALIDATION.md、release_10_6_manifest.json 及本记录/HANDODD.md。
- 原因：按用户要求在独立 Git 分支保存当前源码，并将主要实现与可选能力形成可审阅说明。
- 行为与时序影响：这是当前代码的发布快照，没有修改活动实验、算法、周期或流水级；未合并常规三次 placement。
- 验证：partition 253 项发现（250 PASS/3 SKIP）、后端 44 组命令与20项恢复测试、调度12项测试；Linux 后端/调度同样通过；153文件匹配已有原生证据。
- 限制：详见 RELEASE_10_6_VALIDATION.md；当前未启用跨会话 discovery 缓存，阶段内缓存与该能力分别记录。
