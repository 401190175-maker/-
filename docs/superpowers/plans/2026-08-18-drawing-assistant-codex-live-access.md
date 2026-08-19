# Drawing Assistant Codex Live Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Codex able to ask the drawing graph natural-language questions through the local read-only `drawing-assistant` MCP tool, with live Neo4j and transport verification reported separately.

**Architecture:** Keep Codex outside the business layer: Codex calls the local STDIO MCP server `drawing-assistant`, which exposes only `ask_drawing_assistant`; that server calls `DrawingAssistantService.answer()`, which reads through `DrawingGraphToolFacade`. The fallback path is the read-only CLI `scripts/drawing_assistant.py`; no step writes graph facts or promotes candidates.

**Tech Stack:** Python 3.11+, Neo4j 5.x over Bolt, local Codex `config.toml`, STDIO MCP, PowerShell, `unittest`.

**Spec:** `README.md`, `architecture.md`, `Module.md`, `产品实现层实施门槛表.md`, `.codex/skills/drawing-graph-operator/references/product-test-workflows.md`, `.codex/skills/drawing-graph-operator/references/mcp-boundaries.md`.

## Global Constraints

- Default `write_back=false`; product CLI/MCP must not expose write-back.
- Candidate relations, `CANDIDATE_*`, `matched_candidate`, model observations, and model interpretations are not source facts or formal relations.
- `DrawingAssistantService.answer()` is the product natural-language entry; do not expand `DrawingGraphQAService` into the product assistant.
- MCP is preferred for Codex natural-language testing; CLI is only a transparent fallback.
- Do not print or commit `NEO4J_PASSWORD`, `DASHSCOPE_API_KEY`, tokens, or `.env` contents.
- Skipped integration tests do not prove live Neo4j.
- HTTP TestClient, MCP in-memory tests, and fake runtime do not prove real socket, real STDIO transport, host MCP registration, or live data.

---

### Task 1: Baseline Gate And Version Snapshot

**Files:**
- Read: `README.md`
- Read: `architecture.md`
- Read: `Module.md`
- Read: `产品实现层实施门槛表.md`
- Read: `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md`
- Read: `scripts/skill_preflight.py`

**Interfaces:**
- Consumes: current repository files and process environment.
- Produces: a baseline report with `skill_preflight.py` JSON, git status, and the list of blocked reasons.

- [ ] **Step 1: Run the preflight gate**

```powershell
python scripts\skill_preflight.py
```

Expected before configuration: JSON may report `blocked=true`, with reasons such as `mcp_not_registered`, `neo4j_env_missing`, or `recognition_provider_missing`.

- [ ] **Step 2: Confirm the product assistant files exist**

```powershell
rg --files src scripts tests docs/acceptance .codex/skills/drawing-graph-operator | rg "drawing_assistant|assistant_mcp|assistant_http|PRODUCT_ADAPTER|USER_RUNBOOK|skill_preflight"
```

Expected: the list includes `scripts\serve_drawing_assistant_mcp.py`, `scripts\drawing_assistant.py`, `src\drawing_graph\assistant_mcp_tools.py`, and `src\drawing_graph\drawing_assistant_service.py`.

- [ ] **Step 3: Capture workspace status**

```powershell
git status --short
```

Expected: unrelated or existing user changes are left untouched; if product assistant files are untracked, do not claim the implementation is integrated into a clean version until this is resolved.

### Task 2: Align The Implementation Gate Document

**Files:**
- Modify: `产品实现层实施门槛表.md`
- Test: `tests/test_readme.py`
- Test: `tests/test_module_docs.py`
- Test: `tests/test_assistant_docs.py`
- Test: `tests/test_assistant_adapter_docs.py`

**Interfaces:**
- Consumes: current implementation status from `README.md`, `architecture.md`, `Module.md`, and `PRODUCT_ADAPTER_ACCEPTANCE.md`.
- Produces: a gate table that says product 03/04/05/06/07/08 and CLI/HTTP/MCP adapter are implemented with offline validation, while live Neo4j, live DashScope, real STDIO, real HTTP socket, and host MCP registration remain unverified until executed.

- [ ] **Step 1: Update stale rows in the gate table**

Edit `产品实现层实施门槛表.md` so rows for `03`, `04`, `05`, `06`, `07`, `DrawingAssistantService`, and product CLI/HTTP/MCP no longer say "当前不做" where the current root docs say implemented.

- [ ] **Step 2: Preserve the safety wording**

Keep these exact boundaries in the updated document: `write_back=false`, candidate not formal, skipped not live, adapter only calls `DrawingAssistantService`, and live verification remains separate.

- [ ] **Step 3: Run document contract tests**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_readme tests.test_module_docs tests.test_assistant_docs tests.test_assistant_adapter_docs -v
```

Expected: all listed tests pass. Failures mean the docs and locked contracts disagree.

### Task 3: Load Local Runtime Configuration

**Files:**
- Read: `.env.example`
- Do not read or print: `.env`
- Do not modify: committed source files

**Interfaces:**
- Consumes: user-provided Neo4j credentials and data root in the current PowerShell/Codex process.
- Produces: a process environment where `skill_preflight.py` can see Neo4j, project data, and optional recognition provider readiness.

- [ ] **Step 1: Prepare environment variables in PowerShell**

```powershell
$env:DRAWING_GRAPH_DATA_ROOT = "C:\Users\40119\Desktop\图块图谱构建\data"
$env:DRAWING_GRAPH_PROJECT_SLUG = "road-project"
$env:NEO4J_URI = "bolt://127.0.0.1:7687"
$env:NEO4J_USER = "neo4j"
$env:NEO4J_PASSWORD = "<your-neo4j-password>"
$env:DRAWING_GRAPH_LOG_LEVEL = "INFO"
$env:DRAWING_GRAPH_ASSISTANT_MCP_LOG_LEVEL = "INFO"
```

Expected: no password is printed in terminal history beyond the local command the user typed.

- [ ] **Step 2: Enable recognition only when needed**

```powershell
$env:DRAWING_GRAPH_RECOGNITION_PROVIDER = "qwen"
$env:DASHSCOPE_API_KEY = "<your-dashscope-api-key>"
```

Expected: use this only for questions that need live visual recognition; graph-only natural-language QA can proceed without claiming live DashScope is verified.

- [ ] **Step 3: Re-run the preflight gate**

```powershell
python scripts\skill_preflight.py
```

Expected after Neo4j is running: `available_entries` contains `cli_neo4j`. If MCP has not been registered yet, `mcp_not_registered` can remain.

### Task 4: Validate The Read-Only CLI Against Live Neo4j

**Files:**
- Read: `docs/acceptance/USER_RUNBOOK.md`
- Execute: `scripts/drawing_assistant.py`
- Execute: `scripts/drawing_graph_tool.py`

**Interfaces:**
- Consumes: live Neo4j and imported/enhanced graph data.
- Produces: a known-good page or block ID and one successful product CLI natural-language answer.

- [ ] **Step 1: List drawing sets**

```powershell
python scripts\drawing_graph_tool.py list-drawing-sets --project-id project:road-project --limit 10
```

Expected: JSON response with at least one drawing set. If empty, run import and enrichment before continuing.

- [ ] **Step 2: List pages in a drawing set**

```powershell
python scripts\drawing_graph_tool.py list-pages --drawing-set-id set:road-project:lslq_yhd_2_1 --limit 10
```

Expected: JSON response with page IDs such as `page:road-project:lslq_yhd_2_1:road_24`.

- [ ] **Step 3: Ask a natural-language question through product CLI**

```powershell
python scripts\drawing_assistant.py --question "page:road-project:lslq_yhd_2_1:road_24 这张图有哪些可用证据？" --request-id req:codex-live-cli-001 --page-id page:road-project:lslq_yhd_2_1:road_24 --no-recognition --output json
```

Expected: stdout is one JSON envelope with `ok=true` and an `AnswerPackage` status such as `answered`, `partial`, `clarification_required`, or `unsupported`. This proves CLI plus live Neo4j, not MCP.

### Task 5: Register The Product MCP Server In Codex

**Files:**
- Modify with user approval if outside workspace: `C:\Users\40119\.codex\config.toml`
- Execute: `scripts/serve_drawing_assistant_mcp.py`

**Interfaces:**
- Consumes: Codex config and the local product MCP server script.
- Produces: a Codex host registration for server `drawing-assistant`, exposing tool `ask_drawing_assistant`.

- [ ] **Step 1: Add the MCP server entry**

Add a local STDIO MCP entry for `drawing-assistant` that runs Python from the repository root and starts:

```powershell
python scripts\serve_drawing_assistant_mcp.py
```

Expected config shape: the config text contains `drawing-assistant`, because `scripts\skill_preflight.py` detects registration by searching for that server name.

- [ ] **Step 2: Restart Codex**

Fully exit and reopen Codex so the host reloads `config.toml`.

Expected: a new Codex task can discover the registered MCP server.

- [ ] **Step 3: Re-run preflight after restart**

```powershell
python scripts\skill_preflight.py
```

Expected: `checks.mcp.drawing_assistant_registered=true` and `available_entries` includes `mcp_assistant`.

### Task 6: Verify Real MCP And Live Product QA

**Files:**
- Execute: product MCP server through Codex host
- Test: `tests/test_assistant_mcp_models.py`
- Test: `tests/test_assistant_mcp_tools.py`
- Test: `tests/test_assistant_mcp_runtime.py`
- Test: `tests/test_assistant_mcp_server.py`
- Test: `tests/test_assistant_mcp_cli.py`
- Test: `tests/test_assistant_mcp_boundaries.py`
- Test: `tests/integration/test_product_adapter_live.py`

**Interfaces:**
- Consumes: registered MCP server, live Neo4j test configuration, and at least one known page ID.
- Produces: separated verification statuses for unit/fake, real STDIO/Codex host, and live Neo4j.

- [ ] **Step 1: Run product MCP offline contract tests**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_assistant_mcp_models tests.test_assistant_mcp_tools tests.test_assistant_mcp_runtime tests.test_assistant_mcp_server tests.test_assistant_mcp_cli tests.test_assistant_mcp_boundaries -v
```

Expected: all tests pass. This does not prove live Neo4j.

- [ ] **Step 2: Run live product adapter integration test**

```powershell
$env:PYTHONPATH='src'
$env:NEO4J_TEST_URI = "bolt://127.0.0.1:7687"
$env:NEO4J_TEST_USER = "neo4j"
$env:NEO4J_TEST_PASSWORD = "<test-neo4j-password>"
python -m unittest tests.integration.test_product_adapter_live -v
```

Expected: test runs without being skipped. If skipped, report `live Neo4j 未验证`.

- [ ] **Step 3: Ask through Codex MCP**

In a fresh Codex task, ask: `用 drawing-assistant 的 ask_drawing_assistant 查询 page:road-project:lslq_yhd_2_1:road_24 这张图有哪些可用证据？`

Expected: the answer reports `产品 Skill 路由：MCP 已调用`; if MCP is unavailable but CLI works, report `CLI 降级已调用` and do not claim MCP passed.

### Task 7: Record Final Verification Status

**Files:**
- Modify: `docs/acceptance/PRODUCT_ADAPTER_ACCEPTANCE.md`
- Optionally modify: `README.md`
- Optionally modify: `Module.md`

**Interfaces:**
- Consumes: outputs from Tasks 1-6.
- Produces: a dated verification entry that distinguishes offline/fake, MCP STDIO, Codex host registration, live Neo4j, live DashScope, and skipped tests.

- [ ] **Step 1: Append a dated verification note**

Add a `2026-08-18` note with the exact commands run and their status categories. Do not paste credentials.

- [ ] **Step 2: Run document tests**

```powershell
$env:PYTHONPATH='src'; python -m unittest tests.test_readme tests.test_module_docs tests.test_assistant_adapter_docs -v
```

Expected: all document tests pass.

- [ ] **Step 3: Summarize the final state**

Report these fields exactly:

```text
产品 Skill 路由：未运行 / MCP 已调用 / CLI 降级已调用 / HTTP 已调用
单元/合同测试：未运行 / 单元测试通过 / 失败
MCP in-memory：未运行 / 单元测试通过 / 失败
STDIO smoke：未运行 / 通过 / 失败
HTTP socket：未运行 / 通过 / 失败
live Neo4j：未运行 / live Neo4j 已验证 / live Neo4j 未验证 / 集成测试跳过
live DashScope 或真实文本 provider：未运行 / 已验证 / 未验证
```
