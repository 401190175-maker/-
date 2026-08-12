# Qwen Recognition Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an offline-tested Qwen multimodal recognition client for the existing semantic recognition protocol.

**Architecture:** Keep recognition behind `MultimodalRecognitionClient`. Add a Qwen client that speaks DashScope's OpenAI-compatible chat completions endpoint, validates structured JSON output, and maps provider failures to `ToolModelError("RECOGNITION_FAILED", ...)`. Production assembly may select Qwen only when explicitly configured; default tests and in-memory facade keep the fake client.

**Tech Stack:** Python 3.11, `unittest`, `httpx`, existing drawing graph DTOs.

## Global Constraints

- No standalone OCR engine.
- No live API calls in offline tests.
- Do not store or print `DASHSCOPE_API_KEY`.
- Default semantic recognition remains dry-run unless `write_back=true` is explicitly passed.
- Candidate and semantic evidence outputs remain separate from formal source facts.

---

### Task 1: Qwen Client Offline Contract

**Files:**
- Create: `src/drawing_graph/qwen_semantic_client.py`
- Create: `tests/test_qwen_semantic_client.py`

**Interfaces:**
- Consumes: `RecognitionClientRequest`, `RecognitionClientResult`, `BBox`, `ToolModelError`
- Produces: `QwenRecognitionConfig`, `QwenMultimodalRecognitionClient.recognize(request)`

- [x] **Step 1: Write failing tests**

Add tests that verify Qwen request construction, successful structured response parsing, invalid JSON handling, provider non-200 handling, and missing API key validation using `httpx.MockTransport`.

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_qwen_semantic_client -v`
Expected: import failure because `drawing_graph.qwen_semantic_client` does not exist.

- [x] **Step 3: Implement minimal Qwen client**

Create `QwenRecognitionConfig` and `QwenMultimodalRecognitionClient`, using injected `httpx.Client` for offline tests and validating response JSON into the existing recognition result DTO.

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_qwen_semantic_client -v`
Expected: all Qwen client offline tests pass.

### Task 2: Factory Configuration

**Files:**
- Modify: `src/drawing_graph/config.py`
- Modify: `src/drawing_graph/tool_factory.py`
- Modify: `tests/test_tool_factory.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `ToolFacadeConfig.from_mapping(values)`
- Produces: `ToolFacadeConfig.recognition_provider`, `qwen_model`, `qwen_base_url`, `qwen_timeout_seconds`

- [x] **Step 1: Write failing tests**

Extend factory/config tests so `recognition_provider="qwen"` wires a `QwenMultimodalRecognitionClient` when `DASHSCOPE_API_KEY` exists, while defaults keep `FakeMultimodalRecognitionClient`.

- [x] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_tool_factory -v`
Expected: config fields or Qwen client import are missing.

- [x] **Step 3: Implement minimal config and factory wiring**

Add non-secret Qwen provider fields to `ToolFacadeConfig`, keep API key outside config, and let the production Neo4j facade factory read `DASHSCOPE_API_KEY` only when Qwen is selected.

- [x] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_tool_factory -v`
Expected: all factory tests pass.

### Task 3: Focused Regression

**Files:**
- Existing semantic service/client/factory tests

- [x] **Step 1: Run focused regression**

Run: `python -m unittest tests.test_semantic_client tests.test_qwen_semantic_client tests.test_tool_factory -v`
Expected: all focused offline tests pass.

- [x] **Step 2: Report verification boundary**

State that Qwen client was offline-tested only; live DashScope and live Neo4j are not claimed.
