# Phase 6 M2 双物资确认设计 Handoff

本变更只预注册双物资确认设计，不实现 runner，不生成场景，不调用 Gurobi，不运行确认、pilot、正式扩展或 M0 E3。

- 父级证据：PR #48，阈值 `(0.2,0.3]`；候选 `beta=1.1/1.3,T03`。
- 设计：2物资、6期、50场景、5个全新种子、2个预算、C0/C1/T03，共30组。
- C0为完全无中断控制；C1为轻度控制；T03为阈值附近处理。
- 双物资使用冻结前两个原型，并预注册 `0.8/1.2` 供应脆弱性倍率。
- 成功必须同时满足完整性、CRN、C0零激活、T03激活与适度门槛，以及共享储备跨物资动态配置证据。
- `formal_extension_authorized=false`。

分支：`agent/phase6-m2-two-item-confirmation-design`；Draft PR：[#49](https://github.com/nieying-code/phrase3/pull/49)。科学设计提交：`fea81fe01bea593f9a9710b1312f93abbf7ae7a9`；对应 CI [run 31679477052](https://github.com/nieying-code/phrase3/actions/runs/31679477052) 的 Linux 与 Windows 作业均成功。后续如仅追加本追溯记录，其提交不改变设计、指纹或执行边界。

本地验证：专项 `4 passed`；完整回归 `313 passed`；Phase 5 `6 passed`；`compileall` 与 `git diff --check` 通过。
