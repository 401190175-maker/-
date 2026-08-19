# 产品级 Adapter 验收记录（PRODUCT_ADAPTER_ACCEPTANCE）

## 范围

本记录覆盖 `changes/产品实现层/adapter与产品级验收/tasks.md` 的 Task 1-20，交付产品级只读
HTTP/MCP adapter 与产品 CLI/HTTP/MCP 三入口验收，同时保持旧 QA CLI/HTTP/MCP 兼容。

新增源码（`src/drawing_graph/`）：

- `assistant_adapter_serialization.py`：产品 adapter 共享 envelope、JSON-safe 投影、错误类别与脱敏。
- `assistant_http_models.py`：产品 HTTP request/response/health DTO，严格字段白名单。
- `assistant_http_runtime.py`：产品 HTTP driver/facade/service 装配与幂等关闭。
- `assistant_http.py`：产品 HTTP FastAPI app、路由、并发/超时/错误映射。
- `assistant_mcp_models.py`：产品 MCP 输入输出模型，转换为只读 `AssistantRequest`。
- `assistant_mcp_tools.py`：产品 MCP tool handler，一次 `answer()` 生成同源 structuredContent/TextContent。
- `assistant_mcp_runtime.py`：产品 MCP runtime 装配与生命周期。
- `assistant_mcp_server.py`：产品 MCP server、工具 Schema、只读 annotations。

新增脚本（`scripts/`）：`serve_drawing_assistant.py`、`serve_drawing_assistant_mcp.py`。

新增测试（`tests/`）：`test_assistant_adapter_serialization.py`、`test_assistant_http_models.py`、
`test_assistant_http_runtime.py`、`test_assistant_http.py`、`test_assistant_http_cli.py`、
`test_assistant_http_boundaries.py`、`test_assistant_mcp_models.py`、`test_assistant_mcp_tools.py`、
`test_assistant_mcp_runtime.py`、`test_assistant_mcp_server.py`、`test_assistant_mcp_cli.py`、
`test_assistant_mcp_boundaries.py`、`test_product_adapter_e2e.py`、`test_product_adapter_qa_compatibility.py`、
`test_assistant_adapter_docs.py`。

可选修改：`src/drawing_graph/config.py`（新增 `AssistantHttpConfig`、`AssistantMcpConfig`）、
`tests/test_drawing_assistant_e2e.py`（补充 CLI JSON 保留 warnings/unsupported_parts 的断言）。

## 验证方式

所有命令均在仓库根目录执行，先设置 `$env:PYTHONPATH='src'`，属于 unit/fake/offline 验证；
不连接真实 Neo4j，也不调用真实云模型或真实文本 provider。

### 单元与合同

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_adapter_serialization tests.test_assistant_http_models tests.test_assistant_mcp_models -v
```

### HTTP adapter

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_http_models tests.test_assistant_http_runtime tests.test_assistant_http tests.test_assistant_http_cli tests.test_assistant_http_boundaries -v
```

### MCP adapter

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_mcp_models tests.test_assistant_mcp_tools tests.test_assistant_mcp_runtime tests.test_assistant_mcp_server tests.test_assistant_mcp_cli tests.test_assistant_mcp_boundaries -v
```

### 产品三入口 fake E2E

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_product_adapter_e2e tests.test_drawing_assistant_e2e tests.test_drawing_assistant_cli -v
```

### 旧 QA 兼容回归

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_product_adapter_qa_compatibility tests.test_qa_service tests.test_qa_http tests.test_qa_mcp_tools -v
```

### 文档契约

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_adapter_docs -v
```

## 验证结果快照（2026-08-17）

- 产品 adapter 专项回归（Task 17，覆盖序列化/HTTP 模型与 app/HTTP CLI/HTTP 边界/MCP 模型/MCP tools/runtime/server/CLI/边界/三入口 E2E/旧 QA 兼容）：`Ran 127 tests ... OK`（0 失败、0 错误、0 跳过）。
- 文档契约回归（Task 16）：`tests.test_readme tests.test_module_docs tests.test_assistant_docs tests.test_assistant_adapter_docs` 共 `Ran 42 tests ... OK`。
- 全仓离线回归（Task 18）：`python -m unittest discover tests` 为 `Ran 2717 tests`，`OK (skipped=5)`；5 项 skipped 均为 `tests/integration/` 因缺少 `NEO4J_TEST_URI`、`NEO4J_TEST_USER`、`NEO4J_TEST_PASSWORD` 而跳过（含新增的 `test_product_adapter_live.py`）。

以上全部属于 unit/fake/offline、进程内 ASGI（TestClient）与 MCP in-memory client session 验证；未执行真实 HTTP socket、MCP STDIO 子进程、live Neo4j、live DashScope 或真实文本 provider 验证。

## 验证状态分层

| 验证层 | 状态 |
|---|---|
| unit/fake/offline（产品序列化/HTTP/MCP/E2E/旧 QA 兼容） | 已执行（离线/fake） |
| HTTP TestClient（进程内 ASGI，非真实 socket） | 已执行 |
| HTTP 真实 socket（Uvicorn 监听） | 未验证 |
| MCP in-memory client session | 已执行 |
| MCP STDIO（真实 stdio 子进程 transport） | 未验证 |
| 旧 QA 兼容回归 | 已执行 |
| live Neo4j | 未验证 |
| live DashScope / 真实文本 provider | 未验证 |
| 真实 MCP 宿主注册 | 未验证 |

**skipped 不等于 live Neo4j 通过。** 未配置 `NEO4J_TEST_URI` / `NEO4J_TEST_USER` /
`NEO4J_TEST_PASSWORD` 时，`tests/integration/` 相关测试按设计跳过，跳过不代表 live 验证通过。

## live 验证状态（Task 19 / Task 20）

- **live Neo4j（Task 19）**：新增 `tests/integration/test_product_adapter_live.py`。未配置
  `NEO4J_TEST_URI`/`NEO4J_TEST_USER`/`NEO4J_TEST_PASSWORD` 时按设计 skipped（`Ran 1 test ... OK (skipped=1)`），
  跳过不等于 live Neo4j 通过。配置 disposable 测试库后，产品 MCP runtime 可经
  `DrawingAssistantService.answer() -> DrawingGraphToolFacade` 完成只读问答；测试使用
  `product-adapter-live-<uuid>` 前缀创建并清理一次性数据，不调用 DashScope、不写业务事实。
  本轮未配置 live 环境，**live Neo4j 未验证**。
- **live DashScope / 真实文本 provider（Task 20）**：需要用户明确授权并配置
  `DASHSCOPE_API_KEY` 或真实文本 provider 环境；本轮未授权、未配置，**未验证**。
  provider 输出即使执行，也只能成为 observation/interpretation/candidate evidence，
  不能成为 source_fact/formal。
- **真实 MCP 宿主注册**：未验证。

## live 验证增量（2026-08-18）

本轮按 Codex 接入最短路线补充执行以下验证；所有命令均未输出 Neo4j 密码或
DashScope key，产品问答仍固定只读，不提供写回入口。

- **前置门**：加载本机 `.env` 后运行 `python scripts\skill_preflight.py`，
  结果为 `available_entries=["mcp_assistant","cli_neo4j","recognition_qwen"]`，
  `blocked=false`，`blocked_reasons=[]`。这只证明配置文本、Neo4j Bolt 端口和
  recognition provider 前置条件可见，不等于当前 Codex 会话已经加载新 MCP。
- **产品 CLI + live Neo4j**：运行
  `python scripts\drawing_assistant.py --question "这张图主要讲什么？" --request-id req:codex-live-cli-003 --page-id page:road-project:lslq_yhd_2_1:road_24 --no-recognition --output json`，
  返回 `ok=true`、`status="answered"`、`question_type="page_summary"`。该结果证明
  产品 CLI 可通过真实 Neo4j 读取已导入图谱；`--no-recognition` 表示本次未调用 DashScope。
- **产品 MCP 单元/合同回归**：运行
  `python -m unittest tests.test_assistant_mcp_models tests.test_assistant_mcp_tools tests.test_assistant_mcp_runtime tests.test_assistant_mcp_server tests.test_assistant_mcp_cli tests.test_assistant_mcp_boundaries -v`，
  `Ran 50 tests ... OK`。
- **live Neo4j 产品集成**：首次运行因 `.env` 中 `NEO4J_TEST_PASSWORD` 仍为占位符而
  出现 Neo4j authentication failure；本轮未修改 `.env`，只在命令进程内临时将
  `NEO4J_TEST_*` 映射为当前可用的 `NEO4J_*` 后复跑
  `python -m unittest tests.integration.test_product_adapter_live -v`，结果为
  `Ran 1 test ... OK`。同时修复了测试生命周期问题：live 测试中的 MCP runtime
  不再复用并关闭测试类共享 driver，而是创建并关闭自己的 driver。
- **真实 STDIO transport smoke**：使用 `mcp.client.stdio.stdio_client` 启动真实子进程
  `python scripts/serve_drawing_assistant_mcp.py`，完成 initialize、tools/list 和一次
  `ask_drawing_assistant` 调用，输出 `TOOLS ['ask_drawing_assistant']`、
  `IS_ERROR False`、`STATUS answered`、`QUESTION_TYPE page_summary`。
- **Codex 宿主注册状态**：已向本机 `C:\Users\40119\.codex\config.toml` 追加
  `drawing-assistant` server 配置；当前 Codex 会话用工具发现仍找不到
  `ask_drawing_assistant`，因此真实 Codex 宿主调用仍需完全重启 Codex 后验证。

验证状态更新：

| 验证层 | 2026-08-18 状态 |
|---|---|
| unit/fake/offline（产品 MCP 合同） | 已执行，50 项 OK |
| HTTP TestClient（进程内 ASGI，非真实 socket） | 本轮未重跑 |
| HTTP 真实 socket（Uvicorn 监听） | 本轮未验证 |
| MCP in-memory client session + live Neo4j | 已执行，1 项 OK |
| MCP STDIO（真实 stdio 子进程 transport） | 已执行，smoke 通过 |
| 产品 CLI + live Neo4j | 已执行，`answered/page_summary` |
| live Neo4j | 已验证产品只读读取链路 |
| live DashScope / 真实文本 provider | 本轮未调用，未验证 |
| 真实 Codex 宿主注册 | 配置已追加；当前会话未加载，需重启后验证 |

## live 验证增量（2026-08-19）：MCP 第三步修复回放

### 背景

第三步验收目标：`allow_recognition=true` 且 `write_back=false` 下，验证
`qwen3-vl-plus` 视觉链路能被问答系统按需调用，同时确认不持久化语义证据。
本轮回放修复了 live 复验中暴露的三个链路问题，并重新完成 MCP/CLI 复验。

### 修复清单

1. **执行层默认截止策略自相矛盾**（`src/drawing_graph/recognition_execution.py`）：
   `DRAWING_GRAPH_QWEN_TIMEOUT_SECONDS=60` 与
   `DRAWING_GRAPH_RECOGNITION_DEADLINE_SECONDS=60` 时，单次调用超时被 clamp 为
   `min(deadline, 60)=60`，重试门要求 `timeout + 0.1s 预留 <= 剩余截止时间`
   （60.1 > 60），导致每次都在调用 Qwen 前立即 `deadline_exceeded`。修复：单次
   调用超时 clamp 为 `min(60, max(0.1, deadline - 1.0))`，默认 60/60 配置可发起
   一次真实调用，重试仍受 deadline 门控。回归测试：`tests/test_recognition_execution.py`
   新增“60/60 默认配置必须真正调用 provider”，并把“过小截止时间仍拒绝”用例改为
   0.05s；`tests/test_multimodal_recognition_contracts.py` 同步。
2. **block observations 支撑链缺失**（`src/drawing_graph/semantic_service.py` +
   `src/drawing_graph/recognition_prompting.py`）：`block_semantic_identification`
   输出契约允许 `observations`，但 04 投影只生成 interpretation、丢弃 observations；
   05 的 SEMANTIC_MEANING claim 门要求 `supported_by_observation_ids` 引用同次识别
   的 TextObservation，导致解释永远无法成为 claim。修复：block 分支把 observations
   投影为 TextObservation（唯一 ID 带索引），并确定性把同 run 同目标 observation ID
   写入 `BlockInterpretation.supported_by_observation_ids`；prompt 指示模型把图块内
   可见文字/标注输出为 observations。回归测试：`tests/test_semantic_service.py`、
   `tests/test_recognition_prompting.py`。
3. **answerability scope 澄清门误判**（`src/drawing_graph/assistant_answerability.py`）：
   supported 评估的 reason_codes 混入被拒证据的 `scope_conflict`/`evidence_kind_mismatch`
   噪音时，answerability 仍判 `clarification_required`，把已可答答案压成 partial。
   修复：scope 澄清门只在评估不可答（非 answerable）时触发。回归测试：
   `tests/test_assistant_answerability.py`。

### 验证（2026-08-19）

- 离线：相关回归 364 项 OK；全量 `python -m unittest discover tests` 为
  `Ran 2754 tests`，`OK (skipped=5)`（5 项 live Neo4j 集成按设计跳过）。
- live（本机 `.env` 已加载、网络放行、全程 `write_back=false`）：
  - 04 facade dry-run：`qwen3-vl-plus` 返回 `succeeded`，1 条 `BlockInterpretation`
    + 15~16 条 TextObservation，解释的 `supported_by_observation_ids` 全部链接到
    同 run observation。
  - 产品 MCP STDIO smoke（与 `~/.codex/config.toml` 注册命令相同）：
    `ask_drawing_assistant` 返回 `status=answered`，claims=2
    （`identity_and_location`/source_fact + `semantic_meaning`/semantic_interpretation，
    均带 citation），`unsupported_parts=[]`、
    `recognition_run_ids=["run:temp:9ba25893-..."]`。
  - 产品 CLI 同问题：模型遵守契约时同样返回 semantic_meaning claim；模型偶发不遵守
    输出契约时执行层按 `contract_failed` 如实降级为 partial，不伪造成功。
  - 未持久化：按 `run:temp:9ba25893-...` 与按 block 查 `list-interpretations` 均
    `NOT_FOUND`，识别结果 `persisted=false`。
- 诚实边界：live DashScope 调用需要网络放行；本记录不把单次 live 成功扩展为黄金集
  或全量模型稳定性结论；LLM 输出非确定性由执行层 fail-closed 处理。

### 验证状态分层（2026-08-19）

| 验证层 | 2026-08-19 状态 |
|---|---|
| unit/fake/offline 全量回归 | 已执行，2754 项 OK（skipped=5） |
| 产品 CLI + live Neo4j + live DashScope（dry-run） | 已执行，模型遵守契约时 answered |
| MCP STDIO（真实 stdio 子进程 transport）+ live DashScope（dry-run） | 已执行，answered |
| 未持久化核验（list-interpretations） | 已执行，NOT_FOUND |
| live Neo4j 语义写入 | 未验证（本轮不写回） |
| 真实 Codex 宿主注册 | 未验证（工具发现仍未挂载到会话，需完全重启后验证） |

## 边界确认

- 产品 HTTP/MCP adapter 只调用 `DrawingAssistantService.answer()`，不直接访问 Neo4j driver、
  repository、Cypher、Qwen provider 或离线增强规则；runtime 仅负责装配 driver -> facade -> service。
- 默认 `write_back=false`；产品 HTTP/MCP 首版不提供任何写回路径。HTTP 检测到 `write_back=true`
  或 `allow_write_back=true` 返回 403 `read_only_violation`；MCP 输入模型拒绝这些字段。
- `allow_recognition=true` 只表示允许按需识别，不等于写回授权；04 识别固定 `write_back=false`。
- `candidate_relation`、`matched_candidate`、`CANDIDATE_*` 保持候选语义，不渲染成正式事实。
- HTTP 并发上限、请求超时、请求体限制、认证、参数错误、service 错误与未预期异常均映射为稳定
  脱敏 error envelope。
- MCP structuredContent 来自 `AnswerPackage` JSON-safe 投影；TextContent 只概述状态与数量，不新增事实；
  stdout 只承载协议帧，日志与错误走 stderr。
- 旧 QA CLI/HTTP/MCP 路由、工具名、输入 schema、输出 envelope 与只读语义保持不变，且不反向依赖产品 adapter。
- 未实现：Web UI、远程 MCP、Streamable HTTP MCP、OAuth/RBAC、多 worker 生产部署、HTTP/MCP 写回、
  产品级外部反馈入口。
