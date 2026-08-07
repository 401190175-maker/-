# 当前设计索引

本根目录设计索引用于指向当前有效设计：`changes/tool-facade/design.md`。详细实现边界、依赖方向和任务拆分以该文件和 `Module.md` 为准。

规划边界：不声称代码已实现 HTTP API、Agent Skill、MCP Tool adapter、完整语义证据层或全量自动语义扫描。当前代码已实现的范围需按 `src/` 和测试结果核对。

设计中的受控关系包括 `USES_BASIC_INFO`、`CANDIDATE_CAPTION_OF` 和 `CANDIDATE_HAS_SECTION_MARK`。候选关系 AI 复核是显式流程，复核证据通过 `review_run_id` 追踪。`DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 只可作为历史实现或迁移兼容语境出现，不是目标关系。
