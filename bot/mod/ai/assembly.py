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

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from collections.abc import Awaitable, Callable
import logging

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

    async def rebuild_knowledge(self, source_dir: Path | None = None) -> int:
        import time

        count = 0
        knowledge_dir = self.knowledge_dir if source_dir is None else Path(source_dir)
        if not knowledge_dir.is_dir():
            return 0
        source_ids: set[str] = set()
        reader = KnowledgeSourceReader(knowledge_dir)
        for path in sorted(knowledge_dir.rglob("*")):
            if not path.is_file() or path.suffix.casefold() not in KNOWLEDGE_SOURCE_SUFFIXES:
                continue
            relative = path.relative_to(knowledge_dir).as_posix()
            document = reader.read(relative)
            if not document.content.strip():
                logger.warning("Skipping blank knowledge source: %s", relative)
                continue
            await self.retrieval.index_document(document, now=int(time.time()))
            source_ids.add(relative)
            count += 1
        self.knowledge.remove_sources_not_in(source_ids)
        return count

    async def sync_owner_data(self) -> tuple[int, int]:
        """Apply manual-memory source data and rebuild its dependent knowledge index."""
        self.owner_data.set_sync_state("staging")
        try:
            validation = self.owner_data.validate()
            if not validation.valid:
                raise ValueError("AI data validation failed: " + "; ".join(validation.issues[:3]))
            with self.owner_data.materialize_snapshot(validation) as snapshot:
                snapshot_manual = ManualMemorySyncService(
                    self.manual_memory.database,
                    snapshot / "users_memory",
                )
                snapshot_prompts = PromptSourceLoader(
                    resource_dir=self.prompts.resource_dir,
                    override_dir=snapshot / "prompt",
                )
                prompt_sources = snapshot_prompts.load()
                self.owner_data.set_sync_state("applying")
                records = snapshot_manual.sync().records
                documents = await self.rebuild_knowledge(snapshot / "knowledge")
                self.owner_data.mark_snapshot_applied(validation, snapshot)
                self.prompts.install(prompt_sources)
            self.owner_data.set_sync_state("completed")
            return records, documents
        except Exception as exc:
            self.owner_data.set_sync_state("failed", f"{type(exc).__name__}: {exc}")
            raise


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
