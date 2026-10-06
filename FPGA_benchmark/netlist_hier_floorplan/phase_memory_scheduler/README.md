# 当前两组实验的阶段内存调度

用户在 2026-10-06 授权按可用内存并行调度、在资源不足时暂停高内存阶段。本调度适配仅属于 affinity01/affinity02 两组 6.5 ns 实验；原153文件物理源码及公共流程不修改。

服务器使用同实验目录下的 phase_scheduler_v1。新调度器登记并接管已有 affinity01 实验控制器，冻结旧的对照组调度器以防第二组重复启动；已有 Vivado 不重启、不热更新 Tcl。affinity02 从干净 post-opt 运行相同物理流程；Vivado 启动器增加的 Tcl execution trace 仅在 source 阶段入口等待 Python 内存许可，原 source 路径、argv、命名空间及物理过程保持不变。

|阶段|预算|
|---|---:|
|启动、首次布局 seed|32 GiB|
|基础 fanout、第二次布局 base|40 GiB|
|完整采集、联合候选、ECO、第三次布局及 routing|54 GiB|
|独立重开|32 GiB|
|额外整体余量|4 GiB|

预算根据原运行记录设置：Vivado 报告 seed/base/generic 峰值分别约22,796/26,293/54,639 MB，历史 process RSS 与原54 GiB预约单独保留；工具heap峰值与process RSS并非同一口径。已加载的 affinity01 恢复会话在进入独立重开前仍保守按54 GiB预约。

准入要求为：申请阶段尚未驻留的预算＋其他运行作业尚未驻留的预算＋整体余量。MemAvailable已扣除实际RSS，避免重复扣减。Tcl阶段等待保留全部已有对象；暂停不能视为释放内存，也不通过增加swap获得并行准入。

内存不足时优先在阶段入口等待，许可使用匹配请求nonce且未过期的lease。极低内存可暂停登记并核验PID启动标识、命令及cwd的实验Vivado，回升后恢复。不能暂停无关进程，不能恢复已冻结的旧调度器；新调度器持有唯一flock及双重未启动检查，防止第二组的部分启动造成重复运行。

12项本地和Linux测试通过，包括保留未来内存增长、两个高内存阶段不能同时准入、暂停RSS不作为释放、过期或错误lease不放行、实际等待进程阻塞后放行、Tcl source/argv/作用域保留、PID复用拒绝及部分启动竞态拒绝。物理源码逐项与已验证source匹配。

记录位于服务器的config.json、validation.json、handoff.json、ownership.json、events.jsonl、gate_affinity02及series_state.json。最终报告须分列阶段等待、紧急暂停和两组makespan；原编译阶段墙钟包含等待，不能将其全部算作工具计算时间。40分钟自动检查频率不变。
