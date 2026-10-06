# 阶段内存调度代码的发布范围

本目录保存 2026-10-06 已使用的七个源码/测试/说明文件，不包含当时实验的 `config.json`、PID 登记、进程身份、内存采样、lease、日志或运行结果。原七个文件按字节保留；[README.md](README.md) 是当时两组实验的说明，包含历史检查频率，当前检查频率以外部监控配置为准。

`policy.py`、`gate.py`、`entry.tcl` 和 `vivado_entry.py` 提供阶段预算、进程身份、nonce/过期许可和保持原 Tcl source/argv/作用域的适配。预算为启动/seed 32 GiB、base 40 GiB、generic 54 GiB、reopen 32 GiB，额外余量 4 GiB，来自当前 GETRF 负载。它们不能作为其他设计的固定内存保证。

准入使用 `MemAvailable`，只增加各作业尚未驻留的预约增长量，再加余量，避免把实际 RSS 重复扣减。等待或 SIGSTOP 不释放内存。只允许对已登记且 PID、启动标识、命令与 cwd 全部匹配的实验进程暂停/恢复，不触碰无关进程。

`controller.py` 是 **affinity01/affinity02 6.5 ns 两组的接管协调器**，含明确的作业名与实验适配规则，并非任意 case 的通用队列。它要求新建独立目录下的外部 `config.json`，以及被冻结原控制器的正确指纹，执行双重未启动检查和唯一锁。不要直接把本发布目录指向其他活动实验运行它。

复用配置需明确提供 `pair_root`、`first_root`、`second_root`、`source`、`post_opt`、`post_opt_sha256`、`old_scheduler` 的身份与 `gate_directory` 等字段，按照协调器全部校验准备有效尝试。适配其他 case 应另建隔离副本并验证接管、重复启动防护和恢复边界，不能修改运行中已经加载的 Tcl。

`python3 test_scheduler.py` 使用临时目录与模拟 /proc，并验证真实 gate 子进程阻塞/放行；不启动 Vivado、不对实验进程发送信号。完整硬件实验、历史运行配置与进程证据不属于源码回归测试。
