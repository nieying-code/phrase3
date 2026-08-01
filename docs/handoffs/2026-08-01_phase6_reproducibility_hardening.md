# Phase 6 Reproducibility Hardening Handoff

## 任务目标

在任何新pilot或正式实验重跑前，一次性修复Windows换行导致的组件指纹
漂移，并系统排查同类复现风险。本PR只修改复现与执行基础设施，不运行
Phase 6实验，不修改数学模型、实验矩阵科学参数、算法或求解器设置。

## 分支和提交

- Branch: `agent/phase6-reproducibility-hardening`
- Base: merged PR #21, `f65ed995af846df1386049d6dc634ced99b89cc0`
- Initial implementation commit: `59e5994`
- Final PR head: see Draft PR (the handoff commit is necessarily its ancestor)
- Draft PR: pending

## 根因与隐藏风险审计

最初假设是Windows将受控文件从LF检出为CRLF。取证表明这只是问题的一部分：

- 已批准family组件指纹：`5803afd6...`；
- 当时Windows CRLF工作树计算值：`a1c2238...`；
- 从Git blob恢复为纯LF后计算值：`efcb7564...`。

因此历史门槛来自混合工作树字节，单纯添加`.gitattributes`不能恢复旧指纹，
也不能安全证明旧门槛可继续使用。进一步审计还发现：

1. Python只约束到3.12系列，未强制3.12.10；
2. E3 registry、projection和正式门槛没有实际环境指纹；
3. E3组件列表遗漏锁、状态、复现和入口依赖；
4. E3 projection未验证finalized manifest和结果文件哈希；
5. E3曾在manifest登记哈希后再次改写`result.json`；
6. 多个Phase 6写入器没有统一的Windows瞬时文件锁重试；
7. pilot/formal入口未强制拒绝tracked脏工作树；
8. CI使用不精确的Python `3.12`且没有Windows换行守卫；
9. 配置与组件的原始字节哈希可受换行转换影响；
10. 旧输出根目录混合多个指纹周期，增加误读旧registry的风险；
11. 自定义Phase 6输出根目录未被Git忽略，导致manifest总是笼统记录
    `working_tree_dirty=true`，重复制造审计歧义。

## 修改内容

### 换行与指纹

- `.gitattributes`固定Python、YAML、Git控制文件和依赖锁为LF；
- 受控文本哈希读取器遇到CRLF或孤立CR立即拒绝；
- E3和family组件列表均包含`.gitattributes`及其实际直接依赖；
- 自动测试通过AST检查组件列表覆盖所有直接本地导入；
- CI固定Python 3.12.10，并增加Windows复现守卫作业。

### 环境身份

- 强制CPython 3.12.10；
- 逐项核验`requirements-gurobi-lock.txt`；
- 强制Gurobi/gurobipy 13.0.2；
- 环境指纹包含Python、锁定包、操作系统、处理器、CPU和内存；
- E3 registry、result、manifest、projection、P1→P2门槛和formal gate均核验
  环境指纹。

### 源码与制品完整性

- pilot/formal在生成场景前拒绝任何tracked修改；
- 未跟踪文件只允许位于`outputs/`；
- `.gitignore`覆盖Phase 6周期输出、验证输出和临时输出目录，使受控输出不再
  把manifest标成笼统的脏工作树；
- E3改为`result → finalized manifest（result SHA-256）→ registry →
  projection`；
- projection和scale advancement重新核验registry/result/manifest的一致性；
- 被篡改、缺失或未最终化的制品标记为`artifact_invalid`并阻止授权；
- 全部Phase 6 JSON/CSV原子写入统一使用Windows `PermissionError`有限重试；
- JSON固定LF，CSV固定CRLF，避免平台默认值漂移。

## 指纹影响

科学矩阵内容未改变：

- scientific config: `f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3`
- E3 runner config: `3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd`
- family runner config: `983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c`

复现基础设施属于受保护执行依赖，因此组件与环境指纹按设计更新：

- old E3 component: `7713671...`
- new E3 component: `f99c95b2b6651e0d2d2bac6964c37fcd5bf22682e2e72bc6f10ab40351297ace`
- old family component: `5803afd6...`
- new family component: `02e2ce95219149b110d60fbc7935c6d385452b62de4da9c28406155a3baa6e9a`
- old package-only environment: `0306c49c...`
- new complete environment: `b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af`

以上新组件值需在最终提交和全新worktree复核；若最终源码仍有变化，以PR
机器检查输出为准。

## 旧结果影响

- 已完成的旧pilot、family pilot和E1正式结果仍是有效的历史数值/诊断证据；
- 它们不能进入新指纹门槛，也不能迁移或改写；
- 失败E2 run `formal_v21_e2_v2_2026072401`永久保留，不能复用run ID；
- 本PR不声称旧数值错误，失效的是其对新执行周期的机器授权资格；
- 后续必须从全新输出根目录、全新run ID依次重建门槛。

## 验证结果

未运行任何场景生成、pilot、formal seed或Gurobi实验。

- `python -m compileall -q src tests`: passed
- Phase 6专项回归：`50 passed`
- 复现加固专项：`9 passed`
- 本地完整回归：`143 passed in 29.00s`
- `git diff --check`: passed
- 首次全新worktree检查发现宽泛`*.json eol=lf`会把三个历史结果快照
  标记为tracked修改；该规则已移除，避免“加固本身制造脏工作树”。最终
  clean-worktree复核见PR验证记录。
- GitHub Actions Linux/Windows：pending

## 后续恢复方案

本PR复审并由用户手动合并后：

1. 从最新`main`建立专用实验分支，不再切换该运行worktree；
2. 使用全新输出根目录，例如`outputs/phase6_v21_lf_stable/`；
3. 确认tracked工作树干净、环境和四类指纹一致；
4. 从`0/12`重新运行V1 E3 pilot并单独复审；
5. 再按每种子`E1 → E2 → E4 → E5`重建family pilot并复审；
6. 依次运行V2、P1、P2 pilot，每批停止复审；
7. 完整计算门槛通过后，重新运行E1正式实验；
8. E1复审通过后，才重新启动E2正式实验。

任何源码、科学配置、runner配置、依赖或环境指纹变化都会自动阻断旧门槛。

## ChatGPT复审重点

1. `.gitattributes`范围是否覆盖所有受控执行文本；
2. LF拒绝策略是否会在场景生成前生效；
3. E3/family组件依赖闭包是否完整且不过度耦合；
4. Python补丁、锁定包、Gurobi和硬件环境是否全部进入门槛；
5. tracked/untracked源码门槛是否可能被绕过；
6. E3最终化顺序和manifest/result哈希是否闭环；
7. artifact-invalid是否确实阻止projection和scale advancement；
8. Windows原子替换重试是否有界且只捕获`PermissionError`；
9. 旧结果是否仅保留为历史证据、没有迁移授权；
10. 本PR是否严格未运行任何Phase 6实验。
