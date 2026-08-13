# Phase 6 M2C2 双物资确认 Runner Handoff

基线：PR #49合并提交 `28079b9d63ffeabf5bff909684b8c982f46f1b2b`。分支：`agent/phase6-m2c2-confirmation-runner`。

本修订实现独立30组安全runner，冻结状态与显式CLI授权缺一不可；M0、M1和单物资M2的授权、registry或projection均不能授权本轨道。Primary必须完整串行运行，失败即停止；run ID和终态不可覆盖；状态摘要有界，result/checkpoint不由状态工具加载。

科学执行显式使用 `M2C2` 双物资参考预算 `2337.610924158743`、两个预算及逐期容量，禁止继承V1。跨物资指标来自完整扩展式 `R_min_opt` 端点的50场景精确补救；C0实施完整双向无中断等价验收。Projection独立复算CRN、激活、适度储备、跨物资动态分配和结论边界。

本修订执行计数均为0：确认实验、诊断、pilot、正式扩展、M0 E3、场景生成和Gurobi科学调用均未发生。Draft PR、最终提交、测试和CI在发布后记录于PR正文，避免追溯文件自引用。

本地验证：M2C2专项在加入最终跨进程锁测试前为 `26 passed`；普通完整回归 `329 passed`；Phase 5端到端 `6 passed`。最终专项数量与Linux/Windows CI由PR正文记录。
