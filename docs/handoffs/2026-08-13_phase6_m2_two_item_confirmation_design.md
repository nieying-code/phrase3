# Phase 6 M2 双物资确认设计 Handoff

本变更只预注册双物资确认设计，不实现 runner，不生成场景，不调用 Gurobi，不运行确认、pilot、正式扩展或 M0 E3。复审修订已冻结独立 `M2C2` 参考预算/容量、$R_{min}^{opt}$ 端点跨物资指标、父级 PR #48 证据锁定及 C0 完整等价门槛。

- 父级证据：PR #48，阈值 `(0.2,0.3]`；候选 `beta=1.1/1.3,T03`。
- 设计：2物资、6期、50场景、5个全新种子、2个预算、C0/C1/T03，共30组。
- C0为完全无中断控制；C1为轻度控制；T03为阈值附近处理。
- 双物资使用冻结前两个原型，并预注册 `0.8/1.2` 供应脆弱性倍率。
- 成功必须同时满足完整性、CRN、C0零激活、T03激活与适度门槛，以及共享储备跨物资动态配置证据。
- `formal_extension_authorized=false`。

分支：`agent/phase6-m2-two-item-confirmation-design`；Draft PR：[#49](https://github.com/nieying-code/phrase3/pull/49)。初始设计提交为 `fea81fe01bea593f9a9710b1312f93abbf7ae7a9`；复审修复后的最终科学设计基线为 `2d623f111afdce8b782d6b4b008bb4580eb7c290`，对应 CI [run 31680792963](https://github.com/nieying-code/phrase3/actions/runs/31680792963) 的 Linux 与 Windows 作业均成功。后续纯追溯提交的最终 SHA 仅记录于 PR 正文，不再写回本文件，以避免无限自引用；该类提交不改变设计、指纹或执行边界。

本地验证：专项 `8 passed`；完整回归 `317 passed`；Phase 5 `6 passed`；`compileall` 与 `git diff --check` 通过。
