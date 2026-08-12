"""Factory helpers for constructing the drawing graph tool facade."""

from __future__ import annotations

from .assistant_evidence_freshness import EvidenceFreshnessEvaluator
from .assistant_evidence_sufficiency import EvidenceSufficiencyEvaluator
from .assistant_recognition_budget import RecognitionBudgetEvaluator
from .assistant_recognition_target_planner import RecognitionTargetPlanner
from .assistant_semantic_gap_decision import SemanticGapDecisionService
from .config import ToolFacadeConfig
from .candidate_review import CandidateReviewResult, CandidateReviewService
from .query_port_adapter import QueryServiceReadPortAdapter
from .query_service import QueryService
from .semantic_cache import InMemorySemanticCacheService
from .semantic_image_inputs import SemanticImageInputBuilder
from .semantic_payload_store import InMemorySemanticPayloadStore
from .recognition_run_log import InMemoryRecognitionRunLog
from .relation_repository import (
    RelationRepository,
    RelationRepositoryCandidateRelationPort,
    RelationRepositorySectionMatchPort,
    RelationRepositorySectionMatchQueryPort,
)
from .semantic_client import FakeMultimodalRecognitionClient
from .semantic_neo4j_repository import SemanticNeo4jRepository
from .semantic_repository import InMemorySemanticEvidenceRepository
from .semantic_service import SemanticRecognitionService
from .qwen_semantic_client import QwenMultimodalRecognitionClient, QwenRecognitionConfig
from .section_match_service import SectionMatchService
from .source_fact_query import Neo4jPageSourceFactReader, SourceFactQuery
from .tool_facade import DrawingGraphToolFacade


def create_tool_facade(read_port, config: ToolFacadeConfig | None = None) -> DrawingGraphToolFacade:
    """Create a facade from injected ports without opening database connections."""

    facade_config = config or ToolFacadeConfig.from_env()
    run_log = InMemoryRecognitionRunLog()
    semantic_repository = InMemorySemanticEvidenceRepository()
    payload_store = InMemorySemanticPayloadStore()
    cache_service = InMemorySemanticCacheService()
    input_builder = SemanticImageInputBuilder()
    semantic_service = SemanticRecognitionService(
        client=_recognition_client(facade_config),
        run_log=run_log,
        semantic_repository=semantic_repository,
        input_builder=input_builder,
        cache_service=cache_service,
    )
    return DrawingGraphToolFacade(
        read_port=read_port,
        semantic_service=semantic_service,
        run_log=run_log,
        semantic_repository=semantic_repository,
        payload_store=payload_store,
        section_match_service=SectionMatchService(),
    )


def create_neo4j_tool_facade(
    driver,
    *,
    source_fact_reader=None,
    config: ToolFacadeConfig | None = None,
) -> DrawingGraphToolFacade:
    """Create a facade wired to Neo4j-backed ports without opening a connection."""

    facade_config = config or ToolFacadeConfig.from_env()
    query_service = QueryService(driver)
    page_source_reader = source_fact_reader or SourceFactQuery(Neo4jPageSourceFactReader(driver))
    read_port = QueryServiceReadPortAdapter(query_service, source_fact_reader=page_source_reader)
    run_log = InMemoryRecognitionRunLog()
    semantic_repository = SemanticNeo4jRepository(driver)
    payload_store = InMemorySemanticPayloadStore()
    cache_service = InMemorySemanticCacheService()
    input_builder = SemanticImageInputBuilder()
    semantic_service = SemanticRecognitionService(
        client=_recognition_client(facade_config),
        run_log=run_log,
        semantic_repository=semantic_repository,
        input_builder=input_builder,
        cache_service=cache_service,
    )
    relation_repository = RelationRepository(driver)
    return DrawingGraphToolFacade(
        read_port=read_port,
        semantic_service=semantic_service,
        run_log=run_log,
        semantic_repository=semantic_repository,
        candidate_relation_port=RelationRepositoryCandidateRelationPort(relation_repository),
        candidate_review_service=CandidateReviewService(_SubmittedDecisionReviewClient(), repository=relation_repository),
        payload_store=payload_store,
        section_match_service=SectionMatchService(),
        section_match_write_port=RelationRepositorySectionMatchPort(relation_repository),
        section_match_query_port=RelationRepositorySectionMatchQueryPort(relation_repository),
    )


def create_semantic_gap_decision_service() -> SemanticGapDecisionService:
    """创建纯决策的语义缺口决策服务，不连接数据库、不读取供应商凭据。"""

    return SemanticGapDecisionService(
        sufficiency_evaluator=EvidenceSufficiencyEvaluator(),
        freshness_evaluator=EvidenceFreshnessEvaluator(),
        target_planner=RecognitionTargetPlanner(),
        budget_evaluator=RecognitionBudgetEvaluator(),
    )


__all__ = (
    "create_semantic_gap_decision_service",
    "create_tool_facade",
    "create_neo4j_tool_facade",
)


class _SubmittedDecisionReviewClient:
    """Review client that persists an explicitly submitted facade decision."""

    def review(self, request):
        decision = request.context.get("decision")
        reason = request.context.get("reason")
        accepted_candidate_id = None
        if decision == "accepted":
            accepted_candidate_id = request.candidates[0]["candidate_id"]
        return CandidateReviewResult(
            review_run_id=request.review_run_id,
            relation_spec=request.relation_spec,
            status=decision,
            accepted_candidate_id=accepted_candidate_id,
            reason=reason,
        )


def _recognition_client(config: ToolFacadeConfig):
    """Create the configured recognition provider without broadening facade ports."""

    if config.recognition_provider == "qwen":
        return QwenMultimodalRecognitionClient(
            QwenRecognitionConfig.from_env(
                model=config.qwen_model,
                base_url=config.qwen_base_url,
                timeout_seconds=config.qwen_timeout_seconds,
            )
        )
    return FakeMultimodalRecognitionClient()
