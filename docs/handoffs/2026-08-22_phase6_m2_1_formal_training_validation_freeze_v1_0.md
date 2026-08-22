# Phase 6 M2.1正式训练—验证冻结与执行器交接

本PR基于PR #67合并提交`5d40f93f1cf323501941343b34592053a26cccef`，建立独立的M2.1正式训练—验证命名空间。它不运行实验，只冻结并机器授权10组三元组中的训练与验证阶段。

## 阶段边界

本批允许的未来执行为10个正式训练种子与10个正式验证种子的一一配对。每组生成100个训练场景，识别容差最优储备区间，重新优化最小、中点和最大三个候选，并在同一组2,000个验证场景上完成3个候选的精确补救评价。冻结总量为10条primary run、30个验证候选和60,000次验证补救评价。

10个正式测试种子只保留身份，当前runner禁止生成或读取测试场景。即使训练—验证投影完整通过，程序也只能输出`permit_separate_selected_plan_freeze_review_PR_only`；`selected_plan_freeze_authorized=false`、`formal_test_authorized=false`和`formal_extension_authorized=false`保持不变。正式测试必须等待10组选择结果复审、方案身份冻结及独立授权PR。

## Pilot证据绑定

预检同时核验PR #67紧凑审计、D盘pilot registry和projection的最终字节哈希。审批文件中的三项哈希必须与审计和本机只读制品一致；pilot必须为3/3最优、18,000次验证评价与12,000次测试探针评价闭合、异常集合为空且`pilot_compute_gate_passed=true`。M2旧授权和pilot授权均不能替代本正式阶段授权。

## 执行安全

- 使用独立输出根`outputs/phase6_m2_1_formal_training_validation_v1_0`；
- primary必须从空目录一次严格串行运行完整10组，不能用`case_id`挑选；
- 任一失败、超时、中断或最终化错误立即停止后续run；
- 失败primary永久进入投影分母；诊断只能使用新run ID和同case的`parent_run_id`；
- 每条run按result、manifest、registry、projection顺序最终化；
- projection重新核验制品路径、哈希、方案身份、候选选择、共同随机数和60,000次评价闭合；
- Gurobi/gurobipy 13.0.2、`gurobi_direct`、`Threads=1`，每次求解120秒、每组三元组训练期限1,800秒、每候选验证期限7,200秒；
- 只有显式CLI参数`--authorize-formal-training-validation-execution`才能开始。

## 本PR停止边界

本PR场景生成、Gurobi调用、正式run、正式测试、算法性能和M0 E3运行数全部为0。完成测试并创建Draft PR后停止，不自动运行10组三元组，也不访问正式测试集。

最终提交、tree、测试数量和CI记录于PR正文。
