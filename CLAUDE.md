# AI PM Skills - Project Guide

## Project Overview

ai-pm-skills is the Python CLI toolchain for the AI Product Manager system. It provides structured data management (SQLite nodes/tags/edges, snapshots, checkpoints) that the OpenClaw agent calls via shell commands. The agent's behavior is governed by `~/.openclaw/workspace/AI-PM.md`.

## Architecture: Forward-Backward Pipeline

### Phase 0: Adaptive Interview
The agent evaluates a 10-dimension completeness checklist (weighted 1-3) against user input. It self-iterates: asks targeted questions about the weakest dimensions, re-evaluates after each answer, and only produces a requirements document when the weighted score ≥ 70 (or after 8 rounds with assumptions marked).

### Phase 1: Forward Decomposition
**Independent parallel decomposition with NO cross-node alignment.** No fixed layers or layer semantics. Nodes decompose by detail granularity: depth-0 is coarsest, depth-N is executable (one person, one sprint). Breadth-first with depth-first sprints. Each node gets weighted multi-axis hyperspace tags. Only parent edges created. Completed subtrees compacted early to free context budget.

### Phase 2: Backward Optimization (Cluster-First)
Once forward pass completes, a single bottom-up optimization runs:
1. Cluster leaf nodes via tag Jaccard + DBSCAN → O(N)
2. Compare cluster representatives → O(K²) instead of O(N²)
3. Detailed intra/cross-cluster LLM alignment → only matched clusters
4. Create 6 typed edges (calls, produces_consumes, shares, presents, constrains, measures) with lifecycle tracking
5. Bottom-up parent re-derivation with constraint propagation
6. Root consistency check (strategic alignment)

### Compaction & Context Control
3-level compaction (full ~500t → compacted ~150t → interface ~80t). Constraints survive all compression levels. Always compress from original, never iteratively. Quality floor: minimum 850t context or stop.

## Context Management
Three-tier priority per LLM call. Tiers are priority bands, not token caps — the actual sizes depend on node content:
- Tier 1 mandatory (minimum ~850t, unbounded upward): project summary + current node FULL content + parent compacted. Quality floor: if this alone exceeds model window, stop.
- Tier 2 important (target ~800t): top-5 related node interfaces + edge contracts. Truncated if Tier 1 is large.
- Tier 3 auxiliary (fills remaining window): sibling titles + ancestor interfaces.

Note: "~850t" is the minimum viable context, not an allocation cap. A complex node's full content (Tier 1) may be 5K+ tokens. The system fills Tier 1 completely, then fits Tier 2/3 into whatever remains.

The `ai-pm-context` skill handles assembly and truncation.

## Directory Structure

```
ai-pm-skills/
├── CLAUDE.md              <- You are here
├── README.md              <- Project introduction
├── requirements.txt       <- Python deps
├── setup.sh               <- Environment setup script
├── install_skills.sh      <- Symlink skills to ~/.openclaw/skills/
├── .gitignore
├── skills/                <- 8 OpenClaw Skills
│   ├── ai-pm-core/        <- Main orchestrator (state machine, phase dispatch)
│   ├── ai-pm-decomposer/  <- Forward decomposer (prompt templates, LLM calls)
│   ├── ai-pm-hyperspace/  <- Clustering engine (Jaccard + DBSCAN)
│   ├── ai-pm-comparator/  <- Merge strategy analyst
│   ├── ai-pm-challenger/  <- Adversarial validator
│   ├── ai-pm-backprop/    <- Reverse propagation engine
│   ├── ai-pm-context/     <- Context assembler (token budgets)
│   └── ai-pm-memory/      <- Cross-project pattern memory
├── shared/                <- Python modules shared across all skills
│   ├── config.py          <- Config from ~/.openclaw/workspace/ai-pm-data/config.json
│   ├── db.py              <- SQLite (nodes/tags/edges tables)
│   ├── vector_store.py    <- ChromaDB (3 collections)
│   ├── embeddings.py      <- Embedding API (Ollama/OpenAI)
│   ├── llm.py             <- Claude API wrapper (per-level model, retry)
│   └── models.py          <- Dataclasses (Node, HyperspaceVector, Cluster, MergePlan)
├── tests/                 <- pytest test suite
└── docs/                  <- Design documentation
```

## Code Conventions

- **Python 3.11+** required
- **Type annotations** on all function signatures
- **Dataclasses** for data models (shared/models.py)
- **Error handling**: try/except with logging; no bare `except:`
- **Imports**: each skill script does `sys.path.insert(0, ...)` to reach `shared/`

## OpenClaw SKILL.md Format

Each skill directory contains a `SKILL.md` with:
```yaml
---
name: skill-name
description: >
  Multi-line description written like explaining a task to a colleague.
  Include trigger keywords naturally in the description.
version: 0.1.0
triggers:
  - "keyword phrase 1"
  - "keyword phrase 2"
---
```
Followed by Markdown body: trigger scenarios, workflow steps, script references, I/O spec.

## Runtime Data

All runtime data lives in `~/.openclaw/workspace/ai-pm-data/`:
- `config.json` — embedding provider, model selection, budgets
- `<project>/files/` — detail.md, summary.md, vector.json per node
- `<project>/state.json` — state machine checkpoint
- `ai_pm.db` — SQLite database
- `vector_store/` — ChromaDB persistence
- `patterns/` — cross-project pattern JSON files

## Shared Modules

The `shared/` directory contains Python modules used by all skills:
- Skills reference shared modules via `sys.path.insert(0, project_root)`
- `shared/db.py`: SQLite with 3 tables (nodes, tags, edges), WAL mode, foreign keys
- `shared/vector_store.py`: ChromaDB with 3 collections (node_summaries, rule_fingerprints, project_patterns)
- `shared/llm.py`: Anthropic SDK, per-level model selection, 3x retry with backoff
- `shared/embeddings.py`: Ollama (default) with OpenAI fallback

## Database Schema

### nodes table
`node_id TEXT PK, project, level, parent_id, status, title, detail_path, summary_path, vector_path, version, compacted, constraints, created_at, updated_at`

### tags table
`node_id, tag_key, tag_value` (composite PK) — structured hyperspace vector tags for set operations

### edges table
`from_id, to_id, edge_type` (composite PK) + `status, strength, alignment_count, contract, from_version, to_version, created_at, updated_at`

## Testing

```bash
python -m pytest tests/ -v
```

Tests cover: prompt template loading/rendering, JSON response parsing, vector extraction, database CRUD, clustering algorithms, context assembly, and token budget enforcement. Tests use tempfile for isolation and do not require external services.

## Key Design Decisions

1. **Adaptive depth, not fixed layers**: Decomposition depth is driven by content complexity. Some branches finish at depth-2, others go to depth-12. Layers are granularity levels, not semantic categories.
2. **Forward pass: zero cross-node alignment**: Branches decompose independently. No alignment during Phase 1. This makes forward pass embarrassingly parallel but relies on Phase 2 clustering to catch divergence.
3. **Backward pass: cluster-first content rewriting**: After all leaves complete, one backward optimization rewrites content (not just creates edges). Detects overlap → extracts shared components → rewrites originals.
4. **Edge lifecycle (backward/maintenance only)**: Edges and alignment are created exclusively in Phase 2 and during post-delivery maintenance. They are NOT triggered during forward decomposition. alignment_count > 4 → force resolution.
5. **Constraints survive all compaction**: Negative requirements preserved at every compression level.
6. **File-based state sharing**: SQLite + filesystem for persistence. CLI returns JSON for agent consumption. Checkpoints enable rollback. Snapshots enable session resumption.
