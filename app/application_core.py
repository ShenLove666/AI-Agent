from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.compat_chat import router as compat_chat_router
from app.api.compat_knowledge import router as compat_knowledge_router
from app.api.compat_misc import router as compat_misc_router
from app.api.biz_change_logs import router as biz_change_logs_router
from app.api.compat_trace import router as compat_trace_router
from app.api.contract_fixes import router as contract_fixes_router
from app.api.conversations import router as conversation_router
from app.api.dashboard import router as dashboard_router
from app.api.knowledge import router as knowledge_router
from app.api.knowledge_chunk_fixes import router as knowledge_chunk_fixes_router
from app.api.knowledge_fixes import router as knowledge_fixes_router
from app.api.knowledge_mutations import router as knowledge_mutation_router
from app.api.management import router as management_router
from app.api.orders import router as orders_router
from app.api.retail import data_source_router, router as retail_router
from app.api.settings import router as settings_router
from app.api.system import create_system_router
from app.api.support import router as support_router
from app.container import build_container as build_ai_container
from app.framework.config import Settings, settings
from app.framework.database import Database
from app.framework.http import install_http_conventions
from app.framework.migrations import upgrade_database
from app.infra_ai.providers.cross_encoder import CrossEncoderRerankModel
from app.infra_ai.providers.sentence_transformer import (
    SentenceTransformerEmbeddingModel,
)
from app.infra_ai.router import ChatModelRouter
from app.modules.conversations.service import ConversationService
from app.modules.knowledge.search import SqlKeywordSearchChannel
from app.modules.knowledge.service import KnowledgeService
from app.modules.rag.rewrite import QueryRewriteService
from app.modules.rag.service import RagChatService
from app.modules.rag.agentic import AgenticRagCoordinator
from app.modules.rag.trace_service import RagTraceService
from app.modules.retrieval.engine import MultiChannelRetrievalEngine
from app.modules.retrieval.postprocessors import (
    MetadataEnrichmentPostProcessor,
    RerankPostProcessor,
    WeightedRrfPostProcessor,
)
from app.modules.retrieval.vector_channel import VectorSearchChannel
from app.modules.settings.repository import RuntimeSettingsRepository
from app.modules.settings.service import (
    RuntimeSettingsService,
    apply_restart_env_overrides,
)
from app.modules.users.repository import UserRepository
from app.modules.users.service import AuthService
from app.modules.vector.indexer import VectorIndexer
from app.modules.vector.memory import InMemoryVectorStore
from app.modules.vector.milvus import MilvusVectorStore

from app.modules.conversations import models as conversation_models  # noqa: F401,E402
from app.modules.commerce import models as commerce_models  # noqa: F401,E402
from app.modules.evaluation import models as evaluation_models  # noqa: F401,E402
from app.modules.knowledge import models as knowledge_models  # noqa: F401,E402
from app.modules.rag import trace_models as rag_trace_models  # noqa: F401,E402
from app.modules.operations import models as operation_models  # noqa: F401,E402
from app.modules.orders import models as order_models  # noqa: F401,E402
from app.modules.provenance import models as provenance_models  # noqa: F401,E402
from app.modules.optimization import models as optimization_models  # noqa: F401,E402
from app.modules.support import models as support_models  # noqa: F401,E402
from app.modules.users import models as user_models  # noqa: F401,E402


@dataclass(slots=True)
class ApplicationContainer:
    settings: Settings
    database: Database
    user_repository: UserRepository
    auth: AuthService
    conversations: ConversationService
    knowledge: KnowledgeService
    model_router: ChatModelRouter | None
    retrieval: MultiChannelRetrievalEngine
    agentic: AgenticRagCoordinator
    chat: RagChatService
    runtime_settings: RuntimeSettingsService


def build_vector_components():
    backend = os.getenv("VECTOR_BACKEND", "milvus").lower()
    if backend in {"disabled", "none", "off"}:
        return None, None, None
    project_root = Path(__file__).resolve().parents[1]
    bundled_model = project_root / "models" / "bge-small-zh-v1.5"
    model_path = os.getenv("EMBED_MODEL_PATH") or (
        str(bundled_model) if bundled_model.is_dir() else None
    )
    if not model_path:
        return None, None, None
    embeddings = SentenceTransformerEmbeddingModel(
        model_path=model_path,
        device=os.getenv("EMBED_DEVICE", "cpu"),
    )
    if backend == "milvus":
        store = MilvusVectorStore(
            uri=os.getenv(
                "MILVUS_URI", str(project_root / "data" / "milvus-ragent.db")
            ),
            token=os.getenv("MILVUS_TOKEN"),
            dimension=int(os.getenv("EMBED_DIMENSION", "512")),
            collection_name=os.getenv("MILVUS_COLLECTION", "ragent_chunks_v2"),
        )
    else:
        store = InMemoryVectorStore()
    return embeddings, store, VectorIndexer(embeddings, store)


def build_container(app_settings: Settings) -> ApplicationContainer:
    ai = build_ai_container(app_settings)
    database = Database(app_settings.database_url)
    users = UserRepository()
    conversations = ConversationService()
    embeddings, vector_store, vector_indexer = build_vector_components()
    knowledge = KnowledgeService(vector_indexer=vector_indexer)

    channels = [SqlKeywordSearchChannel(database, weight=1.0)]
    weights = {"keyword": 1.0}
    if embeddings is not None and vector_store is not None:
        channels.append(VectorSearchChannel(embeddings, vector_store, weight=1.2))
        weights["vector"] = 1.2

    postprocessors = [WeightedRrfPostProcessor(weights)]
    if rerank_path := os.getenv("RERANK_MODEL_PATH"):
        postprocessors.append(
            RerankPostProcessor(
                CrossEncoderRerankModel(
                    rerank_path, device=os.getenv("RERANK_DEVICE", "cpu")
                ),
                candidate_limit=int(os.getenv("RERANK_CANDIDATE_LIMIT", "20")),
            )
        )
    postprocessors.append(MetadataEnrichmentPostProcessor())
    retrieval = MultiChannelRetrievalEngine(
        channels=channels,
        postprocessors=postprocessors,
        timeout_seconds=app_settings.retrieval_timeout_seconds,
    )
    traces = RagTraceService()
    rewrite = QueryRewriteService(ai.chat_router)
    agentic = AgenticRagCoordinator(ai.chat_router, retrieval)
    runtime_settings = RuntimeSettingsService(
        app_settings, RuntimeSettingsRepository()
    )
    return ApplicationContainer(
        settings=app_settings,
        database=database,
        user_repository=users,
        auth=AuthService(users),
        conversations=conversations,
        knowledge=knowledge,
        model_router=ai.chat_router,
        retrieval=retrieval,
        agentic=agentic,
        chat=RagChatService(
            ai.chat_router,
            conversations,
            retrieval,
            rewrite,
            traces,
            retrieval_candidate_limit=app_settings.retrieval_candidate_limit,
            retrieval_context_limit=app_settings.retrieval_context_limit,
            history_token_budget=app_settings.prompt_history_token_budget,
            context_token_budget=app_settings.prompt_context_token_budget,
            agentic=agentic,
            runtime_settings_repository=RuntimeSettingsRepository(),
        ),
        runtime_settings=runtime_settings,
    )


def create_app(app_settings: Settings | None = None) -> FastAPI:
    resolved_settings = app_settings or settings
    container = build_container(resolved_settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        upgrade_database(container.database)
        # 需重启生效的配置：合并回环境变量后重建容器
        if apply_restart_env_overrides(container.database):
            rebuilt = build_container(Settings())
            app.state.container = rebuilt
        yield
        container.database.engine.dispose()

    app = FastAPI(
        title=resolved_settings.app_name,
        version="2.0.0-alpha.7",
        description="RAGent-style modular RAG platform implemented in Python",
        lifespan=lifespan,
    )
    app.state.container = container
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(resolved_settings.cors_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    install_http_conventions(app)
    prefix = resolved_settings.api_prefix
    for router in (
        settings_router,
        create_system_router(resolved_settings),
        auth_router,
        conversation_router,
        knowledge_router,
        knowledge_mutation_router,
        chat_router,
        management_router,
        orders_router,
        retail_router,
        data_source_router,
        support_router,
        dashboard_router,
        knowledge_fixes_router,
        knowledge_chunk_fixes_router,
        contract_fixes_router,
        compat_knowledge_router,
        compat_chat_router,
        compat_trace_router,
        biz_change_logs_router,
        compat_misc_router,
    ):
        app.include_router(router, prefix=prefix)

    frontend_dist = Path(__file__).resolve().parents[1] / "web" / "dist"
    frontend_assets = frontend_dist / "assets"
    if frontend_assets.is_dir():

        class ImmutableStaticFiles(StaticFiles):
            """构建产物文件名带内容哈希，可安全一年长缓存。"""

            def file_response(
                self, *args, **kwargs
            ):  # pragma: no cover - 依赖 FastAPI 内部签名
                response = super().file_response(*args, **kwargs)
                response.headers.update(
                    {"Cache-Control": "public, max-age=31536000, immutable"}
                )
                return response

        app.mount(
            "/assets",
            ImmutableStaticFiles(directory=frontend_assets),
            name="frontend-assets",
        )

    @app.get("/{path:path}", include_in_schema=False)
    async def serve_frontend(path: str, request: Request):
        if request.url.path == prefix or request.url.path.startswith(prefix + "/"):
            return JSONResponse(
                status_code=404,
                content={
                    "success": False,
                    "data": None,
                    "error": {"code": "ROUTE_NOT_FOUND", "message": "API 接口不存在"},
                    "traceId": None,
                },
            )
        requested_file = (frontend_dist / path).resolve()
        if (
            path
            and frontend_dist in requested_file.parents
            and requested_file.is_file()
        ):
            # 构建产物文件名带内容哈希，可安全长缓存
            return FileResponse(
                requested_file,
                headers={"Cache-Control": "public, max-age=31536000, immutable"},
            )
        index_file = frontend_dist / "index.html"
        if index_file.is_file():
            # SPA 入口必须每次校验，避免缓存旧 index 引用已删除的旧 chunk
            return FileResponse(index_file, headers={"Cache-Control": "no-cache"})
        return {"message": "Frontend has not been built; run `npm run build` in web/."}

    return app


app = create_app()
