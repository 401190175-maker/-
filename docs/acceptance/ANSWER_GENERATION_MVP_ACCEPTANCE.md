# 答案生成与只读总编排 MVP 验收记录

本文记录 `changes/产品实现层/答案生成与只读总编排MVP` 的四层专项回归与完整离线回归的**新鲜验证结果**。它只反映当前已实际运行并观察到的命令与数字，不把历史测试数字、skipped 或计划当作完成证据；live Neo4j、live DashScope 与真实文本 provider 均未验证。

- 验收日期：2026-08-14
- 工作目录：`C:\Users\40119\Desktop\图块图谱构建`
- 范围：06 答案生成、07 只读总编排、无副作用 factory、产品只读 CLI 与 fake 端到端
- 运行方式：所有命令均在仓库根目录，先 `$env:PYTHONPATH='src'` 再执行

## 1. 06 专项回归（Task 71）

命令：

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_models tests.test_assistant_claim_builder tests.test_assistant_citation_builder tests.test_assistant_answer_serialization tests.test_assistant_answer_templates tests.test_assistant_answer_text tests.test_assistant_answer_generation tests.test_assistant_answer_security tests.test_assistant_answer_boundaries -v
```

结果：`Ran 191 tests`，`OK`（0 失败、0 错误、0 跳过）。

已覆盖的 design 负向门禁（均有对应失败断言测试）：

- 非诊断 claim 无 evidence/citation 时 fail closed（`test_assistant_citation_builder.ClaimCitationIntegrityTests`、`test_assistant_answer_generation.AnswerPackageValidatorTests`）。
- candidate/interpretation/conflict 不被提升为 formal/source fact（`test_assistant_claim_builder`、`test_assistant_answer_generation`、`test_assistant_answer_templates`）。
- 受约束文本新增/遗漏/改绑 claim/citation、删除限定语、引入新数字/业务 ID 均被拒绝（`test_assistant_answer_text`）。
- 文本生成超时/异常/校验失败回退中文模板，不泄露 provider 原文（`test_assistant_answer_text.TextFallbackTests`）。
- canonical JSON 字节一致、UTF-8 中文、拒绝 NaN/Infinity/不可序列化对象（`test_assistant_answer_serialization`）。
- 敏感字段（image_path、URI、Cypher、凭据、traceback）不进入 package/JSON（`test_assistant_answer_security`）。
- 06 模块不导入 facade/repository/driver/provider/写回（`test_assistant_answer_boundaries`）。

## 2. 07 专项回归（Task 72）

命令：

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service tests.test_drawing_assistant_boundaries tests.test_drawing_assistant_factory -v
```

结果：`Ran 32 tests`，`OK`（0 失败、0 错误、0 跳过）。

已覆盖：

- 单意图 01→02→03 顺序、多意图逐子请求、clarification/unsupported 早停（`test_drawing_assistant_service`）。
- 只读入口门禁：`allow_write_back=true` 在任何下游调用前被拒绝，问题文本中的写回要求不构成授权（`ReadOnlyEntryGateTests`）。
- 按页识别分组、每页一次 facade 且固定 `write_back=false`、缺页目标转结构化失败、页级失败不丢其他页（`PageRecognitionExecutionTests`、`RecognitionTargetGroupingTests`）。
- 05 只读调用 `write_back_policy=None`；partial/recognition_failed 状态映射（`ReadOnlyFusionCallTests`、`AssistantErrorMappingTests`）。
- 资源上限 subrequest/page-group 稳定拒绝（`AssistantResourceLimitTests`）。
- 07 模块不导入 driver/repository/provider/QA/写回（`test_drawing_assistant_boundaries`）。
- factory 无副作用、默认无真实文本生成器、不接收裸 repository/session（`test_drawing_assistant_factory`）。

## 3. 产品 CLI smoke 验收（Task 73）

命令（含新增子进程 smoke）：

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_cli tests.test_drawing_assistant_cli_boundaries tests.test_drawing_assistant_e2e -v
```

结果：`Ran 31 tests`，`OK`（0 失败、0 错误、0 跳过）。

子进程 smoke 证据（`test_drawing_assistant_e2e.CliSubprocessSmokeTests`，无 Neo4j/网络）：

- 脚本 import 无副作用（子进程 `import drawing_assistant; print('import-ok')` 返回 0）。
- 缺 `--question` 子进程退出码为 2，stdout 为空。
- 无 `NEO4J_*` 环境变量时 `--question q` 子进程退出码 2，stderr 为脱敏 `configuration_failed` envelope，不含 password/secret。

fake 端到端覆盖（`DrawingAssistantE2ETests`）：

- 真实 01—06 + fake facade 覆盖 clarification、unsupported、partial、recognition 问题（退出 0，stdout 单一 `{"ok": true, ...}` envelope）。
- fake service 覆盖 answered/partial/clarification_required/unsupported/recognition_failed 五类业务状态，均退出 0。

CLI 合同覆盖（`test_drawing_assistant_cli`）：JSON/文本输出、相同显式 request-id 字节一致、退出码 0/1/2、错误脱敏、无 write-back 参数。静态安全（`test_drawing_assistant_cli_boundaries`）：CLI 不导入 repository/QueryService/provider/写回/离线规则，无硬编码凭据。

以上均为 fake/离线 smoke，**不证明 live Neo4j、live DashScope 或真实文本 provider**。

## 4. 完整离线回归（Task 74）

命令：

```powershell
$env:PYTHONPATH='src'; python -m unittest discover tests -v
```

结果：`Ran 2462 tests`，`OK (skipped=4)`。

4 项跳过均为 `tests/integration/` 下的 live Neo4j 集成测试，因缺少 `NEO4J_TEST_URI`/`NEO4J_TEST_USER`/`NEO4J_TEST_PASSWORD` 环境变量而跳过。所有既有离线回归（导入、关系增强、QA、HTTP、MCP、语义、识别、01—05）均保持通过。

## 5. live 状态记录（分层分离）

| 层级 | 状态 | 说明 |
|---|---|---|
| 离线单元/合同/静态边界 | 已验证 | 上述 2462 项离线回归全部通过 |
| fake runtime 端到端 | 已验证 | Task 73 fake facade/service 覆盖五类状态 |
| CLI 子进程 smoke | 已验证 | 参数、退出码、输出、错误脱敏（fake 环境） |
| live Neo4j | 未验证 | 未配置 disposable 测试库；skipped 不等于 live 通过 |
| live DashScope / 真实文本 provider | 未验证 | 默认不装配真实 provider，未执行真实模型调用 |

## 6. 已知边界（非本需求范围，如实记录）

真实管线（fake facade + 真实 01—06）在离线 smoke 中，因既有 05 融合默认空规范化规则注册表且 freshness 未透传至 `FusionEvidence.is_current_for_request`，检索证据会被判为 stale，导致 `page_summary` 一类问题在当前快照下产出 `partial` 而非 `answered`。这是 05 自身接缝，不属于本 change 的 06/07/CLI 范围；本记录不把 `partial` 表述为 `answered` 已验证。live 环境下修正 05 接缝后方可重新验收，且必须单独记录。
