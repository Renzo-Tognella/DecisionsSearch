# DecisionsSearch 🔍

> **Hybrid Memory Server for AI Agents** — an MCP server with persistent shared memory (Neo4j + Qdrant) and an autonomous CI/CD error investigator that finds root causes and proposes fixes.

[![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)](https://python.org)
[![MCP](https://img.shields.io/badge/MCP-Compatible-green?logo=json)](https://modelcontextprotocol.io)
[![Tests](https://img.shields.io/badge/tests-passing-brightgreen)]()
[![License](https://img.shields.io/badge/license-MIT-blue)](./LICENSE)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker)]()

🇧🇷 **[Leia em Português](README.pt-BR.md)**

## What DecisionsSearch Is

AI coding agents forget everything the moment a session ends. The next session — yours or a teammate's — re-derives the same context, re-litigates the same decisions, and repeats mistakes the team already fixed once. CI/CD pipelines have the same blind spot: errors happen, get triaged manually, and the connection between "this error" and "the PR that caused it" is lost.

**DecisionsSearch is a persistent, queryable memory layer that sits between your AI agents and a knowledge graph.** It gives agents three things they don't have on their own:

1. **Durable memory across sessions** — decisions, business rules, code patterns, and PR history survive after the chat window closes. Neo4j stores the relationships (what implements what, what superseded what); Qdrant enables semantic search over all of it.
2. **A structured vocabulary for "what's worth remembering"** — not a raw transcript dump, but typed categories (business rule, architectural decision, code pattern, PR record, task episode) that stay useful months later.
3. **Autonomous error investigation** — point your CI/CD at DecisionsSearch's webhook, and it finds the suspect PRs, runs a coding agent to investigate root cause, and can open a fix PR on its own.

## When To Use It

- You're running Claude Code (or another MCP-aware agent) on a codebase you touch repeatedly, and you're tired of re-explaining the same architecture and rules every session.
- Multiple agents/developers work on the same codebase and need a shared source of truth for *why* things are the way they are, not just *what* the code does.
- You want your CI/CD to do first-pass triage on errors before a human looks at them.

**Don't use it for:** a one-off script, a throwaway prototype, or as a replacement for your actual documentation/wiki — DecisionsSearch complements structured docs, it doesn't replace them (see `.decisionssearch/` files below).

## Quick Start

### Prerequisites

- Python >= 3.11
- [uv](https://docs.astral.sh/uv/) (recommended) or pip
- Docker (for Neo4j + Qdrant in full mode)

### Install

```bash
git clone https://github.com/Renzo-Tognella/DecisionsSearch.git
cd DecisionsSearch
uv sync
```

### Configure

```bash
cp .env.example .env
cp config/decisionssearch.yaml.example config/decisionssearch.yaml
```

Edit `.env` with your API keys and `config/decisionssearch.yaml` for your setup.

### Run

**Full mode** (Neo4j + Qdrant, recommended — richer search, graph traversal):

```bash
# Start infrastructure
docker compose up -d

# Bootstrap vector collection (idempotent — safe to re-run)
uv run python -m scripts.bootstrap_qdrant

# Start server (HTTP + MCP on port 8000)
uv run decisionssearch
```

The current HTTP/MCP server uses the full composition and requires Neo4j +
Qdrant. The `mode` field is retained for configuration compatibility; setting
`mode: light` does not currently activate a JSONL-only server path. JSONL is
used for landing zone, snapshots and local operational state; the benchmark
has a separate explicit local backend.

### Verify

```bash
# MCP endpoint responds (406 without proper MCP headers is expected — it means the route is alive)
curl http://localhost:8000/api/health   # real health path lives under /api
curl http://localhost:8000/mcp/
```

## Connecting Your Agent

**Local, stdio (simplest for personal use):**

```json
{
  "mcpServers": {
    "decisionssearch": {
      "command": "uv",
      "args": ["--directory", "/path/to/DecisionsSearch", "run", "decisionssearch-mcp"]
    }
  }
}
```

**Local or remote, HTTP (needed if the server already runs as a persistent process, e.g. via `uv run decisionssearch`):**

```json
{
  "mcpServers": {
    "decisionssearch": { "url": "http://localhost:8000/mcp" }
  }
}
```

Drop this into a project's `.mcp.json` (project-scoped) or your global MCP config. **MCP servers are only picked up when a session starts** — after adding or changing this config, open a new agent session in that project rather than expecting the tools to appear mid-session.

### Project-scoped memory

For memory tools, `project` is optional. When omitted, DecisionsSearch uses the
name of the Git repository root (or the current folder for a non-Git workspace)
as the project partition. New memories receive that project value, and
`memory.query`/`memory.find_duplicates` filter Qdrant and Neo4j by it before the
hybrid ranking and RRF fusion. Set `DECISIONSSEARCH_PROJECT` when the server is
started outside the workspace or when a deployment needs an explicit partition.

This is a logical memory partition, not an authentication boundary. The
resolution order is:

1. `DECISIONSSEARCH_PROJECT`, when configured;
2. an explicit `project` argument, useful for imports and batch jobs;
3. the Git repository root name;
4. the current folder name when no Git root exists.

Omitting `project` is the recommended agent workflow. The resolved value is
written with the memory and is passed to every retrieval branch. A query first
filters the project in the canonical ledger, Qdrant, and Neo4j, then performs
dense, sparse, and structural retrieval, RRF fusion, and optional reranking.

## How memory works

DecisionsSearch does not treat a transcript, diff, or embedding as a memory by
itself. A memory is durable, typed knowledge with a project, evidence, context,
and a reason to remain useful after the current task.

```text
workspace → project tag → raw event → sanitization → extraction
         → admission gates → proposal/approval → canonical ledger
         → outbox → Qdrant search projection
```

The write path is deliberately selective:

- `memory.ingest_raw` stores the sanitized source in the landing zone and asks
  the extractor for typed candidates;
- the admission chain requires a project and evidence, checks duplicates or
  refinements, validates category-specific context, and evaluates weight;
- with the canonical ledger enabled, the agent creates a proposal with a
  before/after preview, field diff, evidence, and `preview_hash`;
- an operator or trusted policy approves the proposal; the apply uses expected
  heads (CAS) and creates an immutable revision, head, lineage, and outbox event;
- the materializer publishes the active head to Qdrant idempotently. Qdrant is a
  derived retrieval index, never the source of truth.

The canonical model separates identity from content: `MemoryFamily` is the
stable logical memory, `MemoryRevision` is an immutable version, and
`MemoryHead` points to the published version for a scope and branch. Evidence,
aliases, relations, validity windows, and audit events remain queryable. Updating
a title or summary therefore creates a new revision instead of silently erasing
history.

On reads, the resolved project is applied before candidate generation. Dense
embeddings find semantic similarity, sparse retrieval preserves exact technical
terms, and the graph contributes structural context. These ranked lists are
combined by RRF; optional spreading activation, composite scoring, and reranking
then refine the candidates. A high relevance score is a retrieval signal, not
proof that a claim is true.

For the complete lifecycle, data model, project isolation, and operational
limits, see [`docs-public/relatorio_memoria.md`](docs-public/relatorio_memoria.md),
[`ARCHITECTURE.md`](ARCHITECTURE.md), and the public PDF
[`docs-public/relatorio_resultados.pdf`](docs-public/relatorio_resultados.pdf).

### Public documents

- [`docs-public/instalacao.md`](docs-public/instalacao.md) — supported installation and operation;
- [`docs-public/relatorio_memoria.md`](docs-public/relatorio_memoria.md) — memory lifecycle and project partitioning;
- [`docs-public/relatorio_resultados.md`](docs-public/relatorio_resultados.md) — reproducible evidence and current limits;
- [`docs-public/instalacao.pdf`](docs-public/instalacao.pdf) and [`docs-public/relatorio_resultados.pdf`](docs-public/relatorio_resultados.pdf) — visual PDF versions.

## Using DecisionsSearch Day-to-Day: The Skills Suite

Connecting the MCP server gives your agent 40+ raw tools (`memory.query`, `memory.pr.create`, `graph.project.create`, ...) — powerful, but not something you want to call by hand every time. `skills-memory/` ships a suite of 13 agent skills that wrap those tools into a workflow:

| Step | Skill | What it does |
|------|-------|---------------|
| 1. Setup (once per project) | `decisionssearch-init` | Q&A about your business/domain → writes `.decisionssearch/{business,architecture,code-patterns}.md`, installs the other 12 skills into the project, registers the project node in the graph |
| 2. End of every PR | `decisionssearch-capture` | One sweep of the session + PR diff → detects what's worth remembering (rule? decision? pattern?) → creates the right memory nodes, with your confirmation, and links them |
| 3. Anytime | `query-memory` | "Have we done something like this before?" — semantic search across PRs, rules, decisions, patterns, and past task episodes |
| 3. Anytime | `rule-blame` / `architecture-blame` / `code-blame` | "How did this get here?" — walks the chain of PRs, decisions, and superseded versions for a rule, an architectural choice, or a file |
| 4. Periodically | `decisionssearch-update` | Syncs `.decisionssearch/*.md` with what the graph has learned since the last sync — proposes a diff, you approve it |

Install with `decisionssearch-init` in a fresh project; the suite ships its own README, a canonical template every skill follows, and a golden-set test file per skill (plus a consolidated cross-skill routing test) — see [`skills-memory/README.md`](skills-memory/README.md).

## Usage Modes

### Mode 1: Personal Memory (Local)

Run DecisionsSearch locally. Your AI agent connects via MCP stdio or HTTP (see above).

The local server uses the same full composition as the shared server. For a
reproducible zero-infrastructure regression, use the benchmark's explicit local
backend rather than treating JSONL as a canonical memory store.

```yaml
# config/decisionssearch.yaml
mode: full
data_dir: data
```

Full mode (Neo4j + Qdrant) provides graph traversal and hybrid
vector+structural queries.

### Mode 2: Shared Team Memory (Server)

Deploy DecisionsSearch on a server. All team members' agents read/write to the same knowledge base.

```bash
# On your server
uv run decisionssearch --host 0.0.0.0 --port 8000
```

Team members point their agents to the shared MCP endpoint:

```json
{
  "mcpServers": {
    "decisionssearch": { "url": "https://your-domain.example/mcp" }
  }
}
```

Everyone's agent sessions contribute memories. The daily scan job automatically ingests GitHub PRs and cards, building a shared knowledge graph of the team's decisions, patterns, and architectural history.

### Mode 3: Autonomous Error Investigator

Configure in `config/decisionssearch.yaml`:

```yaml
agent:
  provider: codex          # opencode | codex | claude | zai | openrouter
  timeout: 600
  codex:
    model: gpt-4o
    api_key: ${OPENAI_API_KEY}

safety:
  min_confidence: 0.7
  max_auto_fixes_per_hour: 3
  blocked_paths:
    - auth/
    - security/
    - .env

notifications:
  slack:
    enabled: true
    webhook_url: ${SLACK_WEBHOOK_URL}
```

Point your CI/CD pipeline to send errors:

```bash
# GitHub Actions example
curl -X POST https://your-domain.example/api/webhook/errors \
  -H "Content-Type: application/json" \
  -H "X-Signature: $(echo -n "$body" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET")" \
  -d '{
    "error_type": "RuntimeError",
    "error_message": "Null pointer in UserService",
    "stack_trace": "at UserService.java:42\nat Controller.java:15",
    "service": "api",
    "environment": "production"
  }'
```

DecisionsSearch will:
1. Ingest the error and find which files are affected
2. Search for PRs that recently modified those files (suspects)
3. Run a coding agent to investigate root cause
4. If confidence is high enough, create a fix PR
5. Notify the team via Slack

## Memory Categories

Every memory node has a `category` that determines what fields are required and enforced by admission gates before it's accepted into the graph:

| Category | Created via | Required beyond the basics | Use it for |
|----------|-------------|------------------------------|-------------|
| `PRMemory` | `memory.pr.create` | `pr_url`, `work_item_url` | What a PR changed and why |
| `BusinessRule` | `memory.manual.create` | `domain` (non-empty) | Durable domain truth that outlives any single PR |
| `ArchitecturalDecision` | `memory.manual.create` | `architectural_rationale`, `alternatives_considered` | A design choice, motivation, trade-offs, and rejected alternatives |
| `DesignRule` | `memory.manual.create` | evidence and durable context | A durable coding, structure, or interaction convention |
| `DesignPattern` | `memory.manual.create` | evidence of reuse | A recurring design or interaction solution |
| `CodePattern` | `memory.manual.create` | `examples` (non-empty) | A reusable implementation convention, with a concrete example |
| `FeatureDescription` | `memory.upsert` / extraction | `objective`, `trigger`, or `related_files` | How a feature or workflow starts, behaves, and ends |
| Episode | `memory.episode.create` | `task_description`, `outcome` (`completed`/`failed`/`partial`) | What was tried in a specific task and what happened — not a `MemoryItem`, links via `related_memory_ids` |
| Procedure | `memory.procedure.create` | `steps` | A repeatable runbook for a type of task |

Relations between `MemoryItem`s go through two distinct, validated APIs — don't mix them up:
- **PR → memory** (`memory.pr.link_memory`): `IMPLEMENTS`, `EVIDENCES`, `MODIFIES`.
- **memory → memory** (`memory.link`): `RELATED_TO`, `DEPENDS_ON`, `REFINES`, `DEPRECATES`, `CONFLICTS_WITH`, `EVOLVES_FROM`.

Superseding a rule or decision is `memory.deprecate(memory_id, replaced_by, rationale)`, not a manual link — it proposes `(new)-[:DEPRECATES]->(old)` and applies it only after operator approval.

## MCP Tools

The server exposes 40+ MCP tools. Key categories:

| Category | Tools | Description |
|----------|-------|--------------|
| **Memory** | `memory.ingest_raw`, `memory.query`, `memory.get`, `memory.upsert`, `memory.manual.create`, `memory.find_duplicates` | Core ingestion and retrieval; project defaults to the agent workspace folder |
| **Relations** | `memory.link`, `memory.deprecate` | Typed relationships between memories |
| **Context** | `memory.context`, `memory.reflect`, `memory.capture_commit` | Pre-task loading, post-task extraction, and post-commit verification |
| **PR Memory** | `memory.pr.create`, `memory.pr.query`, `memory.pr.link_memory`, `memory.pr.linked_memories`, `memory.linked_prs` | PR-to-memory linking |
| **Catalog** | `graph.project.*`, `graph.category.*`, `graph.domain.*`, `graph.relation.*` | Graph catalog management |
| **Episodic** | `memory.episode.create`, `memory.episode.query` | Task outcome memories |
| **Procedural** | `memory.procedure.create`, `memory.procedure.query` | Reusable procedures |
| **Errors** | `errors.ingest`, `errors.list`, `errors.get_investigation` | Error pipeline |
| **System** | `system.jobs.list`, `system.jobs.run`, `system.jobs.history` | Scheduler control |
| **Admin** | `memory.consolidate`, `memory.reconcile`, `memory.feedback` | Maintenance |

## Configuration Reference

All config in `config/decisionssearch.yaml`. Environment variables via `${VAR:default}` syntax.

| Variable | Default | Description |
|----------|---------|--------------|
| `mode` | `full` | `full` (Neo4j + Qdrant); `light` is a legacy compatibility label, not a JSONL-only server |
| `LLM_PROVIDER` | `gemini` | LLM provider: openai, zai, openrouter, gemini |
| `LLM_API_KEY` | — | Generic API key for all providers |
| `EMBEDDING_PROVIDER` | inherits `LLM_PROVIDER` | Optional separate embedding provider, including openrouter |
| `OPENROUTER_API_KEY` | — | OpenRouter key for chat, embeddings, reranking, and the autonomous worker |
| `OPENROUTER_RERANK_MODEL` | `qwen/qwen3-reranker-8b` | Native OpenRouter reranker model |
| `OPENROUTER_RERANK_ZDR` | `true` | Restricts reranking to Zero Data Retention endpoints |
| `OPENROUTER_EMBEDDING_ZDR` | `true` | Restricts OpenRouter embedding requests to ZDR endpoints |
| `DECISIONSSEARCH_LEDGER_BACKEND` | `neo4j` | Canonical ledger adapter; `memory` is restricted to tests/regressions |
| `DECISIONSSEARCH_ENABLE_OPERATOR_TOOLS` | `false` | Explicitly enables MCP approval/rejection/apply tools |
| `DECISIONSSEARCH_PROJECT` | unset | Optional project partition override when the process is outside the workspace |
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j connection |
| `NEO4J_PASSWORD` | — | Neo4j password |
| `QDRANT_HOST` | `localhost` | Qdrant host |
| `QDRANT_PORT` | `6333` | Qdrant port |
| `SPARSE_SEARCH_ENABLED` | `false` | Enables BM25 sparse retrieval alongside dense vectors on a compatible collection |
| `RERANKER_PROVIDER` | `none` | none, cohere, jina, cross-encoder, openrouter, openai |

See `config/decisionssearch.yaml.example` for the complete reference with all options.

## Architecture

Application code lives directly under `src/` (`src/domain`, `src/application`,
`src/infrastructure`, `src/interfaces`, and `src/bootstrap`). Packaging maps
that physical layout to the stable public namespace `decisionssearch.*`.

See [ARCHITECTURE.md](./ARCHITECTURE.md) for detailed technical documentation with diagrams covering:
- Memory ingestion pipeline (5-gate admission)
- Project resolution and project-first filtering
- Canonical ledger, approval, revision, and outbox lifecycle
- Hybrid search pipeline (RRF fusion + spreading activation)
- Error investigation flow (agent worker + safety gates)
- Graph data model
- Deployment topologies

See [LIMITATIONS.md](./LIMITATIONS.md) for the current implementation gaps,
their evidence, and the proposed path to resolve them.

## Post-commit memory capture

The versioned `.githooks/post-commit` hook collects `HEAD`, changed files, the
open PR for the current branch (when `gh` is available), and the session from
`DECISIONSSEARCH_SESSION_FILE` or `.decisionssearch/session.md`. It sends that context to the
LLM with an explicit instruction to check for durable knowledge before creating
memory. `no_memory` is a valid result, so trivial changes are not forced into
memory. Accepted candidates pass the admission gates and capture is idempotent
per commit + PR + session.

Install it once from the repository root:

```bash
uv run python -m scripts.install_git_hooks
```

The hook runs in the background and is fail-open, so an OpenRouter, GitHub,
Qdrant, or Neo4j failure never blocks a commit. To test synchronously:

```bash
DECISIONSSEARCH_COMMIT_MEMORY_HOOK_SYNC=1 \
DECISIONSSEARCH_SESSION_FILE=.decisionssearch/session.md \
git commit -m "my change"
```

Agents that already have the context can call `memory.capture_commit` with
`session_context`, `commit_sha`, and the PR metadata. For diagnostics, run
`uv run python -m scripts.post_commit_memory_hook --repo . --dry-run`.

## Development

```bash
# Install dev dependencies
uv sync --group dev

# Run tests
uv run pytest tests/ -q --ignore=tests/e2e

# Lint
uv run ruff check .

# E2E tests (requires running infrastructure)
RUN_E2E=1 uv run pytest tests/e2e -q
```

## License

MIT
