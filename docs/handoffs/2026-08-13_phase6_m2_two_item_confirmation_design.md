# Phase 6 M2 双物资确认设计 Handoff

本变更只预注册双物资确认设计，不实现 runner，不生成场景，不调用 Gurobi，不运行确认、pilot、正式扩展或 M0 E3。

- 父级证据：PR #48，阈值 `(0.2,0.3]`；候选 `beta=1.1/1.3,T03`。
- 设计：2物资、6期、50场景、5个全新种子、2个预算、C0/C1/T03，共30组。
- C0为完全无中断控制；C1为轻度控制；T03为阈值附近处理。
- 双物资使用冻结前两个原型，并预注册 `0.8/1.2` 供应脆弱性倍率。
- 成功必须同时满足完整性、CRN、C0零激活、T03激活与适度门槛，以及共享储备跨物资动态配置证据。
- `formal_extension_authorized=false`。

分支：`agent/phase6-m2-two-item-confirmation-design`。Draft PR、最终提交和 CI 待发布后补充。

本地验证：专项 `4 passed`；完整回归 `313 passed`；Phase 5 `6 passed`；`compileall` 与 `git diff --check` 通过。
