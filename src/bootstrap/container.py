from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from decisionssearch.application.memory.admission_service import AdmissionService
from decisionssearch.application.agents.agent_loop_service import AgentLoopService
from decisionssearch.application.governance.audit_service import AuditService
from decisionssearch.application.catalog.catalog_csv_service import CatalogCsvService
from decisionssearch.application.agents.cognitive_reflection_service import CognitiveReflectionService
from decisionssearch.application.memory.commit_memory_hook import CommitMemoryCaptureService, JsonlCaptureState
from decisionssearch.application.search.composite_scorer import CompositeScorer
from decisionssearch.application.memory.consolidation_service import ConsolidationService
from decisionssearch.application.memory.context_resolver import ContextResolver
from decisionssearch.infrastructure.ai.embeddings.embedding_service import EmbeddingService
from decisionssearch.application.memory.episodic_memory_service import EpisodicMemoryService
from decisionssearch.application.memory.extraction_service import ExtractionService
from decisionssearch.application.catalog.graph_catalog_service import GraphCatalogService
from decisionssearch.application.catalog.graph_operations_service import GraphOperationsService
from decisionssearch.application.search.hybrid_search_service import HybridSearchService
from decisionssearch.application.search.hyde_service import HyDEService
from decisionssearch.application.memory.landing_zone_service import LandingZoneService
from decisionssearch.application.memory.manual_memory_authoring_service import ManualMemoryAuthoringService
from decisionssearch.infrastructure.persistence.neo4j.neo4j_service import Neo4jService
from decisionssearch.infrastructure.persistence.neo4j.neo4j_memory_ledger import Neo4jMemoryLedger
from decisionssearch.application.memory.persistence_service import PersistenceService
from decisionssearch.application.memory.ledger import (
    InMemoryMemoryLedger,
    LedgerApplyService,
    LocalApprovalBoundary,
    ProposalService,
)
from decisionssearch.application.memory.ledger.materializer import QdrantHeadMaterializer
from decisionssearch.application.pr_memory.pr_memory_service import PRMemoryService
from decisionssearch.application.memory.procedural_memory_service import ProceduralMemoryService
from decisionssearch.infrastructure.persistence.qdrant.qdrant_service import QdrantService
from decisionssearch.application.search.query_rewriter_service import QueryRewriterService
from decisionssearch.infrastructure.ai.reranking.reranking_service import create_reranker
from decisionssearch.application.memory.sanitization_service import SanitizationService
from decisionssearch.application.search.spreading_activation_service import SpreadingActivationService
from decisionssearch.application.governance.telemetry_service import TelemetryService
from decisionssearch.application.governance.tool_telemetry_service import ToolTelemetryService
from decisionssearch.application.governance.weight_service import WeightService


@dataclass
class ServiceContainer:
    neo4j: Neo4jService
    qdrant: QdrantService
    embeddings: EmbeddingService
    extraction: ExtractionService
    admission: AdmissionService
    persistence: PersistenceService
    search: HybridSearchService
    sanitization: SanitizationService
    resolver: ContextResolver
    weight: WeightService
    telemetry: TelemetryService
    consolidation: ConsolidationService
    agent_loop: AgentLoopService
    reflection: CognitiveReflectionService
    landing_zone: LandingZoneService
    audit: AuditService
    graph_catalog: GraphCatalogService
    graph_operations: GraphOperationsService
    catalog_csv: CatalogCsvService
    pr_memory: PRMemoryService
    manual_memory_authoring: ManualMemoryAuthoringService
    commit_memory: CommitMemoryCaptureService
    procedural_memory: ProceduralMemoryService
    episodic_memory: EpisodicMemoryService
    ledger: Any
    proposal_service: ProposalService
    approval_boundary: LocalApprovalBoundary
    ledger_apply: LedgerApplyService
    materializer: QdrantHeadMaterializer
    tool_telemetry: Any = None
    error_service: Any = None
    error_orchestrator: Any = None
    notification_service: Any = None
    scheduler: Any = None
    daily_scan: Any = None
    config: Any = None

    async def close(self) -> None:
        await self.neo4j.close()
        await self.qdrant.close()
        if self.scheduler and hasattr(self.scheduler, "stop"):
            await self.scheduler.stop()
        if self.notification_service and hasattr(self.notification_service, "close"):
            await self.notification_service.close()


def create_container() -> ServiceContainer:
    neo4j = Neo4jService(legacy_memory_writes_allowed=False)
    qdrant = QdrantService()
    qdrant.canonical_only = True
    ledger_backend = os.getenv("DECISIONSSEARCH_LEDGER_BACKEND", "neo4j").strip().lower()
    if ledger_backend == "memory":
        ledger = InMemoryMemoryLedger()
    elif ledger_backend == "neo4j":
        ledger = Neo4jMemoryLedger(neo4j)
    else:
        raise ValueError(
            "DECISIONSSEARCH_LEDGER_BACKEND inválido; use 'neo4j' ou 'memory'. "
            "O modo memory é apenas para testes e não é autoritativo."
        )
    proposal_service = ProposalService(ledger)
    approval_boundary = LocalApprovalBoundary(ledger)
    ledger_apply = LedgerApplyService(ledger)
    embeddings = EmbeddingService()
    materializer = QdrantHeadMaterializer(ledger=ledger, qdrant=qdrant, embeddings=embeddings)
    sanitization = SanitizationService()
    extraction = ExtractionService(sanitization=sanitization)
    weight = WeightService()
    admission = AdmissionService(vector_store=qdrant, embeddings=embeddings)
    persistence = PersistenceService(
        neo4j=neo4j,
        qdrant=qdrant,
        embeddings=embeddings,
        weight_service=weight,
        proposal_service=proposal_service,
    )
    reranker = create_reranker()
    spreading = SpreadingActivationService(neo4j=neo4j, ledger=ledger)
    hyde = HyDEService()
    query_rewriter = QueryRewriterService()
    search = HybridSearchService(
        qdrant=qdrant,
        neo4j=neo4j,
        embeddings=embeddings,
        reranker=reranker,
        spreading_activation=spreading,
        hyde=hyde,
        composite_scorer=CompositeScorer.from_env(),
        query_rewriter=query_rewriter,
        ledger=ledger,
    )
    resolver = ContextResolver(neo4j=neo4j)
    telemetry = TelemetryService()
    tool_telemetry = ToolTelemetryService()
    consolidation = ConsolidationService(
        neo4j=neo4j,
        qdrant=qdrant,
        proposal_service=proposal_service,
    )
    landing_zone = LandingZoneService()
    audit = AuditService()
    graph_catalog = GraphCatalogService(neo4j=neo4j)
    graph_operations = GraphOperationsService(neo4j=neo4j)
    catalog_csv = CatalogCsvService(
        graph_catalog=graph_catalog,
        graph_operations=graph_operations,
    )
    pr_memory = PRMemoryService(
        neo4j=neo4j,
        embeddings=embeddings,
        proposal_service=proposal_service,
        ledger=ledger,
    )
    procedural_memory = ProceduralMemoryService(
        neo4j=neo4j,
        proposal_service=proposal_service,
        ledger=ledger,
    )
    episodic_memory = EpisodicMemoryService(
        neo4j=neo4j,
        proposal_service=proposal_service,
        ledger=ledger,
    )
    reflection = CognitiveReflectionService(
        neo4j=neo4j,
        procedural_memory=procedural_memory,
        weight_service=weight,
        telemetry=telemetry,
        extraction=extraction,
        proposal_service=proposal_service,
        ledger=ledger,
    )
    agent_loop = AgentLoopService(
        search=search,
        extraction=extraction,
        admission=admission,
        persistence=persistence,
        episodic_memory=episodic_memory,
        procedural_memory=procedural_memory,
        weight=weight,
        neo4j=neo4j,
        reflection_service=reflection,
    )
    manual_memory_authoring = ManualMemoryAuthoringService(
        admission=admission,
        persistence=persistence,
        proposal_service=proposal_service,
    )
    commit_memory = CommitMemoryCaptureService(
        extraction=extraction,
        admission=admission,
        persistence=persistence,
        sanitization=sanitization,
        state=JsonlCaptureState(
            os.getenv(
                "DECISIONSSEARCH_COMMIT_MEMORY_STATE_PATH",
                "data/commit_memory_hook/processed.jsonl",
            )
        ),
    )

    return ServiceContainer(
        neo4j=neo4j,
        qdrant=qdrant,
        embeddings=embeddings,
        extraction=extraction,
        admission=admission,
        persistence=persistence,
        search=search,
        sanitization=sanitization,
        resolver=resolver,
        weight=weight,
        telemetry=telemetry,
        tool_telemetry=tool_telemetry,
        consolidation=consolidation,
        agent_loop=agent_loop,
        reflection=reflection,
        landing_zone=landing_zone,
        audit=audit,
        graph_catalog=graph_catalog,
        graph_operations=graph_operations,
        catalog_csv=catalog_csv,
        pr_memory=pr_memory,
        procedural_memory=procedural_memory,
        episodic_memory=episodic_memory,
        ledger=ledger,
        proposal_service=proposal_service,
        approval_boundary=approval_boundary,
        ledger_apply=ledger_apply,
        materializer=materializer,
        manual_memory_authoring=manual_memory_authoring,
        commit_memory=commit_memory,
    )


def wire_error_pipeline(container: ServiceContainer, config: Any = None) -> None:
    from decisionssearch.infrastructure.config.config_loader import load_config
    from decisionssearch.application.error_investigation.error_service import ErrorService
    from decisionssearch.application.error_investigation.error_investigation_orchestrator import ErrorInvestigationOrchestrator
    from decisionssearch.application.notifications.notification_registry import NotificationRegistry
    from decisionssearch.application.notifications.notification_service import NotificationService
    from decisionssearch.infrastructure.agents.agent_worker import create_agent_worker
    from decisionssearch.application.jobs.scheduler_service import SchedulerService
    from decisionssearch.infrastructure.integrations.github_service import GitHubService
    from decisionssearch.application.jobs.daily_scan_service import DailyScanService

    if config is None:
        config = load_config()

    container.config = config

    error_svc = ErrorService(neo4j=container.neo4j, ledger=container.ledger)
    container.error_service = error_svc

    registry = NotificationRegistry()
    notif_svc = NotificationService(registry=registry)
    container.notification_service = notif_svc

    agent_cfg = config.agent_config
    try:
        worker = create_agent_worker(agent_cfg)
    except ValueError:
        worker = None

    github = GitHubService(
        repo_path=config.get("agent", "workdir", default="."),
        gh_token=config.get("github", "token", default=""),
    ) if config.github_config.get("auto_create_pr", False) else None

    orchestrator = ErrorInvestigationOrchestrator(
        error_service=error_svc,
        pr_memory=container.pr_memory,
        notification_service=notif_svc,
        worker=worker,
        github=github,
        safety=config.safety,
    )
    container.error_orchestrator = orchestrator

    scan_config = config.get("daily_scan", default={})
    if scan_config.get("enabled", False):
        daily_scan = DailyScanService(container=container, config=scan_config)
        container.daily_scan = daily_scan

    scheduler = SchedulerService(
        container=container,
        config=config.scheduler_config,
    )
    container.scheduler = scheduler
