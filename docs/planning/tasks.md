# 当前任务索引

当前任务实施入口为 `changes/tool-facade/tasks.md`。本文档只保留项目级边界，避免旧测试误判规划文件缺失。

规划边界：本文件不声称代码已实现所有目标；任务完成状态以 `changes/tool-facade/tasks.md` 的验收记录、当前测试输出和实际源码为准。

任务涉及的关键关系与复核边界包括 `USES_BASIC_INFO`、`CANDIDATE_CAPTION_OF`、`CANDIDATE_HAS_SECTION_MARK`、AI 复核、`review_run_id`。`DrawingBlock -[:HAS_BASIC_INFO]-> DrawingBasicInfo` 不是目标关系，不再作为目标关系。
