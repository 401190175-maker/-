"""QA orchestration service composing DrawingGraphToolFacade results.

``DrawingGraphQAService`` is an orchestration layer outside the facade: it
validates requests, routes question types, aggregates facade DTOs into
structured answers, and never touches Neo4j, Cypher, repositories, or write
paths directly.
"""

from __future__ import annotations

from typing import Any, Callable

from .qa_models import (
    QAAnswer,
    QAAnswerStatus,
    QAError,
    QAErrorCode,
    QARequest,
    QAScope,
    QuestionType,
)
from .qa_models import AnswerFact, EvidenceRef
from .tool_models import ToolModelError


class DrawingGraphQAService:
    """Route QA requests to facade-backed aggregation handlers."""

    def __init__(self, facade: Any):
        if facade is None:
            raise QAError(QAErrorCode.FACADE_UNAVAILABLE, "a DrawingGraphToolFacade must be injected")
        self.facade = facade

    def ask(self, request: QARequest) -> QAAnswer:
        """Answer one QA request (read-only in phase one)."""

        if request.write_back:
            raise QAError(
                QAErrorCode.WRITE_BACK_FORBIDDEN,
                "phase one QA is read-only; write_back must be false",
            )
        self._validate_scope(request.question_type, request.scope)
        handlers = {
            QuestionType.PAGE_SUMMARY: self._answer_page_summary,
            QuestionType.BLOCK_RELATIONS: self._answer_block_relations,
            QuestionType.CANDIDATE_RELATIONS: self._answer_candidate_relations,
            QuestionType.SECTION_MATCHES: self._answer_section_matches,
            QuestionType.TABLE_CAPTION_STATUS: self._answer_table_caption_status,
            QuestionType.DIAGNOSTIC_STATUS: self._answer_diagnostic_status,
            QuestionType.UNKNOWN_OR_UNSUPPORTED: self._unsupported,
        }
        handler = handlers[request.question_type]
        return handler(request)

    def _validate_scope(self, question_type: QuestionType, scope: QAScope) -> None:
        if question_type is QuestionType.PAGE_SUMMARY:
            _require_scope_id(scope.page_id, "page_id", question_type)
            return
        if question_type is QuestionType.BLOCK_RELATIONS:
            _require_scope_id(scope.block_id, "block_id", question_type)
            return
        if question_type is QuestionType.CANDIDATE_RELATIONS:
            if scope.page_id is None and scope.block_id is None:
                _require_scope_id(scope.page_id, "page_id or block_id", question_type)
            return
        if question_type is QuestionType.SECTION_MATCHES:
            if scope.cross_section_id is None and scope.page_id is None:
                if scope.block_id is not None:
                    raise QAError(
                        QAErrorCode.UNSUPPORTED_SCOPE,
                        "section_matches does not support block_id scope",
                    )
                _require_scope_id(scope.cross_section_id, "cross_section_id or page_id", question_type)
            return
        if question_type is QuestionType.TABLE_CAPTION_STATUS:
            supported = (scope.page_id, scope.table_id, scope.table_caption_id)
            if not any(value is not None for value in supported):
                if scope.block_id is not None:
                    raise QAError(
                        QAErrorCode.UNSUPPORTED_SCOPE,
                        "table_caption_status does not support block_id scope",
                    )
                _require_scope_id(scope.page_id, "page_id, table_id, or table_caption_id", question_type)
            return
        if question_type is QuestionType.DIAGNOSTIC_STATUS:
            if scope.page_id is None and scope.block_id is None:
                _require_scope_id(scope.page_id, "page_id or block_id", question_type)
            return
        if question_type is QuestionType.UNKNOWN_OR_UNSUPPORTED:
            return
        raise QAError(QAErrorCode.UNSUPPORTED_QUESTION, f"unsupported question type: {question_type.value}")

    def _answer_page_summary(self, request: QARequest) -> QAAnswer:
        source_calls = ["get_page_source_facts"]
        try:
            page = self.facade.get_page_source_facts(request.scope.page_id)
        except ToolModelError as error:
            if error.category == "NOT_FOUND":
                return QAAnswer(
                    question_type=request.question_type,
                    scope=request.scope,
                    status=QAAnswerStatus.NOT_FOUND,
                    summary="页面不存在或来源事实不可用",
                    source_calls=tuple(source_calls),
                )
            raise _translate_facade_error(error) from error
        if page is None:
            return QAAnswer(
                question_type=request.question_type,
                scope=request.scope,
                status=QAAnswerStatus.NOT_FOUND,
                summary="页面不存在或来源事实不可用",
                source_calls=tuple(source_calls),
            )

        facts = [
            AnswerFact(
                fact_kind="source_fact",
                label="页面图片",
                status="confirmed",
                ids={"page_id": page.page_id},
                value=page.image_path,
                evidence=(
                    EvidenceRef(page_id=page.page_id, image_path=page.image_path),
                ),
            ),
            AnswerFact(
                fact_kind="source_fact",
                label="页面元素",
                status="confirmed",
                ids={"page_id": page.page_id},
                value=len(page.elements),
                evidence=tuple(
                    EvidenceRef(
                        page_id=page.page_id,
                        element_id=element.element_id,
                        image_path=page.image_path,
                        bbox=_bbox_dict(element.bbox),
                        normalized_bbox=_bbox_dict(element.normalized_bbox),
                    )
                    for element in page.elements
                ),
            ),
            AnswerFact(
                fact_kind="source_fact",
                label="元素类型统计",
                status="confirmed",
                ids={"page_id": page.page_id},
                value=_element_type_stats(page.elements),
            ),
        ]
        warnings: list[str] = []
        status = QAAnswerStatus.ANSWERED

        if request.include_semantics:
            observations, observation_warnings, observation_degraded = _optional_facade_call(
                lambda: self.facade.list_text_observations(page_id=request.scope.page_id)
            )
            source_calls.append("list_text_observations")
            warnings.extend(observation_warnings)
            if observation_degraded:
                status = QAAnswerStatus.PARTIAL
            for observation in observations or ():
                facts.append(_observation_fact(observation, page.image_path))

            interpretations, interpretation_warnings, interpretation_degraded = _optional_facade_call(
                lambda: self.facade.list_interpretations(page_id=request.scope.page_id)
            )
            source_calls.append("list_interpretations")
            warnings.extend(interpretation_warnings)
            if interpretation_degraded:
                status = QAAnswerStatus.PARTIAL
            for interpretation in interpretations or ():
                facts.append(_interpretation_fact(interpretation))

        summary = f"页面 {page.page_id} 来源事实可用，共 {len(page.elements)} 个元素"
        return QAAnswer(
            question_type=request.question_type,
            scope=request.scope,
            status=status,
            summary=summary,
            facts=tuple(facts),
            warnings=tuple(warnings),
            unsupported_parts=(),
            source_calls=tuple(source_calls),
        )

    def _answer_block_relations(self, request: QARequest) -> QAAnswer:
        source_calls: list[str] = []
        try:
            trace = self.facade.get_block_trace(request.scope.block_id)
        except ToolModelError as error:
            if error.category == "NOT_FOUND":
                return QAAnswer(
                    question_type=request.question_type,
                    scope=request.scope,
                    status=QAAnswerStatus.NOT_FOUND,
                    summary="图块不存在或追溯信息不可用",
                    source_calls=("get_block_trace",),
                )
            raise _translate_facade_error(error) from error
        source_calls.append("get_block_trace")
        try:
            relations = self.facade.get_block_relations(request.scope.block_id)
        except ToolModelError as error:
            if error.category == "NOT_FOUND":
                return QAAnswer(
                    question_type=request.question_type,
                    scope=request.scope,
                    status=QAAnswerStatus.NOT_FOUND,
                    summary="图块关系信息不可用",
                    source_calls=tuple(source_calls),
                )
            raise _translate_facade_error(error) from error
        source_calls.append("get_block_relations")
        if trace is None or relations is None:
            return QAAnswer(
                question_type=request.question_type,
                scope=request.scope,
                status=QAAnswerStatus.NOT_FOUND,
                summary="图块不存在或关系信息不可用",
                source_calls=tuple(source_calls),
            )

        facts = [_block_trace_fact(trace)]
        facts.extend((
            _derived_group_fact(
                block_id=request.scope.block_id,
                page_id=trace.page_id,
                label="标题关系",
                relation_type="HAS_CAPTION",
                ids_tuple=relations.caption_ids,
            ),
            _derived_group_fact(
                block_id=request.scope.block_id,
                page_id=trace.page_id,
                label="基础信息关系",
                relation_type="USES_BASIC_INFO",
                ids_tuple=relations.basic_info_ids,
            ),
            _derived_group_fact(
                block_id=request.scope.block_id,
                page_id=trace.page_id,
                label="注释关系",
                relation_type="HAS_ANNOTATION",
                ids_tuple=relations.annotation_ids,
            ),
            _derived_group_fact(
                block_id=request.scope.block_id,
                page_id=trace.page_id,
                label="断面标记关系",
                relation_type="HAS_SECTION_MARK",
                ids_tuple=relations.section_mark_ids,
            ),
        ))
        if relations.candidate_caption_ids:
            facts.append(
                _candidate_group_fact(
                    block_id=request.scope.block_id,
                    page_id=trace.page_id,
                    label="候选标题关系",
                    relation_type="candidate_caption_of",
                    ids_tuple=relations.candidate_caption_ids,
                )
            )
        if relations.candidate_section_mark_ids:
            facts.append(
                _candidate_group_fact(
                    block_id=request.scope.block_id,
                    page_id=trace.page_id,
                    label="候选断面标记关系",
                    relation_type="candidate_section_mark",
                    ids_tuple=relations.candidate_section_mark_ids,
                )
            )

        warnings: list[str] = []
        status = QAAnswerStatus.ANSWERED
        if request.include_candidates:
            candidates, candidate_warnings, candidate_degraded = _optional_facade_call(
                lambda: self.facade.list_candidate_relations(block_id=request.scope.block_id)
            )
            source_calls.append("list_candidate_relations")
            warnings.extend(candidate_warnings)
            if candidate_degraded:
                status = QAAnswerStatus.PARTIAL
            for candidate in candidates or ():
                facts.append(_candidate_fact(candidate))

        summary = f"图块 {request.scope.block_id} 关系状态：{relations.relation_status}"
        if relations.basic_info_status:
            summary += f"；基础信息：{relations.basic_info_status}"
        return QAAnswer(
            question_type=request.question_type,
            scope=request.scope,
            status=status,
            summary=summary,
            facts=tuple(facts),
            warnings=tuple(warnings),
            unsupported_parts=(),
            source_calls=tuple(source_calls),
        )

    def _answer_candidate_relations(self, request: QARequest) -> QAAnswer:
        source_calls: list[str] = []
        warnings: list[str] = []
        status = QAAnswerStatus.ANSWERED
        facts: list[AnswerFact] = []

        candidates, candidate_warnings, candidate_degraded = _optional_facade_call(
            lambda: self.facade.list_candidate_relations(
                page_id=request.scope.page_id,
                block_id=request.scope.block_id,
            )
        )
        source_calls.append("list_candidate_relations")
        warnings.extend(candidate_warnings)
        if candidate_degraded:
            status = QAAnswerStatus.PARTIAL
        for candidate in candidates or ():
            facts.append(_candidate_fact(candidate))

        if request.scope.page_id is not None:
            section_matches, section_warnings, section_degraded = _optional_facade_call(
                lambda: self.facade.list_section_matches(
                    page_id=request.scope.page_id,
                    statuses=("candidate",),
                )
            )
            source_calls.append("list_section_matches")
            warnings.extend(section_warnings)
            if section_degraded:
                status = QAAnswerStatus.PARTIAL
            for match in section_matches or ():
                facts.append(_section_match_fact(match))

        candidate_count = sum(1 for fact in facts if fact.fact_kind == "candidate_relation")
        summary = f"找到 {candidate_count} 条候选关系" if candidate_count else "没有找到候选关系"
        return QAAnswer(
            question_type=request.question_type,
            scope=request.scope,
            status=status,
            summary=summary,
            facts=tuple(facts),
            warnings=tuple(warnings),
            unsupported_parts=(),
            source_calls=tuple(source_calls),
        )

    def _answer_section_matches(self, request: QARequest) -> QAAnswer:
        source_calls: list[str] = []
        warnings: list[str] = []
        facts: list[AnswerFact] = []

        try:
            matches = self.facade.list_section_matches(
                cross_section_id=request.scope.cross_section_id,
                page_id=request.scope.page_id,
            )
        except ToolModelError as error:
            if error.category == "NOT_FOUND":
                matches = ()
            elif error.category == "SEMANTIC_EVIDENCE_UNAVAILABLE":
                return QAAnswer(
                    question_type=request.question_type,
                    scope=request.scope,
                    status=QAAnswerStatus.PARTIAL,
                    summary="断面匹配查询不可用",
                    warnings=("断面匹配查询不可用，已降级",),
                    source_calls=("list_section_matches",),
                )
            else:
                raise _translate_facade_error(error) from error
        source_calls.append("list_section_matches")

        if matches:
            for match in matches:
                facts.append(_section_match_fact(match))
            return QAAnswer(
                question_type=request.question_type,
                scope=request.scope,
                status=QAAnswerStatus.ANSWERED,
                summary=_section_matches_summary(matches),
                facts=tuple(facts),
                source_calls=tuple(source_calls),
            )

        if request.scope.cross_section_id is not None:
            try:
                decision = self.facade.match_section_caption(
                    request.scope.cross_section_id,
                    page_id=request.scope.page_id,
                    write_back=False,
                )
            except ToolModelError as error:
                if error.category == "NOT_FOUND":
                    return QAAnswer(
                        question_type=request.question_type,
                        scope=request.scope,
                        status=QAAnswerStatus.NOT_FOUND,
                        summary="断面或标题观测不存在，无法判断匹配",
                        source_calls=tuple(source_calls),
                    )
                if error.category == "SEMANTIC_EVIDENCE_UNAVAILABLE":
                    return QAAnswer(
                        question_type=request.question_type,
                        scope=request.scope,
                        status=QAAnswerStatus.PARTIAL,
                        summary="断面匹配 dry-run 不可用",
                        warnings=("断面匹配 dry-run 不可用，已降级",),
                        source_calls=tuple(source_calls),
                    )
                raise _translate_facade_error(error) from error
            source_calls.append("match_section_caption")
            if decision is None or decision.match_status == "match_not_found":
                return QAAnswer(
                    question_type=request.question_type,
                    scope=request.scope,
                    status=QAAnswerStatus.ANSWERED,
                    summary="没有找到断面匹配候选",
                    source_calls=tuple(source_calls),
                )
            facts.append(_section_match_fact(decision))
            return QAAnswer(
                question_type=request.question_type,
                scope=request.scope,
                status=QAAnswerStatus.ANSWERED,
                summary=_section_matches_summary((decision,)),
                facts=tuple(facts),
                source_calls=tuple(source_calls),
            )

        warnings.append("未提供 cross_section_id，无法执行 dry-run 匹配判断")
        return QAAnswer(
            question_type=request.question_type,
            scope=request.scope,
            status=QAAnswerStatus.NOT_FOUND,
            summary="没有找到已持久化的断面匹配",
            warnings=tuple(warnings),
            source_calls=tuple(source_calls),
        )

    def _answer_table_caption_status(self, request: QARequest) -> QAAnswer:
        unsupported = (
            "表格标题派生状态（Table -[:HAS_CAPTION]-> TableCaption）缺少 facade 只读接口，本阶段未查询",
        )
        if request.scope.page_id is None:
            return QAAnswer(
                question_type=request.question_type,
                scope=request.scope,
                status=QAAnswerStatus.PARTIAL,
                summary="缺少 page_id，无法通过现有 facade 反查页面",
                unsupported_parts=(
                    "缺少 page_id，无法回答表格标题派生状态",
                ),
                source_calls=(),
            )

        try:
            page = self.facade.get_page_source_facts(request.scope.page_id)
        except ToolModelError as error:
            if error.category == "NOT_FOUND":
                return QAAnswer(
                    question_type=request.question_type,
                    scope=request.scope,
                    status=QAAnswerStatus.NOT_FOUND,
                    summary="页面不存在或来源事实不可用",
                    source_calls=("get_page_source_facts",),
                )
            raise _translate_facade_error(error) from error
        if page is None:
            return QAAnswer(
                question_type=request.question_type,
                scope=request.scope,
                status=QAAnswerStatus.NOT_FOUND,
                summary="页面不存在或来源事实不可用",
                source_calls=("get_page_source_facts",),
            )

        tables = tuple(element for element in page.elements if element.element_type == "Table")
        captions = tuple(
            element for element in page.elements if element.element_type == "TableCaption"
        )
        facts = [
            AnswerFact(
                fact_kind="source_fact",
                label="表格统计",
                status="confirmed",
                ids={"page_id": page.page_id},
                value={"table_count": len(tables), "table_caption_count": len(captions)},
                evidence=(EvidenceRef(page_id=page.page_id, image_path=page.image_path),),
            )
        ]
        for table in tables:
            facts.append(
                _source_element_fact(
                    label="表格",
                    element=table,
                    page_id=page.page_id,
                    image_path=page.image_path,
                    id_key="table_id",
                )
            )
        for caption in captions:
            facts.append(
                _source_element_fact(
                    label="表格标题",
                    element=caption,
                    page_id=page.page_id,
                    image_path=page.image_path,
                    id_key="table_caption_id",
                )
            )

        if not tables and not captions:
            summary = f"页面 {page.page_id} 没有表格或表格标题来源元素"
        else:
            summary = (
                f"页面 {page.page_id} 有 {len(tables)} 个表格、"
                f"{len(captions)} 个表格标题来源元素"
            )
        return QAAnswer(
            question_type=request.question_type,
            scope=request.scope,
            status=QAAnswerStatus.PARTIAL,
            summary=summary,
            facts=tuple(facts),
            unsupported_parts=unsupported,
            source_calls=("get_page_source_facts",),
        )

    def _answer_diagnostic_status(self, request: QARequest) -> QAAnswer:
        source_calls: list[str] = []
        warnings: list[str] = []
        facts: list[AnswerFact] = []
        status = QAAnswerStatus.ANSWERED

        if request.scope.page_id is not None:
            try:
                page = self.facade.get_page_source_facts(request.scope.page_id)
            except ToolModelError as error:
                if error.category == "NOT_FOUND":
                    return QAAnswer(
                        question_type=request.question_type,
                        scope=request.scope,
                        status=QAAnswerStatus.NOT_FOUND,
                        summary="页面不存在或来源事实不可用",
                        source_calls=("get_page_source_facts",),
                    )
                raise _translate_facade_error(error) from error
            source_calls.append("get_page_source_facts")
            if page is None:
                return QAAnswer(
                    question_type=request.question_type,
                    scope=request.scope,
                    status=QAAnswerStatus.NOT_FOUND,
                    summary="页面不存在或来源事实不可用",
                    source_calls=tuple(source_calls),
                )
            facts.append(
                _diagnostic_fact(
                    label="导入可见性",
                    status="confirmed",
                    ids={"page_id": page.page_id},
                    value="已导入",
                )
            )

            if request.include_semantics:
                observations, observation_warnings, observation_degraded = _optional_facade_call(
                    lambda: self.facade.list_text_observations(page_id=request.scope.page_id)
                )
                source_calls.append("list_text_observations")
                warnings.extend(observation_warnings)
                if observation_degraded:
                    status = QAAnswerStatus.PARTIAL
                interpretations, interpretation_warnings, interpretation_degraded = _optional_facade_call(
                    lambda: self.facade.list_interpretations(page_id=request.scope.page_id)
                )
                source_calls.append("list_interpretations")
                warnings.extend(interpretation_warnings)
                if interpretation_degraded:
                    status = QAAnswerStatus.PARTIAL
                observation_count = len(observations or ())
                interpretation_count = len(interpretations or ())
                facts.append(
                    _diagnostic_fact(
                        label="语义证据",
                        status="confirmed" if observation_count or interpretation_count else "not_found",
                        ids={"page_id": page.page_id},
                        value={
                            "observation_count": observation_count,
                            "interpretation_count": interpretation_count,
                        },
                    )
                )

            if request.include_candidates:
                candidates, candidate_warnings, candidate_degraded = _optional_facade_call(
                    lambda: self.facade.list_candidate_relations(page_id=request.scope.page_id)
                )
                source_calls.append("list_candidate_relations")
                warnings.extend(candidate_warnings)
                if candidate_degraded:
                    status = QAAnswerStatus.PARTIAL
                candidate_count = len(candidates or ())
                facts.append(
                    _diagnostic_fact(
                        label="候选状态",
                        status="confirmed" if candidate_count else "not_found",
                        ids={"page_id": page.page_id},
                        value={"candidate_count": candidate_count},
                    )
                )
            summary = f"页面 {page.page_id} 诊断：导入可见，语义证据与候选状态以查询结果为准"
        else:
            try:
                trace = self.facade.get_block_trace(request.scope.block_id)
            except ToolModelError as error:
                if error.category == "NOT_FOUND":
                    return QAAnswer(
                        question_type=request.question_type,
                        scope=request.scope,
                        status=QAAnswerStatus.NOT_FOUND,
                        summary="图块不存在或追溯信息不可用",
                        source_calls=("get_block_trace",),
                    )
                raise _translate_facade_error(error) from error
            source_calls.append("get_block_trace")
            try:
                relations = self.facade.get_block_relations(request.scope.block_id)
            except ToolModelError as error:
                if error.category == "NOT_FOUND":
                    return QAAnswer(
                        question_type=request.question_type,
                        scope=request.scope,
                        status=QAAnswerStatus.NOT_FOUND,
                        summary="图块关系信息不可用",
                        source_calls=tuple(source_calls),
                    )
                raise _translate_facade_error(error) from error
            source_calls.append("get_block_relations")
            if trace is None or relations is None:
                return QAAnswer(
                    question_type=request.question_type,
                    scope=request.scope,
                    status=QAAnswerStatus.NOT_FOUND,
                    summary="图块不存在或关系信息不可用",
                    source_calls=tuple(source_calls),
                )
            facts.append(
                _diagnostic_fact(
                    label="导入可见性",
                    status="confirmed",
                    ids={"block_id": trace.block_id, "page_id": trace.page_id},
                    value="已导入",
                )
            )
            facts.append(
                _diagnostic_fact(
                    label="增强状态",
                    status=relations.relation_status,
                    ids={"block_id": trace.block_id},
                    value={"relation_status": relations.relation_status},
                )
            )
            if request.include_candidates:
                candidates, candidate_warnings, candidate_degraded = _optional_facade_call(
                    lambda: self.facade.list_candidate_relations(block_id=request.scope.block_id)
                )
                source_calls.append("list_candidate_relations")
                warnings.extend(candidate_warnings)
                if candidate_degraded:
                    status = QAAnswerStatus.PARTIAL
                candidate_count = len(candidates or ())
                facts.append(
                    _diagnostic_fact(
                        label="候选状态",
                        status="confirmed" if candidate_count else "not_found",
                        ids={"block_id": trace.block_id},
                        value={"candidate_count": candidate_count},
                    )
                )
            summary = f"图块 {trace.block_id} 诊断：已导入，增强状态为 {relations.relation_status}"

        return QAAnswer(
            question_type=request.question_type,
            scope=request.scope,
            status=status,
            summary=summary,
            facts=tuple(facts),
            warnings=tuple(warnings),
            unsupported_parts=(),
            source_calls=tuple(source_calls),
        )

    def _unsupported(self, request: QARequest, reason: str | None = None) -> QAAnswer:
        reason = reason or "该问题类型当前不受支持或无法安全映射"
        return QAAnswer(
            question_type=request.question_type,
            scope=request.scope,
            status=QAAnswerStatus.UNSUPPORTED,
            summary=reason,
            facts=(),
            warnings=(),
            unsupported_parts=(reason,),
            source_calls=(),
        )


def _require_scope_id(value: str | None, label: str, question_type: QuestionType) -> None:
    if value is None:
        raise QAError(
            QAErrorCode.INVALID_ARGUMENT,
            f"{label} is required for {question_type.value}",
        )


def _translate_facade_error(error: ToolModelError) -> QAError:
    mapping = {
        "INVALID_ARGUMENT": QAErrorCode.INVALID_ARGUMENT,
        "UNSUPPORTED_QUESTION": QAErrorCode.UNSUPPORTED_QUESTION,
        "UNSUPPORTED_SCOPE": QAErrorCode.UNSUPPORTED_SCOPE,
        "NOT_FOUND": QAErrorCode.NOT_FOUND,
        "PARTIAL_ANSWER": QAErrorCode.PARTIAL_ANSWER,
        "WRITE_BACK_FORBIDDEN": QAErrorCode.WRITE_BACK_FORBIDDEN,
        "FACADE_UNAVAILABLE": QAErrorCode.FACADE_UNAVAILABLE,
        "NEO4J_UNAVAILABLE": QAErrorCode.NEO4J_UNAVAILABLE,
        "SEMANTIC_EVIDENCE_UNAVAILABLE": QAErrorCode.SEMANTIC_EVIDENCE_UNAVAILABLE,
    }
    category = mapping.get(error.category, QAErrorCode.INTERNAL_ERROR)
    return QAError(category, str(error), retryable=category in {QAErrorCode.NEO4J_UNAVAILABLE})


def _optional_facade_call(callback: Callable[[], Any]) -> tuple[Any, tuple[str, ...], bool]:
    """Run an optional facade query and downgrade empty/unavailable results.

    Returns ``(result, warnings, degraded)``. ``NOT_FOUND`` is treated as an
    empty result with a warning; ``SEMANTIC_EVIDENCE_UNAVAILABLE`` is a
    degraded result with a warning. Infrastructure errors are re-raised as
    QA errors.
    """

    try:
        return callback(), (), False
    except ToolModelError as error:
        if error.category == "NOT_FOUND":
            return None, ("未找到可选查询结果",), False
        if error.category == "SEMANTIC_EVIDENCE_UNAVAILABLE":
            return None, ("语义证据查询不可用，已降级",), True
        raise _translate_facade_error(error) from error


def _bbox_dict(bbox) -> dict[str, float]:
    return {
        "x_min": bbox.x_min,
        "y_min": bbox.y_min,
        "x_max": bbox.x_max,
        "y_max": bbox.y_max,
    }


def _element_type_stats(elements) -> dict[str, int]:
    stats: dict[str, int] = {}
    for element in elements:
        stats[element.element_type] = stats.get(element.element_type, 0) + 1
    return stats


def _observation_fact(observation, image_path: str | None) -> AnswerFact:
    return AnswerFact(
        fact_kind="semantic_observation",
        label="文字观察",
        status=observation.status,
        ids={
            "observation_id": observation.observation_id,
            "element_id": observation.target_element_id,
            "page_id": observation.page_id,
        },
        value=observation.raw_text,
        evidence=(
            EvidenceRef(
                page_id=observation.page_id,
                element_id=observation.target_element_id,
                image_path=image_path,
                bbox=_bbox_dict(observation.bbox),
                normalized_bbox=_bbox_dict(observation.normalized_bbox),
                observation_id=observation.observation_id,
                recognition_run_id=observation.recognition_run_id,
            ),
        ),
    )


def _interpretation_fact(interpretation) -> AnswerFact:
    return AnswerFact(
        fact_kind="semantic_interpretation",
        label="语义解释",
        status=interpretation.analysis_status,
        ids={
            "interpretation_id": interpretation.interpretation_id,
            "element_id": interpretation.element_id,
        },
        value=interpretation.summary,
        evidence=(
            EvidenceRef(
                page_id=interpretation.page_id,
                element_id=interpretation.element_id,
                interpretation_id=interpretation.interpretation_id,
                recognition_run_id=interpretation.recognition_run_id,
                payload_ref=interpretation.payload_ref,
            ),
        ),
    )


def _block_trace_fact(trace) -> AnswerFact:
    return AnswerFact(
        fact_kind="source_fact",
        label="图块追溯",
        status="confirmed",
        ids={
            "block_id": trace.block_id,
            "project_id": trace.project_id,
            "drawing_set_id": trace.drawing_set_id,
            "page_id": trace.page_id,
        },
        value={
            "page_number": trace.page_number,
            "citation_ref": trace.citation_ref,
        },
        evidence=(
            EvidenceRef(
                project_id=trace.project_id,
                drawing_set_id=trace.drawing_set_id,
                page_id=trace.page_id,
                block_id=trace.block_id,
                image_path=trace.image_path,
                bbox=_bbox_dict(trace.bbox),
                normalized_bbox=_bbox_dict(trace.normalized_bbox),
            ),
        ),
    )


def _derived_group_fact(
    *,
    block_id: str,
    page_id: str,
    label: str,
    relation_type: str,
    ids_tuple: tuple[str, ...],
) -> AnswerFact:
    return AnswerFact(
        fact_kind="derived_relation",
        label=label,
        status="confirmed" if ids_tuple else "not_found",
        ids={"block_id": block_id, "page_id": page_id},
        relation_type=relation_type,
        value=ids_tuple,
        evidence=(EvidenceRef(block_id=block_id, page_id=page_id),),
    )


def _candidate_group_fact(
    *,
    block_id: str,
    page_id: str,
    label: str,
    relation_type: str,
    ids_tuple: tuple[str, ...],
) -> AnswerFact:
    return AnswerFact(
        fact_kind="candidate_relation",
        label=label,
        status="candidate",
        ids={"block_id": block_id, "page_id": page_id},
        relation_type=relation_type,
        value=ids_tuple,
        evidence=(EvidenceRef(block_id=block_id, page_id=page_id),),
    )


def _candidate_fact(candidate) -> AnswerFact:
    value = {}
    if candidate.score is not None:
        value["score"] = candidate.score
    if candidate.conflict_reason is not None:
        value["conflict_reason"] = candidate.conflict_reason
    return AnswerFact(
        fact_kind="candidate_relation",
        label=f"{candidate.relation_type} 候选",
        status=candidate.status,
        ids={
            "candidate_group_id": candidate.candidate_group_id,
            "page_id": candidate.page_id,
            "block_id": candidate.block_id,
        },
        relation_type=candidate.relation_type,
        value=value or None,
        evidence=(
            EvidenceRef(
                page_id=candidate.page_id,
                block_id=candidate.block_id,
                candidate_group_id=candidate.candidate_group_id,
                recognition_run_id=candidate.recognition_run_id,
            ),
        ),
    )


def _source_element_fact(
    *,
    label: str,
    element,
    page_id: str,
    image_path: str | None,
    id_key: str,
) -> AnswerFact:
    return AnswerFact(
        fact_kind="source_fact",
        label=label,
        status="confirmed",
        ids={"page_id": page_id, id_key: element.element_id},
        value=element.element_id,
        evidence=(
            EvidenceRef(
                page_id=page_id,
                element_id=element.element_id,
                image_path=image_path,
                bbox=_bbox_dict(element.bbox),
                normalized_bbox=_bbox_dict(element.normalized_bbox),
            ),
        ),
    )


def _diagnostic_fact(
    *,
    label: str,
    status: str,
    ids: dict[str, str],
    value: Any,
) -> AnswerFact:
    return AnswerFact(
        fact_kind="diagnostic",
        label=label,
        status=status,
        ids=ids,
        value=value,
    )


def _section_match_fact(match) -> AnswerFact:
    is_formal = match.fact_kind == "formal_relation"
    value = {
        "logical_key": match.logical_key,
        "symbol_system": match.symbol_system,
        "candidate_count": match.candidate_count,
        "conflict_reason": match.conflict_reason,
        "matched_caption_ids": match.matched_caption_ids,
        "observation_ids": match.observation_ids,
        "alias_rule_id": match.alias_rule_id,
    }
    return AnswerFact(
        fact_kind=match.fact_kind,
        label="断面正式匹配" if is_formal else "断面候选匹配",
        status=match.status,
        ids={"cross_section_id": match.cross_section_id},
        relation_type="MATCHES_SECTION_CAPTION" if is_formal else "candidate_matches_section_caption",
        value=value,
        evidence=(
            EvidenceRef(
                page_id=match.evidence.get("page_id") if match.evidence else None,
                element_id=match.cross_section_id,
                candidate_group_id=match.evidence.get("candidate_group_id") if match.evidence else None,
                rule_version=match.rule_version,
                review_run_id=match.evidence.get("review_run_id") if match.evidence else None,
            ),
        ),
    )


def _section_matches_summary(matches) -> str:
    formal_count = sum(1 for match in matches if match.fact_kind == "formal_relation")
    candidate_count = sum(1 for match in matches if match.fact_kind != "formal_relation")
    ambiguous = any(getattr(match, "match_status", None) == "ambiguous" for match in matches)
    summary = f"找到 {len(matches)} 条断面匹配（{formal_count} 正式，{candidate_count} 候选）"
    if ambiguous:
        summary += "，存在歧义未确认正式匹配"
    return summary


__all__ = ("DrawingGraphQAService",)
