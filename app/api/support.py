from __future__ import annotations

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.api.dependencies import CurrentUser, DbSession
from app.framework.response import ApiResponse
from app.framework.trace import current_trace_id
from app.modules.support.service import SupportService
from app.modules.support.outbound import OutboundService, build_customer_channel


router = APIRouter(prefix="/support", tags=["merchant-support"])
service = SupportService()
outbound_service = OutboundService(build_customer_channel())


class TransitionRequest(BaseModel):
    status: str
    expected_version: int = Field(alias="expectedVersion")
    resolution_code: str | None = Field(default=None, alias="resolutionCode")
    resolution_note: str | None = Field(default=None, alias="resolutionNote")
    reason: str | None = None


class AssignRequest(BaseModel):
    assignee_id: int | None = Field(default=None, alias="assigneeId")
    expected_version: int = Field(alias="expectedVersion")


class LabelsRequest(BaseModel):
    labels: list[str]
    expected_version: int = Field(alias="expectedVersion")


class ReplyRequest(BaseModel):
    content: str


class DecisionRequest(BaseModel):
    decision: str
    final_content: str | None = Field(default=None, alias="finalContent")
    reason: str | None = None


class KnowledgeReleaseRequest(BaseModel):
    version: str
    title: str
    document_ids: list[int] = Field(alias="documentIds")


class GapResolutionRequest(BaseModel):
    release_id: int = Field(alias="releaseId")


class EvaluationRunRequest(BaseModel):
    release_id: int = Field(alias="releaseId")


class ReleaseDecisionRequest(BaseModel):
    run_id: int = Field(alias="runId")
    release_id: int = Field(alias="releaseId")
    decision: str


class QualityLabelRequest(BaseModel):
    verdict: str
    failure_category: str | None = Field(default=None, alias="failureCategory")
    severity: str | None = None
    note: str | None = None
    suggestion_id: int | None = Field(default=None, alias="suggestionId")


class OutboundRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10000)
    expected_version: int = Field(alias="expectedVersion", ge=1)
    idempotency_key: str = Field(alias="idempotencyKey", min_length=8, max_length=100)
    suggestion_id: int | None = Field(default=None, alias="suggestionId")


def _owner(db, user) -> int:
    return service.owner_for(db, user)


@router.get("/cases")
def list_cases(
    db: DbSession,
    user: CurrentUser,
    status: str | None = None,
    priority: str | None = None,
    assignee_id: int | None = Query(default=None, alias="assigneeId"),
    label: str | None = None,
    unread: bool | None = None,
    search: str | None = None,
) -> ApiResponse:
    return ApiResponse(
        data=service.list_cases(
            db,
            _owner(db, user),
            status=status,
            priority=priority,
            assignee_id=assignee_id,
            label=label,
            unread=unread,
            search=search,
        ),
        traceId=current_trace_id(),
    )


@router.get("/cases/{case_id}")
def case_detail(case_id: int, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.detail(db, _owner(db, user), case_id), traceId=current_trace_id())


@router.get("/cases/{case_id}/workspace")
def case_workspace(case_id: int, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(
        data=service.workspace(db, _owner(db, user), case_id),
        traceId=current_trace_id(),
    )


@router.get("/cases/{case_id}/provenance")
def case_provenance(case_id: int, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.case_provenance(db, _owner(db, user), case_id), traceId=current_trace_id())


@router.get("/coverage")
def support_coverage(db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.coverage(db, _owner(db, user)), traceId=current_trace_id())


@router.post("/cases/{case_id}/transition")
def transition(case_id: int, payload: TransitionRequest, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(
        data=service.transition(
            db,
            _owner(db, user),
            case_id,
            int(user.id),
            status=payload.status,
            expected_version=payload.expected_version,
            resolution_code=payload.resolution_code,
            resolution_note=payload.resolution_note,
            reason=payload.reason,
        ),
        traceId=current_trace_id(),
    )


@router.post("/cases/{case_id}/assign")
def assign(case_id: int, payload: AssignRequest, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.assign(db, _owner(db, user), case_id, int(user.id), payload.assignee_id, payload.expected_version), traceId=current_trace_id())


@router.put("/cases/{case_id}/labels")
def labels(case_id: int, payload: LabelsRequest, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.set_labels(db, _owner(db, user), case_id, int(user.id), payload.labels, payload.expected_version), traceId=current_trace_id())


@router.post("/cases/{case_id}/replies")
def manual_reply(case_id: int, payload: ReplyRequest, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.manual_reply(db, _owner(db, user), case_id, int(user.id), payload.content), traceId=current_trace_id())


@router.post("/cases/{case_id}/outbound")
def confirm_outbound(
    case_id: int,
    payload: OutboundRequest,
    db: DbSession,
    user: CurrentUser,
) -> ApiResponse:
    return ApiResponse(
        data=outbound_service.confirm(
            db,
            owner_id=_owner(db, user),
            case_id=case_id,
            actor_id=int(user.id),
            content=payload.content,
            expected_version=payload.expected_version,
            idempotency_key=payload.idempotency_key,
            suggestion_id=payload.suggestion_id,
        ),
        traceId=current_trace_id(),
    )


@router.post("/cases/{case_id}/suggestions")
async def generate_suggestion(case_id: int, request: Request, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=await service.generate_suggestion(db, _owner(db, user), case_id, int(user.id), request.app.state.container.model_router), traceId=current_trace_id())


@router.post("/cases/{case_id}/suggestions/{suggestion_id}/decision")
def decide(case_id: int, suggestion_id: int, payload: DecisionRequest, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.decide(db, _owner(db, user), case_id, suggestion_id, int(user.id), payload.decision, payload.final_content, payload.reason), traceId=current_trace_id())


@router.get("/metrics")
def metrics(db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.metrics(db, _owner(db, user)), traceId=current_trace_id())


@router.get("/knowledge/releases")
def knowledge_releases(db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.list_releases(db, _owner(db, user)), traceId=current_trace_id())


@router.get("/knowledge/sources")
def knowledge_sources(db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.knowledge_sources(db, _owner(db, user)), traceId=current_trace_id())


@router.post("/knowledge/releases")
def create_knowledge_release(payload: KnowledgeReleaseRequest, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.create_release(db, _owner(db, user), int(user.id), payload.version, payload.title, payload.document_ids), traceId=current_trace_id())


@router.post("/knowledge/releases/{release_id}/publish")
def publish_knowledge_release(release_id: int, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.publish_release(db, _owner(db, user), release_id, int(user.id)), traceId=current_trace_id())


@router.post("/knowledge/releases/{release_id}/activate")
def activate_knowledge_release(release_id: int, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.activate_release(db, _owner(db, user), release_id), traceId=current_trace_id())


@router.get("/quality")
def quality_overview(db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.quality_overview(db, _owner(db, user)), traceId=current_trace_id())


@router.post("/quality/cases/{case_id}/labels")
def add_quality_label(case_id: int, payload: QualityLabelRequest, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.add_quality_label(db, _owner(db, user), case_id, int(user.id), payload.verdict, payload.failure_category, payload.severity, payload.note, payload.suggestion_id), traceId=current_trace_id())


@router.post("/quality/gaps/{gap_id}/resolve")
def resolve_gap(gap_id: int, payload: GapResolutionRequest, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.resolve_gap(db, _owner(db, user), gap_id, int(user.id), payload.release_id), traceId=current_trace_id())


@router.get("/evaluations")
def evaluation_overview(db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.evaluation_overview(db, _owner(db, user)), traceId=current_trace_id())


@router.get("/evaluations/{run_id}")
def evaluation_detail(run_id: int, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.evaluation_detail(db, _owner(db, user), run_id), traceId=current_trace_id())


@router.post("/evaluations")
async def run_evaluation(payload: EvaluationRunRequest, request: Request, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=await service.run_evaluation_async(db, _owner(db, user), int(user.id), payload.release_id, request.app.state.container.agentic), traceId=current_trace_id())


@router.post("/release-decisions")
def decide_release(payload: ReleaseDecisionRequest, db: DbSession, user: CurrentUser) -> ApiResponse:
    return ApiResponse(data=service.decide_release(db, _owner(db, user), int(user.id), payload.run_id, payload.release_id, payload.decision), traceId=current_trace_id())
