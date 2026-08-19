# 答案生成与只读总编排 MVP Implementation Plan

> **实施状态：** 74 个 Task 全部完成。Task 1-65 各通过 TDD red/green；Task 66（QA/HTTP/MCP 兼容回归）、67（Module.md）、68（architecture.md）、69（README）、70（本 change 状态同步）、71-74（四层专项回归与完整离线回归验收）均已同步。完整离线回归 `python -m unittest discover tests -v` 为 2462 项运行、0 失败、4 项因缺少 live Neo4j 测试环境变量而跳过。live Neo4j、live DashScope、真实文本 provider 均未验证；skipped 不等于 live 通过。验收记录见 `docs/acceptance/ANSWER_GENERATION_MVP_ACCEPTANCE.md`。

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development`（推荐）或 `superpowers:executing-plans` 按任务逐项实施；一次只执行一个 Task，每个 Task 完成后独立评审和验证。

**Goal:** 在复用 01—05、`DrawingGraphToolFacade` 和现有 QA 兼容链路的前提下，实现确定性 claim/citation/JSON、默认中文模板、可选受约束文本生成、`DrawingAssistantService` 只读总编排和产品级只读 CLI。

**Architecture:** 新增 06 `AnswerGenerationService` 与 07 `DrawingAssistantService`。06 以确定性代码生成权威 `machine_answer`、claim、citation 和状态，模板始终可用，文本模型只作为受约束表现层；07 只编排 01—06，通过 facade 执行按页 dry-run 识别，不直接访问 driver、repository 或 Cypher。

**Tech Stack:** Python 3.11+、dataclasses/Enum、标准库 `unittest`、现有 assistant/recognition/facade/QA 模块、Neo4j 5.x（仅 live 集成层）、可选供应商无关文本生成 port。

## 全局约束

- 本文只定义实施任务，不实施代码；禁止无意义重构，只修改各 Task 明确列出的文件。
- 每个 Task 只交付一个可独立拒绝的能力；不能为了减少 Task 数把合同、算法、编排、adapter、文档或回归验收合并。
- 每个 Task 实施时遵循同一 TDD 循环：先增加失败断言，运行本 Task 命令确认失败，完成最小实现，再运行同一命令确认通过。
- `machine_answer`、`claims`、`citations` 和 `status` 是权威输出；文本生成器不得新增、删除或改绑 claim/citation。
- 来源事实、派生关系、语义观察、语义解释、候选关系、正式关系和 diagnostic 必须保持分层；candidate/interpretation 不得提升为 formal/source fact。
- `DrawingAssistantService` 必须拒绝 `allow_write_back=true`；04 固定 `write_back=false`；05 固定 `write_back_policy=None`。
- 产品 CLI 不提供 write-back 参数；不输出密码、token、URI、Cypher、绝对路径、traceback 或 provider 原始响应。
- 不改变 Neo4j schema，不新增答案、trace、反馈或文本生成结果持久化。
- 不改造或替换现有 `DrawingGraphQAService`、QA CLI、HTTP、MCP；产品 CLI 是同级 adapter。
- 默认不装配真实文本 provider；fake/模板验证不能表述为 live provider 已验证。
- 单元、fake runtime、CLI smoke、live Neo4j、live DashScope/真实文本 provider 必须分层报告；skipped 不等于 live 通过。
- 当前工作区已有其他未提交修改；实施者必须保留无关改动，不得 reset、覆盖或顺手重构。

## 文件责任

| 文件 | 单一责任 | 首次建立 Task |
|---|---|---:|
| `assistant_models.py` | 产品答案、子请求和执行策略公共合同 | 1 |
| `assistant_claim_builder.py` | EvidenceBundle 到确定性 claim | 21 |
| `assistant_citation_builder.py` | evidence/provenance 到最小 citation | 28 |
| `assistant_answer_templates.py` | 确定性中文模板 | 35 |
| `assistant_answer_text.py` | 受约束文本 port、fake、校验 | 37 |
| `assistant_answer_generation.py` | 06 唯一编排入口、machine answer、canonical JSON | 31 |
| `drawing_assistant_service.py` | 07 只读总编排 | 46 |
| `drawing_assistant_factory.py` | 无副作用装配 | 59 |
| `scripts/drawing_assistant.py` | 产品级只读 CLI adapter | 60 |

## 任务总览

| 阶段 | Tasks | 交付物 |
|---|---:|---|
| 公共答案合同 | 1—8 | 枚举、Claim、Citation、Subanswer、MachineAnswer、AnswerPackage、06/07 policy |
| 02/03/05 接缝 | 9—20 | subrequest 透传、冲突分桶、provenance、confidence、unsupported、warnings |
| Claim/Citation | 21—30 | 确定性 claim、最小 citation、双向完整性 |
| Machine/模板/文本 | 31—40 | 状态、machine answer、canonical JSON、模板、受约束文本回退 |
| 06 服务 | 41—45 | 终止态、正常流水线、资源限制、脱敏、静态边界 |
| 07 服务 | 46—58 | 子请求、只读门禁、识别分组、多意图、聚合、异常和边界 |
| Factory/CLI | 59—65 | 无副作用装配、参数、生命周期、输出、错误、fake E2E |
| 兼容/文档/验收 | 66—74 | QA 兼容、文档同步、专项回归和分层验证记录 |

---

## Task 1：答案版本、状态与原因码合同

**明确目标：** 定义 `drawing-assistant-answer-v1`、`AnswerStatus`、`ClaimStatus`、`TextRenderMode` 及 06/07 专用稳定原因码。

**指定修改文件：** 修改 `src/drawing_graph/assistant_models.py`；新增 `tests/test_assistant_answer_models.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_models.AnswerEnumContractTests -v`

**完成标准：** 枚举值与 design 一致；未知值被拒绝；既有 `ReasonCode` 不删除、不改名；序列化不依赖中文文案。

## Task 2：Claim 兼容性合同

**明确目标：** 为现有 `Claim` 增加 `subrequest_id`、`reason_codes` 和 `citation_ids`，同时保持旧构造方式可用。

**指定修改文件：** 修改 `src/drawing_graph/assistant_models.py`、`tests/test_assistant_answer_models.py`、`tests/test_assistant_models_contract.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_models.ClaimContractTests tests.test_assistant_models_contract -v`

**完成标准：** 新字段有兼容默认值并不可变；旧测试通过；字段校验拒绝非法 tuple/空 ID；本 Task 不实现 claim 生成。

## Task 3：Citation 兼容性合同

**明确目标：** 为现有 `Citation` 增加 `citation_id`、`evidence_id`、`claim_ids`、`project_id` 和 `drawing_set_id`。

**指定修改文件：** 修改 `src/drawing_graph/assistant_models.py`、`tests/test_assistant_answer_models.py`、`tests/test_assistant_models_contract.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_models.CitationContractTests tests.test_assistant_models_contract -v`

**完成标准：** 旧 citation 构造仍有效；新字段稳定序列化；bbox 仍不可变；本 Task 不投影 evidence 或生成 citation ID。

## Task 4：Subanswer 合同

**明确目标：** 定义多意图聚合所需的不可变 `Subanswer` DTO。

**指定修改文件：** 修改 `src/drawing_graph/assistant_models.py`、`tests/test_assistant_answer_models.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_models.SubanswerContractTests -v`

**完成标准：** subrequest、状态、claim/citation IDs、warning 和 unsupported 字段完整；ID 为空或状态非法时拒绝；不包含执行逻辑。

## Task 5：MachineAnswer 合同

**明确目标：** 定义字段顺序固定的权威 `MachineAnswer` DTO。

**指定修改文件：** 修改 `src/drawing_graph/assistant_models.py`、`tests/test_assistant_answer_models.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_models.MachineAnswerContractTests -v`

**完成标准：** 字段集合和声明顺序与 design 一致；合同版本必填；claims/citations/subanswers 只接受正确 DTO；不接受未声明动态字段。

## Task 6：AnswerPackage 兼容性合同

**明确目标：** 为 `AnswerPackage` 增加合同版本、subanswers、reason codes 和 render mode，并保持既有占位消费者兼容。

**指定修改文件：** 修改 `src/drawing_graph/assistant_models.py`、`tests/test_assistant_answer_models.py`、`tests/test_assistant_models_contract.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_models.AnswerPackageContractTests tests.test_assistant_models_contract -v`

**完成标准：** 旧构造仍通过；新字段稳定且不可变；`machine_answer` 接受设计允许的兼容类型；本 Task 不构造答案。

## Task 7：06 请求、失败记录与生成策略合同

**明确目标：** 定义 `AnswerGenerationRequest`、`RecognitionFailure` 和只控制表现/资源的 `AnswerGenerationPolicy`。

**指定修改文件：** 修改 `src/drawing_graph/assistant_models.py`、`tests/test_assistant_answer_models.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_models.AnswerGenerationInputContractTests -v`

**完成标准：** 三个 DTO 的字段与 design 一致；资源值必须为正；失败记录不接受 traceback/provider 原文；policy 不存在写回或事实等级覆写字段。

## Task 8：07 执行策略合同

**明确目标：** 定义组合既有 retrieval/recognition policy 和 07 资源上限的 `AssistantExecutionPolicy`。

**指定修改文件：** 修改 `src/drawing_graph/assistant_models.py`、`tests/test_assistant_answer_models.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_models.AssistantExecutionPolicyTests -v`

**完成标准：** 默认值只读且有限；非法上限被拒绝；不存在 write-back 字段；policy 不能覆盖请求的 `allow_recognition=false`。

## Task 9：QuestionUnderstandingResult 子请求字段

**明确目标：** 为 projected 单子请求结果增加兼容的可选 `subrequest_id`。

**指定修改文件：** 修改 `src/drawing_graph/assistant_models.py`、`tests/test_assistant_question_models.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_question_models -v`

**完成标准：** 顶层默认 `None`；非空 ID 被保留；空白 ID 被拒绝；01 既有单/多意图输出不变。

## Task 10：RetrievalPlan 子请求透传

**明确目标：** 使 `RetrievalPlanner` 把 projected question 的 `subrequest_id` 写入 `RetrievalPlan`。

**指定修改文件：** 修改 `src/drawing_graph/assistant_retrieval_planner.py`、`tests/test_assistant_retrieval_planner.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_retrieval_planner.RetrievalSubrequestPlanTests -v`

**完成标准：** ID 原样透传；顶层仍为 `None`；检索步骤、白名单、limit 和 payload 策略无变化。

## Task 11：RetrievalBundle 子请求透传

**明确目标：** 使 `RetrievalBundleBuilder` 把 plan 的 `subrequest_id` 写入 `RetrievalBundle`。

**指定修改文件：** 修改 `src/drawing_graph/assistant_retrieval_projection.py`、`tests/test_assistant_retrieval_projection.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_retrieval_projection.RetrievalSubrequestProjectionTests -v`

**完成标准：** bundle 与 plan ID 一致；顶层兼容；不改变 evidence bucket、missing evidence 或 retrieval status。

## Task 12：SemanticGapDecision 子请求一致性

**明确目标：** 校验 question、retrieval 和 decision 的 projected `subrequest_id` 一致并继续透传。

**指定修改文件：** 修改 `src/drawing_graph/assistant_semantic_gap_decision.py`、`tests/test_assistant_semantic_gap_decision.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_semantic_gap_decision.SemanticGapSubrequestTests -v`

**完成标准：** 一致 ID 正常返回；不一致 fail closed；顶层 `None` 兼容；不改变缺口评估、目标规划或预算算法。

## Task 13：ClaimSupportAssessment 子请求归属

**明确目标：** 使 05 claim 支撑结果携带当前 projected `subrequest_id`。

**指定修改文件：** 修改 `src/drawing_graph/assistant_claim_support.py`、`tests/test_assistant_claim_support.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_claim_support.ClaimSupportSubrequestTests -v`

**完成标准：** 每项 assessment 归属正确；顶层仍为 `None`；capability、formal gate 和支撑状态逻辑不变。

## Task 14：AnswerabilityResult 子请求归属

**明确目标：** 使 projected 单子请求的 answerability 保留 `subrequest_id`。

**指定修改文件：** 修改 `src/drawing_graph/assistant_answerability.py`、`tests/test_assistant_answerability.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answerability.AnswerabilitySubrequestTests -v`

**完成标准：** 单子请求和多意图子结果均有正确 ID；request 聚合状态不变；不匹配 ID 不被错误合并。

## Task 15：EvidenceBundle 子请求归属

**明确目标：** 使 `EvidenceFusionService` 的最终 bundle 透传已验证的 `subrequest_id`。

**指定修改文件：** 修改 `src/drawing_graph/assistant_evidence_fusion.py`、`tests/test_assistant_evidence_fusion.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion.EvidenceBundleSubrequestTests -v`

**完成标准：** 05 输出 ID 与 02/03 一致；不一致输入仍由既有关联校验拒绝；顶层流程兼容。

## Task 16：Accepted 与 conflicting evidence 分桶

**明确目标：** 修正 05 最终分桶，使 accepted 只含可回答证据、conflicting 只含冲突成员。

**指定修改文件：** 修改 `src/drawing_graph/assistant_evidence_fusion.py`、`tests/test_assistant_evidence_fusion.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion.EvidenceBucketTests -v`

**完成标准：** 两桶不再无条件全量相同；阻断冲突不进入 accepted；未冲突可用证据不进入 conflicting；不在 06 选择 winner。

## Task 17：EvidenceBundle provenance 投影

**明确目标：** 将 05 已产生的去重/来源信息稳定投影到 `EvidenceBundle.provenance`。

**指定修改文件：** 修改 `src/drawing_graph/assistant_evidence_fusion.py`、`tests/test_assistant_evidence_fusion.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion.EvidenceProvenanceOutputTests -v`

**完成标准：** provenance 可回指 surviving/merged evidence；顺序稳定；不复制完整 payload；不修改原 evidence。

## Task 18：EvidenceBundle overall confidence

**明确目标：** 按 05 已批准证据与支撑状态计算并输出确定性的 `overall_confidence`。

**指定修改文件：** 修改 `src/drawing_graph/assistant_evidence_fusion.py`、`tests/test_assistant_evidence_fusion.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion.EvidenceConfidenceOutputTests -v`

**完成标准：** 空证据、partial、冲突和正常支撑都有稳定结果；candidate 不因置信度变成 formal；不读取文本模型结果。

## Task 19：EvidenceBundle unsupported claims

**明确目标：** 将 unsupported/missing/stale-only 的 requirement 结果稳定投影到 `unsupported_claims`。

**指定修改文件：** 修改 `src/drawing_graph/assistant_evidence_fusion.py`、`tests/test_assistant_evidence_fusion.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion.UnsupportedClaimOutputTests -v`

**完成标准：** 只输出稳定 requirement/capability 标识；不生成工程 statement；去重和顺序确定；supported 项不误入。

## Task 20：EvidenceBundle warnings 输出

**明确目标：** 将 05 阶段的安全、截断和降级信息稳定投影到最终 warnings。

**指定修改文件：** 修改 `src/drawing_graph/assistant_evidence_fusion.py`、`tests/test_assistant_evidence_fusion.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_evidence_fusion.EvidenceWarningOutputTests -v`

**完成标准：** warnings 稳定、去重、已脱敏；不含 traceback/路径/凭据；`write_back_result=not_requested` 不成为工程 warning。

## Task 21：稳定 Claim ID

**明确目标：** 实现只依赖合同版本、请求/子请求、capability、scope、status 和排序 evidence IDs 的稳定 claim ID。

**指定修改文件：** 新增 `src/drawing_graph/assistant_claim_builder.py`、`tests/test_assistant_claim_builder.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_claim_builder.StableClaimIdTests -v`

**完成标准：** 相同语义输入 ID 相同；evidence 输入顺序不影响 ID；关键字段变化会改变 ID；不使用时间戳或随机数。

## Task 22：Supported claim 构造

**明确目标：** 将 `ClaimSupportStatus.SUPPORTED` 确定性构造为有证据的正常 claim。

**指定修改文件：** 修改 `src/drawing_graph/assistant_claim_builder.py`、`tests/test_assistant_claim_builder.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_claim_builder.SupportedClaimTests -v`

**完成标准：** statement、capability、scope、confidence、fact kinds 和 evidence IDs 正确；无支撑 evidence 时不发布；不调用模型。

## Task 23：Qualified claim 构造

**明确目标：** 将 `SUPPORTED_WITH_QUALIFIER` 构造为限定语不可删除的 qualified claim。

**指定修改文件：** 修改 `src/drawing_graph/assistant_claim_builder.py`、`tests/test_assistant_claim_builder.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_claim_builder.QualifiedClaimTests -v`

**完成标准：** 05 qualifiers 完整保留并稳定排序；状态为 qualified；低置信/partial/ambiguous 不被写成无条件结论。

## Task 24：Conflicting claim 构造

**明确目标：** 将阻断冲突构造为不选择 winner 的冲突说明 claim。

**指定修改文件：** 修改 `src/drawing_graph/assistant_claim_builder.py`、`tests/test_assistant_claim_builder.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_claim_builder.ConflictingClaimTests -v`

**完成标准：** 状态为 conflicting；statement 明确存在冲突；关联全部冲突证据；不输出正式确定性结论。

## Task 25：Formal review required claim 构造

**明确目标：** 将 `FORMAL_REVIEW_REQUIRED` 只构造为候选/待复核 claim。

**指定修改文件：** 修改 `src/drawing_graph/assistant_claim_builder.py`、`tests/test_assistant_claim_builder.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_claim_builder.FormalReviewClaimTests -v`

**完成标准：** candidate evidence 不能产生 confirmed/formal statement；限定语包含待复核；不存在候选提升或写回调用。

## Task 26：非生成状态处理

**明确目标：** 使 missing、stale-only 和 unsupported 不生成工程事实 claim。

**指定修改文件：** 修改 `src/drawing_graph/assistant_claim_builder.py`、`tests/test_assistant_claim_builder.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_claim_builder.NonGeneratingStatusTests -v`

**完成标准：** 三类状态产生零工程 claim；信息进入结构化 unsupported/follow-up 输入；不编造 statement 或 citation。

## Task 27：Diagnostic claim 构造

**明确目标：** 为允许无工程 evidence 的运行诊断生成明确标记的 diagnostic claim。

**指定修改文件：** 修改 `src/drawing_graph/assistant_claim_builder.py`、`tests/test_assistant_claim_builder.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_claim_builder.DiagnosticClaimTests -v`

**完成标准：** diagnostic 必须有稳定 reason code；statement 明确为运行状态；不得伪装成工程事实；无 reason code 时拒绝。

## Task 28：最小 Citation 投影

**明确目标：** 从 claim evidence、FusionEvidence 和 provenance 投影当前 claim 所需的最小 citation 字段。

**指定修改文件：** 新增 `src/drawing_graph/assistant_citation_builder.py`、`tests/test_assistant_citation_builder.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_citation_builder.MinimalCitationProjectionTests -v`

**完成标准：** evidence/page/block/element/bbox/语义引用按存在性输出；不复制 payload；默认不输出 image path、URI 或内部 ID。

## Task 29：稳定 Citation ID 与排序

**明确目标：** 为最小 citation 生成稳定 ID、确定性去重和业务排序。

**指定修改文件：** 修改 `src/drawing_graph/assistant_citation_builder.py`、`tests/test_assistant_citation_builder.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_citation_builder.StableCitationOrderingTests -v`

**完成标准：** 相同公开定位产生相同 ID；输入乱序不改变输出；排序符合 claim→fact kind→定位→evidence 规则。

## Task 30：Claim/Citation 双向完整性

**明确目标：** 建立 claim 的 `citation_ids` 与 citation 的 `claim_ids` 双向一致关系。

**指定修改文件：** 修改 `src/drawing_graph/assistant_citation_builder.py`、`tests/test_assistant_citation_builder.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_citation_builder.ClaimCitationIntegrityTests -v`

**完成标准：** 每条非诊断 claim 至少一个 citation；citation 必须回指 bundle evidence；孤立/错绑/缺失引用 fail closed。

## Task 31：答案状态解析器

**明确目标：** 按 answerability、claim、冲突、unsupported 和识别失败解析唯一 `AnswerStatus`。

**指定修改文件：** 新增 `src/drawing_graph/assistant_answer_generation.py`、`tests/test_assistant_answer_generation.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_generation.AnswerStatusResolverTests -v`

**完成标准：** answered/partial/clarification/unsupported/recognition_failed 覆盖完整；优先级与 design 一致；不按异常文案判断。

## Task 32：MachineAnswer 构造

**明确目标：** 从同一组已批准输出构造权威 `MachineAnswer`。

**指定修改文件：** 修改 `src/drawing_graph/assistant_answer_generation.py`、`tests/test_assistant_answer_generation.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_generation.MachineAnswerBuilderTests -v`

**完成标准：** 字段来源唯一；claims/citations/status/warnings 等稳定排序；不包含运行对象、未知字段或敏感配置。

## Task 33：Canonical JSON 序列化

**明确目标：** 产生相同输入字节一致的 UTF-8 产品答案 JSON。

**指定修改文件：** 修改 `src/drawing_graph/assistant_answer_generation.py`；新增 `tests/test_assistant_answer_serialization.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_serialization -v`

**完成标准：** 复用 `to_jsonable()`；固定字段/集合顺序和 separators；`ensure_ascii=false`；拒绝 NaN/Infinity/不可序列化对象；完整字符串重复比较一致。

## Task 34：AnswerPackage 一致性校验

**明确目标：** 校验 package 顶层字段与 `machine_answer` 同源且 claim/citation/status 一致。

**指定修改文件：** 修改 `src/drawing_graph/assistant_answer_generation.py`、`tests/test_assistant_answer_generation.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_generation.AnswerPackageValidatorTests -v`

**完成标准：** 双份数据不一致、孤立引用、非法事实提升和未知动态字段均 fail closed；合法 package 不被修改。

## Task 35：中文模板章节与状态渲染

**明确目标：** 按固定章节和答案状态生成始终可用的简短中文模板。

**指定修改文件：** 新增 `src/drawing_graph/assistant_answer_templates.py`、`tests/test_assistant_answer_templates.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_templates.TemplateStructureTests -v`

**完成标准：** 五个章节顺序固定；五类答案状态都有稳定文本；空章节按合同处理；不引入新 claim。

## Task 36：事实等级中文措辞

**明确目标：** 为各 `FactKind` 和 claim status 实现不会提升事实等级的中文措辞。

**指定修改文件：** 修改 `src/drawing_graph/assistant_answer_templates.py`、`tests/test_assistant_answer_templates.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_templates.FactKindWordingTests -v`

**完成标准：** observation/interpretation/candidate/formal/diagnostic 措辞可区分；candidate 和 interpretation 负向断言通过；qualifier 不丢失。

## Task 37：受约束文本生成 port 与 fake

**明确目标：** 定义供应商无关请求/结果/protocol 和无网络 fake 实现。

**指定修改文件：** 新增 `src/drawing_graph/assistant_answer_text.py`、`tests/test_assistant_answer_text.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_text.TextPortContractTests -v`

**完成标准：** 输入只含 approved claims、公开 citation 标签、限定语和章节；fake 可确定性返回；模块不读取环境或访问网络。

## Task 38：文本 ID 与 Citation allowlist 校验

**明确目标：** 拒绝文本生成结果新增、遗漏或改绑 claim/citation。

**指定修改文件：** 修改 `src/drawing_graph/assistant_answer_text.py`、`tests/test_assistant_answer_text.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_text.TextIdentifierAllowlistTests -v`

**完成标准：** claim ID 集合必须完全一致；citation 只能来自 allowlist；重复、未知、遗漏和改绑均被拒绝。

## Task 39：文本事实与限定语门禁

**明确目标：** 拒绝文本生成结果引入未批准数字/业务 ID/实体或删除不可缺少限定语。

**指定修改文件：** 修改 `src/drawing_graph/assistant_answer_text.py`、`tests/test_assistant_answer_text.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_text.TextSemanticGateTests -v`

**完成标准：** 新数字/实体/确定性措辞被拒绝；candidate/interpretation/冲突限定语不可删除；注入式图纸文字不能改变合同。

## Task 40：文本生成模板回退

**明确目标：** 在超时、异常、无效 JSON 或校验失败时稳定回退中文模板。

**指定修改文件：** 修改 `src/drawing_graph/assistant_answer_text.py`、`tests/test_assistant_answer_text.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_text.TextFallbackTests -v`

**完成标准：** 所有失败返回模板和稳定 warning；machine answer 不变；不泄露原始 provider 响应；无生成器时不访问网络。

## Task 41：06 终止态答案生成

**明确目标：** 让 `AnswerGenerationService.generate()` 在无 EvidenceBundle 的合法澄清/unsupported 请求中生成终止态 package。

**指定修改文件：** 修改 `src/drawing_graph/assistant_answer_generation.py`、`tests/test_assistant_answer_generation.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_generation.TerminalAnswerTests -v`

**完成标准：** 两类终止态无需 evidence；其他状态缺 bundle 被拒绝；不调用 claim/citation builder 或文本 provider。

## Task 42：06 正常固定流水线

**明确目标：** 串联 claim→citation→status→machine→validate→template，形成 06 唯一正常入口。

**指定修改文件：** 修改 `src/drawing_graph/assistant_answer_generation.py`、`tests/test_assistant_answer_generation.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_generation.AnswerGenerationPipelineTests -v`

**完成标准：** 协作者调用顺序固定；输出同源且确定；任一完整性错误 fail closed；默认 render mode 为 template。

## Task 43：06 资源上限

**明确目标：** 对 claim、citation、warning 和文本长度执行可测试的生成阶段上限。

**指定修改文件：** 修改 `src/drawing_graph/assistant_answer_generation.py`、`tests/test_assistant_answer_generation.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_generation.AnswerGenerationLimitTests -v`

**完成标准：** 超限采用设计规定的拒绝/显式截断；不得静默丢必需 claim/citation；输出稳定 reason code。

## Task 44：06 输出最小化与错误脱敏

**明确目标：** 防止答案或 06 异常携带路径、凭据、Cypher、traceback、完整 payload 或 provider 原文。

**指定修改文件：** 修改 `src/drawing_graph/assistant_answer_generation.py`；新增 `tests/test_assistant_answer_security.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_security.AnswerOutputSecurityTests -v`

**完成标准：** 敏感样例均不出现在 package/JSON/message；payload_ref 可保留但不解引用；错误码稳定。

## Task 45：06 静态依赖边界

**明确目标：** 用静态测试禁止 06 模块导入 facade、repository、driver、Cypher、provider 具体实现或写回模块。

**指定修改文件：** 新增 `tests/test_assistant_answer_boundaries.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_boundaries -v`

**完成标准：** 允许依赖清单明确；禁止导入均有负向断言；06 只消费公共 DTO/05 输出和可选文本 port。

## Task 46：SubrequestProjector

**明确目标：** 将单个 `AssistantSubrequest` 投影为带父 request ID 和自身 subrequest ID 的独立 question result。

**指定修改文件：** 新增 `src/drawing_graph/drawing_assistant_service.py`、`tests/test_drawing_assistant_service.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service.SubrequestProjectorTests -v`

**完成标准：** scope、requirements、ambiguity、unsupported 和原始顺序完整保留；不混用其他子请求字段。

## Task 47：总编排只读入口门禁

**明确目标：** 在 `DrawingAssistantService.answer()` 调用任何依赖前拒绝 `allow_write_back=true`。

**指定修改文件：** 修改 `src/drawing_graph/drawing_assistant_service.py`、`tests/test_drawing_assistant_service.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service.ReadOnlyEntryGateTests -v`

**完成标准：** true 请求得到稳定领域错误；所有 01—06/facade fake 调用计数为零；问题文本中的写回要求不构成授权。

## Task 48：Clarification/Unsupported 早停

**明确目标：** 对无子请求的 clarification/unsupported 结果跳过 02—05 并进入 06 终止态。

**指定修改文件：** 修改 `src/drawing_graph/drawing_assistant_service.py`、`tests/test_drawing_assistant_service.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service.EarlyStopTests -v`

**完成标准：** 02—05 调用为零；06 恰调用一次；有子请求的顶层 clarification 不误早停整个请求。

## Task 49：单意图 01—03 编排

**明确目标：** 串联 question understanding、graph retrieval 和 semantic gap decision 的单意图只读前半链。

**指定修改文件：** 修改 `src/drawing_graph/drawing_assistant_service.py`、`tests/test_drawing_assistant_service.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service.SingleIntentFrontHalfTests -v`

**完成标准：** 调用顺序和参数准确；request/subrequest ID 不变；07 不复制 01—03 内部算法。

## Task 50：RecognitionTarget 按页分组

**明确目标：** 对 03 selected targets 按 `page_id` 确定性分组并拒绝缺页必需目标。

**指定修改文件：** 修改 `src/drawing_graph/drawing_assistant_service.py`、`tests/test_drawing_assistant_service.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service.RecognitionTargetGroupingTests -v`

**完成标准：** 分组及页顺序稳定；同页目标不拆散；缺 page ID 转结构化失败；不调用 facade。

## Task 51：按页识别执行与失败记录

**明确目标：** 每页调用一次 facade，并把页级异常转换为 `RecognitionFailure` 而不丢其他页结果。

**指定修改文件：** 修改 `src/drawing_graph/drawing_assistant_service.py`、`tests/test_drawing_assistant_service.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service.PageRecognitionExecutionTests -v`

**完成标准：** 每次均显式 `write_back=false`；成功页保留；失败已脱敏；所有页失败不伪造 recognition result。

## Task 52：识别禁止与无需识别分支

**明确目标：** 在请求禁止识别或 03 判定无需识别时完全跳过 facade recognition。

**指定修改文件：** 修改 `src/drawing_graph/drawing_assistant_service.py`、`tests/test_drawing_assistant_service.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service.RecognitionSkipTests -v`

**完成标准：** `allow_recognition=false` 优先；无需识别时调用为零；deferred/missing 信息继续进入融合上下文。

## Task 53：05 只读调用

**明确目标：** 用完整上下文调用 `EvidenceFusionService.fuse()` 且永不传可写 policy。

**指定修改文件：** 修改 `src/drawing_graph/drawing_assistant_service.py`、`tests/test_drawing_assistant_service.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service.ReadOnlyFusionCallTests -v`

**完成标准：** assistant/question/retrieval/decision/recognition 参数齐全；`write_back_policy=None`；03 recommendation 不变成授权。

## Task 54：多意图逐子请求执行

**明确目标：** 按 01 原始顺序为每个子请求独立执行 02—06。

**指定修改文件：** 修改 `src/drawing_graph/drawing_assistant_service.py`、`tests/test_drawing_assistant_service.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service.MultiIntentExecutionTests -v`

**完成标准：** 不把顶层空 requirements 送入 02；子请求证据和状态隔离；MVP 串行；一个失败不抹去已完成子请求。

## Task 55：AnswerPackageAggregator

**明确目标：** 按固定优先级聚合 subanswers、claims、citations、warnings、unsupported、run IDs 和整体状态。

**指定修改文件：** 修改 `src/drawing_graph/drawing_assistant_service.py`、`tests/test_drawing_assistant_service.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service.AnswerPackageAggregatorTests -v`

**完成标准：** answered/partial/clarification/unsupported/recognition_failed 聚合符合 design；不跨语义合并 claim；只去重完全相同引用/警告。

## Task 56：07 资源上限

**明确目标：** 对 subrequest、page group、target、claim 和 citation 数量执行总编排上限。

**指定修改文件：** 修改 `src/drawing_graph/drawing_assistant_service.py`、`tests/test_drawing_assistant_service.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service.AssistantResourceLimitTests -v`

**完成标准：** 每个上限有边界/超限断言；超限稳定拒绝或显式截断；不得静默丢必需子请求或引用。

## Task 57：07 异常分类

**明确目标：** 将输入、合同、必需检索、页级识别和可选阶段失败映射为设计规定的领域结果。

**指定修改文件：** 修改 `src/drawing_graph/drawing_assistant_service.py`、`tests/test_drawing_assistant_service.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service.AssistantErrorMappingTests -v`

**完成标准：** 基础设施失败与业务状态分离；partial 保留已有结果；错误已脱敏；不按原始异常文案推导状态。

## Task 58：07 静态依赖边界

**明确目标：** 禁止总编排模块直接导入 driver、repository、Cypher、CLI、QA service、provider 具体实现或写回内部模块。

**指定修改文件：** 新增 `tests/test_drawing_assistant_boundaries.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_boundaries -v`

**完成标准：** 只允许 01—06 public service、DTO 和 facade public API；所有禁止依赖均有静态负向断言。

## Task 59：无副作用 DrawingAssistant factory

**明确目标：** 装配默认 01—07 服务并支持注入 facade/可选文本生成器，factory 调用本身无外部副作用。

**指定修改文件：** 新增 `src/drawing_graph/drawing_assistant_factory.py`、`tests/test_drawing_assistant_factory.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_factory -v`

**完成标准：** 创建时不连接、不查询、不调用 provider；不接收裸 repository/session；默认无真实文本生成器；不扩张 `tool_factory.py`。

## Task 60：CLI 参数与 AssistantRequest 映射

**明确目标：** 定义产品 CLI 参数并稳定构造 `AssistantRequest` 和执行策略。

**指定修改文件：** 新增 `scripts/drawing_assistant.py`、`tests/test_drawing_assistant_cli.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_cli.CliArgumentMappingTests -v`

**完成标准：** question/request ID/scope/recognition/text/output 映射正确；默认 JSON；参数列表不存在 write-back、密码、token 或 URI。

## Task 61：CLI 生命周期与服务调用

**明确目标：** 让 CLI 管理 driver/facade 生命周期并只调用 `DrawingAssistantService.answer()`。

**指定修改文件：** 修改 `scripts/drawing_assistant.py`、`tests/test_drawing_assistant_cli.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_cli.CliLifecycleTests -v`

**完成标准：** success/error 都关闭资源；service 只调用一次；CLI 不承载检索、识别分组或答案规则；测试使用 fake factory。

## Task 62：CLI JSON 与中文输出

**明确目标：** 按 `--output` 输出单一 canonical JSON envelope 或纯 `text_answer`。

**指定修改文件：** 修改 `scripts/drawing_assistant.py`、`tests/test_drawing_assistant_cli.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_cli.CliOutputTests -v`

**完成标准：** stdout 无调试噪音；JSON 仅一个 envelope；中文模式不夹 warning/日志；相同显式 request ID 输出字节一致。

## Task 63：CLI 退出码与错误 envelope

**明确目标：** 实现业务状态 0、运行失败 1、参数/配置/合同错误 2 的稳定映射。

**指定修改文件：** 修改 `scripts/drawing_assistant.py`、`tests/test_drawing_assistant_cli.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_cli.CliExitCodeTests -v`

**完成标准：** partial/clarification/unsupported/recognition_failed 均为 0；错误 envelope 已脱敏；stderr/stdout 职责明确。

## Task 64：CLI 静态安全边界

**明确目标：** 禁止产品 CLI 直接访问 repository、Cypher、provider、写回模块或离线增强规则。

**指定修改文件：** 新增 `tests/test_drawing_assistant_cli_boundaries.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_cli_boundaries -v`

**完成标准：** 允许依赖仅为配置、factory、DTO、序列化和 driver 生命周期；敏感字段/绝对路径/traceback 泄漏有负向断言。

## Task 65：产品 CLI fake 端到端

**明确目标：** 用 fake facade/服务装配验证自然语言输入到最终 CLI 输出的完整离线链路。

**指定修改文件：** 新增 `tests/test_drawing_assistant_e2e.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_e2e -v`

**完成标准：** answered、partial、clarification、unsupported、recognition_failed 均覆盖；无 Neo4j/网络依赖；不能宣称 live 已验证。

## Task 66：现有 QA/HTTP/MCP 兼容回归

**明确目标：** 证明新增产品链路没有改变现有固定 QA、HTTP 和 MCP 行为。

**指定修改文件：** 修改 `tests/test_qa_service.py`、`tests/test_qa_cli.py`、`tests/test_qa_http.py`、`tests/test_qa_mcp_tools.py`（仅在需要新增兼容断言时）。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_qa_service tests.test_qa_cli tests.test_qa_http tests.test_qa_mcp_tools -v`

**完成标准：** 六类 QA 输入输出兼容；旧 adapter 不依赖 `DrawingAssistantService`；不存在产品 CLI 反向替换。

## Task 67：Module.md 实现同步

**明确目标：** 在实际代码完成后同步新增模块职责、接口、依赖和不包含范围。

**指定修改文件：** 修改 `Module.md`、`tests/test_module_docs.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_module_docs -v`

**完成标准：** 只记录已实现能力；01—07/factory/CLI 职责准确；candidate/formal、只读和文本非权威边界明确。

## Task 68：architecture.md 实现同步

**明确目标：** 在实际代码完成后同步产品 CLI→07→01—06→facade 的架构和依赖方向。

**指定修改文件：** 修改 `architecture.md`；新增或修改 `tests/test_assistant_answer_docs.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_docs.ArchitectureDocumentationTests -v`

**完成标准：** 架构图与代码一致；QA 链保持独立；无 schema/写回扩张；未验证 live 能力不写成已完成。

## Task 69：README 产品 CLI 使用说明

**明确目标：** 在 CLI 实现后提供最短只读运行示例、参数、输出和验证边界。

**指定修改文件：** 修改 `README.md`、`tests/test_readme.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_readme -v`

**完成标准：** 示例无 write-back/密钥；JSON/中文模式和退出码准确；明确默认模板与可选文本生成；不承诺 live 可用。

## Task 70：Change 文档状态同步

**明确目标：** 在实现与专项验证完成后更新本 change 的 proposal/design/tasks 状态和实施证据索引。

**指定修改文件：** 修改 `changes/产品实现层/答案生成与只读总编排MVP/proposal.md`、`design.md`、`tasks.md`；修改 `tests/test_assistant_answer_docs.py`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_docs -v`

**完成标准：** 状态只引用实际命令与结果；未运行层级标为未验证；不把计划、历史数字或 skipped 当成完成证据。

## Task 71：06 专项回归验收

**明确目标：** 运行并记录答案合同、claim/citation、JSON、模板、文本约束和 06 边界的专项回归。

**指定修改文件：** 新增 `docs/acceptance/ANSWER_GENERATION_MVP_ACCEPTANCE.md`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_answer_models tests.test_assistant_claim_builder tests.test_assistant_citation_builder tests.test_assistant_answer_serialization tests.test_assistant_answer_templates tests.test_assistant_answer_text tests.test_assistant_answer_generation tests.test_assistant_answer_security tests.test_assistant_answer_boundaries -v`

**完成标准：** 命令、通过/失败/跳过数量和日期如实记录；每个 design 负向门禁有证据；不包含 live 声明。

## Task 72：07 专项回归验收

**明确目标：** 运行并记录总编排、factory、只读门禁、跨页、多意图和异常聚合的专项回归。

**指定修改文件：** 修改 `docs/acceptance/ANSWER_GENERATION_MVP_ACCEPTANCE.md`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_service tests.test_drawing_assistant_boundaries tests.test_drawing_assistant_factory -v`

**完成标准：** 单/多意图、早停、page grouping、write_back=false、partial/recognition_failed 有新鲜结果；factory 无副作用有证据。

## Task 73：产品 CLI smoke 验收

**明确目标：** 运行并记录 fake runtime 下的产品 CLI 子进程 smoke。

**指定修改文件：** 修改 `tests/test_drawing_assistant_e2e.py`、`docs/acceptance/ANSWER_GENERATION_MVP_ACCEPTANCE.md`。

**可独立测试：** `$env:PYTHONPATH='src'; python -m unittest tests.test_drawing_assistant_cli tests.test_drawing_assistant_cli_boundaries tests.test_drawing_assistant_e2e -v`

**完成标准：** stdout 纯净、退出码、JSON/text、错误脱敏均有子进程证据；明确 fake smoke 不证明 live Neo4j/provider。

## Task 74：完整离线回归与 live 状态记录

**明确目标：** 运行完整离线回归，并把 live Neo4j、live DashScope 和真实文本 provider 状态分开记录。

**指定修改文件：** 修改 `docs/acceptance/ANSWER_GENERATION_MVP_ACCEPTANCE.md`。

**可独立测试：** `python -m unittest discover tests -v`

**完成标准：** 记录完整命令、退出码、通过/失败/跳过数量；保留所有既有回归；live 三层分别标记“已验证/未验证”，skipped 不计为 live 通过。

---

## 任务依赖与执行规则

- 严格按 Task 编号执行；后续 Task 只消费前序 Task 明确交付的 public contract。
- Task 1—8 完成前不实现 builder/service；Task 9—20 完成前不让 06 猜测 subrequest、冲突或 provenance。
- Task 21—40 可按模块顺序实施，但每个 Task 必须单独完成 red/green 和评审，不得一次提交整段 06。
- Task 41—45 通过后才开始 07；Task 46—58 通过后才装配 factory/CLI。
- Task 67—70 只能在对应实现和验证真实完成后同步，不得提前把 design 能力写成当前实现。
- Task 71—74 是四个不同验证层，不能互相替代，也不能并成一个“全部测试”Task。
- 每完成一个 Task，只暂存该 Task 指定文件；若指定文件含用户既有修改，先检查 diff 并保留无关内容。

## 最终完成定义

- 74 个 Task 均有独立评审结果，且没有被合并跳过。
- 产品答案合同、claim/citation、canonical JSON、中文模板和受约束文本回退与 design 一致。
- 07 能处理早停、单意图、多意图、跨页识别、部分成功和只读门禁。
- 产品 CLI 不提供写回，stdout/退出码/错误脱敏满足合同。
- 现有 QA/HTTP/MCP 和完整离线回归无新增失败。
- 文档只声明已实现和已验证能力；fake、skipped、live Neo4j、live DashScope、真实文本 provider 状态清楚分离。
