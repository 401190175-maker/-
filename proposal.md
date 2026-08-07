# 当前规划索引

本根目录规划索引用于保持项目级文档测试和历史规划入口可读；当前正在执行的具体方案以 `changes/tool-facade/proposal.md`、`changes/tool-facade/design.md` 和 `changes/tool-facade/tasks.md` 为准。

规划边界：本文件不声称代码已实现全部目标能力。当前已实现的事实以 `architecture.md`、`README.md`、`Module.md` 和 `src/` 为准。

关系目标包括 `DrawingPage -[:USES_BASIC_INFO]-> DrawingBasicInfo`、`BlockCaption -[:CANDIDATE_CAPTION_OF]-> DrawingBlock`、`DrawingBlock -[:CANDIDATE_HAS_SECTION_MARK]-> CrossSection`。候选关系需要显式 AI 复核，并通过 `review_run_id` 记录复核运行。旧的 `DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 不是目标关系，不再作为目标关系。
