"""Graph retrieval service orchestration for the product assistant layer.

服务串联规划、执行与归一化三个只读环节，是通用检索闭环的唯一产品层入口；
不创建数据库驱动、不读取环境变量、不触发识别或写回。
"""

from __future__ import annotations

from .assistant_models import (
    QuestionUnderstandingResult,
    RetrievalBundle,
    RetrievalPolicy,
)
from .assistant_retrieval_executor import RetrievalExecutor
from .assistant_retrieval_planner import RetrievalPlanner
from .assistant_retrieval_projection import RetrievalBundleBuilder


class GraphRetrievalService:
    """通用检索闭环入口：plan -> execute -> build。"""

    def __init__(
        self,
        facade: object,
        planner: RetrievalPlanner | None = None,
        executor: RetrievalExecutor | None = None,
        bundle_builder: RetrievalBundleBuilder | None = None,
    ):
        self.facade = facade
        self.planner = planner or RetrievalPlanner()
        self.executor = executor or RetrievalExecutor()
        self.bundle_builder = bundle_builder or RetrievalBundleBuilder()

    def retrieve(
        self,
        question_result: QuestionUnderstandingResult,
        policy: RetrievalPolicy | None = None,
    ) -> RetrievalBundle:
        """执行只读通用检索闭环并返回统一 ``RetrievalBundle``。"""

        plan = self.planner.plan(question_result, policy)
        raw_result, source_calls = self.executor.execute(plan, self.facade)
        return self.bundle_builder.build(
            question_result,
            plan,
            raw_result,
            source_calls,
        )
