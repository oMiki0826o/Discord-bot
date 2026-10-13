"""
bot/mod/ai/assembly.py

Modification():

- 集中組裝 AI Module-owned database、services、tools、provider 與 worker。
- 建立可完整停止的 AiModule lifecycle object。
- 將 Knowledge chunk 設定注入索引服務。
- 基礎 AI 組裝改用不依賴 Agent package 的 BasicRuntime。
- 組裝 scoped AiServices 並將 BasicRuntime 綁定到 reload-safe RuntimeHost。
- 將自主記憶 SQLite ↔ Owner JSON 鏡像納入啟停與首次回填流程。

本檔案是 Extension 的 composition root，不包含 Discord 指令邏輯。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from collections.abc import Awaitable, Callable
import logging
import uuid

from bot.config import OWNER_ID

from .attachments.service import AttachmentService, AttachmentSettings
from .attachments.document import extract_document
from .api import AiServices
from .background.extractor import ProviderMemoryExtractor
from .background.jobs import MemoryJobRepository
from .background.worker import BackgroundMemoryWorker
from .config import AiSettings, read_secret
from .context.service import ContextOrchestrator
from .context.planner import BasicContextPlanner
from .data import initialize_data_dir
from .data_sync import OwnerDataService
from .database import AiDatabase
from .guard import RequestGuard
from .history.repository import EventRepository
from .history.search import HistorySearchService
from .knowledge.service import KnowledgeService
from .knowledge.staging import KnowledgeStagingSession
from .knowledge.source import KNOWLEDGE_SOURCE_SUFFIXES, KnowledgeSourceReader
from .memory.repository import MemoryRepository
from .memory.service import MemoryService
from .memory.manual_sync import ManualMemorySyncService
from .memory.global_memory import GlobalMemoryService
from .memory.mirror import MemoryMirrorService
from .memory.watcher import MemoryMirrorWatcher
from .operations import AiOperations
from .profiles.repository import PublicProfileRepository
from .prompt.composer import PromptComposer
from .prompt.loader import PromptSourceLoader
from .provider.gemini import GeminiTransport
from .provider.embedding import GeminiEmbeddingProvider
from .provider.quota import QuotaManager
from .provider.runtime import ProviderRuntime
from .routing import Router
from .retrieval.service import HybridRetrievalService
from .retrieval.vector import VectorRepository
from .runtime.basic import BasicRuntime
from .runtime.host import RuntimeHost
from .search.cache import SearchCache
from .service import AIService
from .topics.service import TopicService
from .summary.repository import SummaryRepository
from .summary.service import SummaryService

logger = logging.getLogger("bot.mod.ai.assembly")


@dataclass(slots=True)
class AiModule:
    service: AIService
    attachments: AttachmentService
    worker: BackgroundMemoryWorker
    settings: AiSettings
    knowledge: KnowledgeService
    retrieval: HybridRetrievalService
    profiles: PublicProfileRepository
    prompts: PromptSourceLoader
    knowledge_dir: Path
    manual_memory: Any
    global_memory: GlobalMemoryService
    operations: AiOperations
    summaries: SummaryService
    search_cache: SearchCache
    provider: ProviderRuntime
    owner_data: OwnerDataService
    mirror: MemoryMirrorService
    watcher: MemoryMirrorWatcher | None = None
    _mirror_prepared: bool = False
    _closed: bool = False
    _sync_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def start(self) -> None:
        if self._closed:
            raise RuntimeError("AI module is already closed")
        if not self._mirror_prepared:
            self.mirror.prepare_initial_state()
            self._mirror_prepared = True
        self.worker.start()
        if self.watcher is not None:
            self.watcher.start()

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.watcher is not None:
            await self.watcher.close()
        await self.worker.close()
        await self.service.close()

    def memory_mirror_status(self) -> dict[str, int | str | None]:
        status = {} if self.watcher is None else self.watcher.snapshot()
        status["owner_blocks"] = self.mirror.repository.owner_block_count()
        return status

    def _knowledge_staging(self) -> KnowledgeStagingSession:
        return KnowledgeStagingSession(
            self.manual_memory.database,
            chunk_chars=self.knowledge.chunk_chars,
            embedder=self.retrieval.embedder,
            embedding_model=self.retrieval.embedding_model,
        )

    async def rebuild_knowledge(
        self,
        source_dir: Path | None = None,
        *,
        full: bool = False,
    ) -> int:
        """Incrementally rebuild Knowledge through the shared publishing lock."""

        async with self._sync_lock:
            validation = self.owner_data.validate()
            if not validation.valid:
                raise ValueError("AI data validation failed: " + "; ".join(validation.issues[:3]))
            if source_dir is None and not full:
                changed = tuple(
                    path for path in validation.change_set.changed
                    if path.startswith("knowledge/")
                )
                removed = tuple(
                    path for path in validation.change_set.removed
                    if path.startswith("knowledge/")
                )
                if not changed and not removed:
                    self.owner_data.mark_types_applied(validation, {"knowledge"})
                    return 0
            staging = self._knowledge_staging()
            staging.seed_active()
            try:
                if source_dir is not None:
                    root = Path(source_dir)
                    changed = tuple(
                        path.relative_to(root).as_posix()
                        for path in sorted(root.rglob("*"))
                        if path.is_file() and path.suffix.casefold() in KNOWLEDGE_SOURCE_SUFFIXES
                    )
                    removed = self._staged_source_ids(staging) - set(changed)
                    reader = KnowledgeSourceReader(root)
                else:
                    all_sources = tuple(
                        path.removeprefix("knowledge/")
                        for path in (*validation.change_set.changed, *validation.change_set.unchanged)
                        if path.startswith("knowledge/")
                    )
                    changed = all_sources if full else tuple(
                        path.removeprefix("knowledge/")
                        for path in validation.change_set.changed
                        if path.startswith("knowledge/")
                    )
                    removed = {
                        path.removeprefix("knowledge/")
                        for path in validation.change_set.removed
                        if path.startswith("knowledge/")
                    }
                    reader = KnowledgeSourceReader(self.knowledge_dir)
                for source_id in changed:
                    await staging.apply_document(reader.read(source_id))
                staging.remove_sources(set(removed))
                staging.verify()
                with self.manual_memory.database.transaction() as connection:
                    staging.publish(connection)
                if source_dir is None:
                    self.owner_data.mark_types_applied(validation, {"knowledge"})
                return len(changed)
            finally:
                staging.clear()

    def _staged_source_ids(self, _staging: KnowledgeStagingSession) -> set[str]:
        with self.manual_memory.database.connect() as connection:
            return {
                str(row[0])
                for row in connection.execute("SELECT source_id FROM knowledge_sources_staging")
            }

    async def sync_owner_data(self) -> tuple[int, int]:
        """Apply manual-memory source data and rebuild its dependent knowledge index."""
        operation_id = uuid.uuid4().hex
        async with self._sync_lock:
            self._record_sync_state("staging", operation_id=operation_id)
            published = False
            staging = self._knowledge_staging()
            try:
                validation = self.owner_data.validate()
                if not validation.valid:
                    raise ValueError("AI data validation failed: " + "; ".join(validation.issues[:3]))
                if not validation.change_set.changed and not validation.change_set.removed:
                    self.owner_data.mark_applied(validation)
                    self._record_sync_state("completed", operation_id=operation_id)
                    return validation.manual_records, 0
                with self.owner_data.materialize_snapshot(validation, changed_only=True) as snapshot:
                    snapshot_manual = ManualMemorySyncService(
                        self.manual_memory.database,
                        snapshot / "users_memory",
                    )
                    snapshot_prompts = PromptSourceLoader(
                        resource_dir=self.prompts.resource_dir,
                        override_dir=snapshot / "prompt",
                    )
                    prompt_changed = any(
                        path.startswith("prompt/")
                        for path in (*validation.change_set.changed, *validation.change_set.removed)
                    )
                    prompt_sources = snapshot_prompts.load() if prompt_changed else self.prompts.load()
                    self._record_sync_state("applying", operation_id=operation_id)
                    staging.seed_active()
                    snapshot_manual.seed_staging()
                    snapshot_manual.stage_changed(
                        validation.change_set.changed,
                        validation.change_set.removed,
                    )
                    changed_knowledge = tuple(
                        path.removeprefix("knowledge/")
                        for path in validation.change_set.changed
                        if path.startswith("knowledge/")
                    )
                    reader = KnowledgeSourceReader(snapshot / "knowledge")
                    for source_id in changed_knowledge:
                        await staging.apply_document(reader.read(source_id))
                    staging.remove_sources({
                        path.removeprefix("knowledge/")
                        for path in validation.change_set.removed
                        if path.startswith("knowledge/")
                    })
                    staging.verify()
                    with self.manual_memory.database.transaction() as connection:
                        staging.publish(connection)
                        snapshot_manual.publish_staging(connection)
                    published = True
                    if prompt_changed:
                        self.prompts.install(prompt_sources)
                    self.owner_data.mark_applied(validation)
                    with self.manual_memory.database.connect() as connection:
                        records = int(connection.execute(
                            "SELECT count(*) FROM manual_memory_records"
                        ).fetchone()[0])
                self._record_sync_state("completed", operation_id=operation_id)
                return records, len(changed_knowledge)
            except asyncio.CancelledError:
                self._record_sync_state("cancelled", "synchronization cancelled", operation_id=operation_id)
                raise
            except Exception as exc:
                self._record_sync_state(
                    "failed_published" if published else "failed",
                    f"{type(exc).__name__}: {exc}",
                    operation_id=operation_id,
                )
                raise
            finally:
                staging.clear()
                self.manual_memory.clear_staging()

    def _record_sync_state(self, status: str, detail: str = "", *, operation_id: str) -> None:
        try:
            self.owner_data.set_sync_state(status, detail, operation_id=operation_id)
        except Exception:
            logger.warning("AI data sync state persistence failed status=%s", status, exc_info=True)


def build_module(
    *,
    database_dir: Path,
    data_dir: Path,
    raw_settings: dict[str, Any],
    transport: Any = None,
    channel_reader: Any = None,
    runtime_host: RuntimeHost | None = None,
    audit_sink: Callable[[str, str, str], Awaitable[None]] | None = None,
) -> AiModule:
    settings = AiSettings.from_mapping(raw_settings)
    module_resources = Path(__file__).parent / "resources"
    data_root = initialize_data_dir(Path(data_dir), resource_dir=module_resources)
    database = AiDatabase(Path(database_dir) / "ai.db")
    database.initialize()
    operations = AiOperations(
        database,
        owner_id=None if OWNER_ID is None else str(OWNER_ID),
    )
    events = EventRepository(database)
    history = HistorySearchService(database)
    memory = MemoryService(database=database, event_repository=events, memory_repository=MemoryRepository(database))
    topics = TopicService(database=database, event_repository=events)
    knowledge = KnowledgeService(database, chunk_chars=settings.knowledge_chunk_chars)
    knowledge_sources = KnowledgeSourceReader(data_root / "knowledge")
    manual_memory = ManualMemorySyncService(database, data_root / "users_memory")
    profiles = PublicProfileRepository(database)
    prompts = PromptSourceLoader(resource_dir=module_resources / "prompt", override_dir=data_root / "prompt")
    owner_data = OwnerDataService(data_root, manual_memory=manual_memory, prompts=prompts)
    validation = owner_data.validate()
    if not validation.valid:
        raise ValueError("AI data validation failed: " + "; ".join(validation.issues[:3]))
    manual_memory.sync()
    global_memory = GlobalMemoryService(data_root / "prompt" / "memory.json", prompts=prompts)

    transport = GeminiTransport(read_secret()) if transport is None else transport
    provider = ProviderRuntime(
        transport,
        quota=QuotaManager(default_cooldown_seconds=settings.quota_cooldown_seconds),
        usage_recorder=operations.record_provider_usage,
        error_recorder=operations.record_error,
        trace_recorder=operations.record_provider_trace,
    )
    search_cache = SearchCache(database=database)
    summaries = SummaryService(events, SummaryRepository(database), provider=provider, model_candidates=settings.model_pools["background"])
    embedder = GeminiEmbeddingProvider(transport.client, model=settings.embedding_model, dimensions=settings.embedding_dimensions) if hasattr(transport, "client") else None
    retrieval = HybridRetrievalService(
        knowledge=knowledge,
        vectors=VectorRepository(database),
        memory=memory,
        manual_memory=manual_memory,
        knowledge_sources=knowledge_sources,
        embedder=embedder,
        embedding_model=settings.embedding_model,
    )
    runtime = BasicRuntime(
        provider,
        max_output_tokens=settings.max_output_tokens,
        timeout_seconds=settings.provider_timeout_seconds,
        retries_per_model=settings.provider_retries_per_model,
        search_cache=search_cache,
    )
    host = runtime_host or RuntimeHost()
    host.bind(runtime, AiServices(
        _provider=provider,
        _settings=settings,
        _retrieval=retrieval,
        _history=history,
        _topics=topics,
        _profiles=profiles,
        _knowledge=knowledge,
        _channel_reader=channel_reader,
    ))
    job_settings = settings.memory_jobs
    jobs = MemoryJobRepository(database, max_attempts=job_settings["max_attempts"], retry_base_seconds=job_settings["retry_base_seconds"], retry_max_seconds=job_settings["retry_max_seconds"])
    mirror = MemoryMirrorService(database, data_root / "auto_memory")
    extractor = ProviderMemoryExtractor(provider=provider, memory_service=memory, model_candidates=settings.model_pools["background"], mirror=mirror)
    worker = BackgroundMemoryWorker(jobs=jobs, events=events, processor=extractor, batch_size=job_settings["batch_size"])
    watcher = MemoryMirrorWatcher(mirror, data_root / "auto_memory", settings.memory_mirror_poll_seconds)
    service = AIService(
        settings=settings, events=events,
        context=(context := ContextOrchestrator(event_repository=events, history_search=history, memory_service=memory, topic_service=topics, summary_service=summaries)),
        context_planner=BasicContextPlanner(
            context=context,
            profiles=profiles,
            retrieval=retrieval,
            manual_memory=manual_memory,
            channel_reader=channel_reader,
        ),
        prompts=prompts, composer=PromptComposer(), router=Router(),
        guard=RequestGuard(cooldown_seconds=settings.cooldown_seconds, abuse_limit=settings.abuse_max_requests, abuse_window_seconds=settings.abuse_window_seconds, max_prompt_chars=settings.max_prompt_chars, is_blocked=operations.block_reason),
        runtime=host, memory_jobs=worker,
        audit_sink=audit_sink,
        user_context_provider=operations.user_context,
        interaction_recorder=operations.record_interaction,
    )
    attachment_settings = settings.attachments
    attachments = AttachmentService(AttachmentSettings(attachment_settings["max_count"], attachment_settings["max_bytes_each"], attachment_settings["max_total_bytes"], attachment_settings["max_text_chars"]), document_extractor=extract_document)
    return AiModule(
        service=service,
        attachments=attachments,
        worker=worker,
        settings=settings,
        knowledge=knowledge,
        retrieval=retrieval,
        profiles=profiles,
        prompts=prompts,
        knowledge_dir=data_root / "knowledge",
        manual_memory=manual_memory,
        global_memory=global_memory,
        operations=operations,
        summaries=summaries,
        search_cache=search_cache,
        provider=provider,
        owner_data=owner_data,
        mirror=mirror,
        watcher=watcher,
    )
