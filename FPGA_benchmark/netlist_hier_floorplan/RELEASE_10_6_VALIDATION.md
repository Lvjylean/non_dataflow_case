# 10 月 6 日发布验收

这是源码发布回归和已存在原生证明的身份核对，不是一次新的完整网表编译。

|检查|结果|范围或限制|
|---|---|---|
|Partition/floorplan 本地回归|253 项发现，250 项通过，3 项跳过|两个 Gurobi 相关测试因本地无 Gurobi 跳过；一个真实 U250 资源表测试因未携带实验资源表跳过|
|后端本地回归|44 组命令通过，20 项恢复集成测试通过|Python、Tcl 模拟、语法、单次 route、只读重开、输入代价与 scope repair 等回归|
|调度器本地回归|12 项通过|预算、等待/暂停内存、nonce/过期许可、进程身份和 Tcl 参数/作用域|
|Linux 发布工作树回归|同一后端与调度器回归通过|服务器默认 Python 缺少 NumPy，未重复运行 partition 全套；未新增依赖|
|后端源码身份|153 文件逐项一致|发布源码、当前实验冻结 source_v1 与原生证据的完整 source_hashes 完全一致|
|原生证明|integration、joint input、pin timing 等价性、physical ECO、broadcast locality、scope repair 均通过|复用已存在并绑定本次源码的服务器证明，不声称本次新跑 native 或新得到 WNS|
|跨会话静态 discovery 缓存|未启用|native_static_discovery_cache_pass=false；代码存在不等于生产准入通过|
|暂存格式检查|保留一处历史 EOF 空行|`code/base/fanout96/quick.tcl` 第22行；保留原字节以匹配153文件的原生证明，不改变 Tcl 行为|

原 native 证据 SHA256：`906fcfa9d96db08aa09e776d5e019d43afa3f03f5c5cf4caea667da28ac32a41`。

`release_10_6_manifest.json` 列出本次 source/config/test/doc 的逐文件 SHA256，清单自身不加入自身哈希。后端原生证明清单与发布清单分开；后者还包括 partition、调度和新说明文件，不作为 run_case 的原生准入 JSON。

使用 NumPy 的源码测试在本地运行时仅使用合成小图与模拟，不提取或载入设计 DCP。Gurobi、完整设计数据与原生实现的验证范围不能由这些模拟测试替代。

恢复、局部复制或布线后的 WNS 可为负；功能与物理检查通过不能据此推断时序收敛。当前 6.2 ns affinity02 尚在运行，本发布不承诺该实验最终结果，也不改变它的输入或已加载脚本。
