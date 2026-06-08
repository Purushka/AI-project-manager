# ai-pm-skills

An AI Product Manager system built as a set of [OpenClaw](https://github.com/anthropics/openclaw) Skills. Takes a product idea and transforms it into a fully decomposed, cross-aligned execution plan through adaptive interview, forward decomposition, and backward optimization.

Designed for complex projects that exceed single-LLM-call context limits, with structured data management (SQLite + ChromaDB), RAG knowledge base, write-lock concurrency control, and multi-level compaction to keep every LLM call under budget.

## Architecture: Forward-Backward Pipeline

The system uses a two-pass architecture that separates concerns for better quality and lower cost:

```
Idea → Adaptive Interview → Requirements → Forward Decomposition → Backward Optimization → Export
                                              (independent)            (content-rewriting)
```

### Phase 0: Adaptive Interview

The agent evaluates a **10-dimension completeness checklist** (weighted 1-3) against user input. It self-iterates: asks targeted questions about the weakest dimensions, re-evaluates after each answer, and only produces a requirements document when the weighted score reaches 70 (or after 8 rounds with assumptions marked).

| Dimension | Weight | Threshold |
|-----------|--------|-----------|
| Users & Scenarios | 3 | 2+ roles + scenarios + pain points |
| Core Value | 3 | Clear problem + why users care |
| MVP Scope | 3 | Must-do + explicit exclusions |
| Market & Competition | 2 | Rough size + 2+ competitors |
| Business Model | 2 | Revenue model + rough pricing |
| Core User Flow | 2 | Registration to first value |
| Tech Constraints | 2 | Stack + integrations + performance |
| Growth | 1 | 1+ acquisition channel |
| Team & Resources | 1 | Rough headcount + timeline |
| Success Metrics | 1 | 1+ quantified metric |

### Phase 1: Forward Decomposition

**Independent parallel decomposition with NO cross-node alignment.** Each branch expands from root to leaf nodes purely based on content complexity.

- **Layers = granularity, not semantics.** There are no fixed layer meanings. Depth-0 is the coarsest view, depth-N is executable (one person, one sprint).
- **Breadth-first + sprint scheduling.** All branches advance together at each depth level.
- **Weighted hyperspace tags** attached to every node for later clustering. Axes weighted by discriminative power (domain=3.0, entity=2.5, pattern=2.0, ... complexity=0.3).
- **Early compaction** of finished subtrees to free context budget.
- **Knowledge Base sync** — every node creation/update/deletion auto-syncs to the shared RAG knowledge base.

Why no alignment during decomposition? It avoids O(N^2) cross-comparison costs at every step. Forward pass runs in parallel with minimal context per call (only parent + project summary needed).

### Phase 2: Backward Optimization (Content-Rewriting)

Once all leaf nodes are done, a bottom-up optimization pass runs that **actually rewrites node content** (not just creates edges):

```
1. Hybrid clustering              → weighted Jaccard + average-link agglomeration + semantic boost
2. Detect overlap between nodes   → LLM identifies shared content (a+b vs b+c)
3. Extract shared components      → create new shared node for common content
4. Rewrite original nodes         → remove extracted content, add references
5. Resolve stuck conflicts        → alignment_count > 4 → LLM concrete resolution
6. Create typed edges             → 6 edge types with contracts
7. Re-derive parent summaries     → bottom-up from updated children
8. Root consistency check         → strategic alignment verification
```

This reduces backward pass complexity from O(N^2) to O(K^2 + N), where K = number of clusters (typically K << N).

**6 Edge Types:**

| Type | Meaning | Alignment Action |
|------|---------|-----------------|
| `calls` | A calls B's interface | Define API contract |
| `produces_consumes` | A produces, B consumes | Unify event schema |
| `shares` | A and B share a resource | Extract shared component |
| `presents` | A is B's UI | Frontend-backend API alignment |
| `constrains` | A's requirements limit B | Constraint propagation |
| `measures` | A measures B's performance | Metric definition consistency |

**Edge Lifecycle:** `discovered → typed → specified → validated → (stale → re-validated or pruned)`

**Convergence Control:** If two nodes keep re-aligning without converging (alignment_count > 4), the system generates a concrete resolution via LLM and applies it — no infinite loops.

### Knowledge Base (RAG)

A shared knowledge base accessible to all nodes, backed by SQLite + ChromaDB vector search:

- **Full-node sync** — every node CRUD operation auto-syncs content to the KB with embedding index
- **Semantic search** — nodes can query background knowledge via embedding similarity
- **Topic mutex** — same topic can only have one active entry; conflicts force amendment workflow
- **Amendment workflow** — non-owners propose changes → owner accepts/rejects → content merged
- **Staleness tracking** — entries marked stale when source node changes; refreshed on next access

```python
# Any node can query the knowledge base
results = kb.semantic_search("authentication flow", project="myproject", top_k=5)

# Auto-sync on node changes (called internally by db operations)
kb.sync_node(node_id, project, title, content)
```

### Write Locks

TTL-based resource locks prevent concurrent modification of the same data:

- **Node-level locks** — backward optimization acquires lock before rewriting content
- **TTL expiry** — stale locks auto-expire (default 300s) to prevent deadlocks
- **Caller identity** — each module identifies itself; only the lock holder can release
- **Context manager** — `with db.locked(resource_id, caller_id):` for safe acquire/release

```python
with db.locked("node_abc123", "backprop"):
    db.update_node_content("node_abc123", new_detail, new_summary, "backprop")
```

### Compaction Engine

3-level compression keeps context under budget while preserving critical information:

| Level | ~Size | Content |
|-------|-------|---------|
| full | ~500t | Complete description, decisions, full tags |
| compacted | ~150t | Summary + public interfaces + constraints + key decisions |
| interface | ~80t | Title + interface signatures + constraints |

**Constraints survive ALL compression levels.** Negative requirements ("only supports X", "must not Y") are never lost.

### Context Budget

Every LLM call operates within a strict token budget:

- **Tier 1 (mandatory, ~850t):** Project summary + current node full + parent compacted
- **Tier 2 (important, ~800t):** Top-5 related node interfaces + contracts
- **Tier 3 (auxiliary):** Sibling titles + ancestor interfaces

**Quality floor:** If Tier 1 can't fit, the system stops and reports rather than operating with insufficient context.

## Demo: Full Pipeline Run

The `demo/` directory contains the output from a complete pipeline run on an "AI Entrepreneurship Platform" project — from seed idea to 533 decomposed nodes with execution tickets.

**Pipeline stats:**
- Duration: ~52 minutes (3 parallel backward workers)
- Total nodes: 533 (451 original + 82 shared components)
- Depth distribution: L0:1 → L1:12 → L2:62 → L3:235 → L4:223
- 383 leaf-level execution tickets (one person, one sprint each)
- 164 nodes rewritten to reference shared components
- 50 parent summaries re-derived bottom-up
- 96 clusters found, 36 rejected by merge guard, 60 processed
- 355 LLM calls, 900 embedding calls

**Files:**
| File | Description |
|------|-------------|
| `final_report.md` | Full tree: all nodes, execution tickets, shared components |
| `full_snapshot.json` | Complete tree data (all 533 nodes) |
| `00_pipeline_summary.json` | Run metadata and timings |
| `01_forward_decomposition.json` | Forward pass output |
| `02_clustering.json` | Cluster assignments (96 clusters) |
| `03_backward_optimization.json` | Shared components and rewrite log |
| `pipeline_*.log` | Full pipeline execution log |

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/Purushka/AI-project-manager.git
cd ai-pm-skills
bash setup.sh

# 2. Install skills to OpenClaw
bash install_skills.sh

# 3. Run tests
python -m pytest tests/ -v
```

### Requirements

- Python 3.11+
- Ollama (optional, for local embeddings)
- An LLM API key (configured in `~/.openclaw/workspace/ai-pm-data/config.json`)

## CLI Reference

All commands output JSON for agent consumption. Path: `cli.py`

### Project Management

```bash
python cli.py project init <name> "<idea>"     # Create project + root node
python cli.py project status <name>             # Show node counts per level
python cli.py project list                      # List all projects
```

### Node Operations

```bash
python cli.py node add <project> <depth> "<title>" [--parent <id>]
python cli.py node get <id>
python cli.py node children <id>
python cli.py node ancestors <id>
python cli.py node status <id> <pending|active|done|invalidated>
python cli.py node list <project> [--level <n>]
```

### Hyperspace Tags

```bash
python cli.py tag set <node_id> key1=val1 key2=val2 ...
python cli.py tag get <node_id>
python cli.py tag find <key> <value>
```

### Edge Management

```bash
python cli.py edge add <from> <to> <type> [--strength <0.0-1.0>]
python cli.py edge list <node_id>
python cli.py edge update <from> <to> <type> --status <s> [--strength <f>] [--contract "<text>"]
python cli.py edge gc <project>                 # Garbage collect weak/orphan/stale edges
```

### Clustering & Search

```bash
python cli.py cluster run <project> <depth>     # Weighted Jaccard + average-link agglomeration
python cli.py search similar <node_id> [--n 5]  # Tag-based similarity search
```

### Export

```bash
python cli.py export <project> [-o output.md]   # Assemble structured report from tree
python cli.py export <project> --polish         # Per-node LLM refinement pass
```

### State Management

```bash
python cli.py compact <node_id> --summary "<text>" --constraints "<json>"
python cli.py snapshot save <project>
python cli.py snapshot load <project> [--version <n>]
python cli.py checkpoint save <project> <iteration> --diff '<json>'
python cli.py checkpoint rollback <project> <iteration>
python cli.py reconcile <project>               # File system <-> DB consistency check
```

## Skills

| Skill | Purpose |
|-------|---------|
| `ai-pm-core` | Main orchestrator, state machine, phase dispatch |
| `ai-pm-decomposer` | Forward decomposition with prompt templates per level |
| `ai-pm-hyperspace` | Hybrid clustering (weighted Jaccard + average-link + semantic boost) |
| `ai-pm-comparator` | Merge strategy analysis for clusters |
| `ai-pm-challenger` | Adversarial validation of merge plans |
| `ai-pm-backprop` | Content-rewriting backward optimization with write locks |
| `ai-pm-context` | Context assembly with token budgets |
| `ai-pm-memory` | Cross-project pattern memory |

## Storage

| Store | Tables/Collections | Purpose |
|-------|-------------------|---------|
| **SQLite** | `nodes`, `tags`, `edges`, `write_locks`, `knowledge`, `knowledge_refs`, `knowledge_amendments` | Structured queries, relationships, concurrency |
| **ChromaDB** | `node_summaries`, `rule_fingerprints`, `project_patterns`, `knowledge_base` | Vector search |
| **File system** | `detail.md`, `summary.md`, `vector.json` per node | Full content, compaction source |

### Database Schema

**nodes:** `node_id PK, project, level, parent_id FK, status, title, detail_path, summary_path, vector_path, version, compacted, constraints, created_at, updated_at`

**tags:** `(node_id, tag_key, tag_value) composite PK` — weighted hyperspace tags

**edges:** `(from_id, to_id, edge_type) composite PK` + `status, strength, alignment_count, contract, from_version, to_version, created_at, updated_at`

**write_locks:** `resource_id PK, caller_id, acquired_at, expires_at` — TTL-based concurrency control

**knowledge:** `id PK, project, topic (UNIQUE per project), content, owner_node_id, status, embedding_id, created_at, updated_at`

**knowledge_amendments:** `id PK, knowledge_id FK, proposer_node_id, proposed_content, reason, status, resolved_at, created_at`

## Data Models

```python
class NodeStatus(Enum):     # pending, active, done, invalidated
class EdgeType(Enum):        # parent, dependency, shared_ref + 6 functional types
class EdgeStatus(Enum):      # discovered, typed, specified, validated, stale, conflict
class CompactionLevel(Enum): # full, compacted, interface

@dataclass
class Node:          # id, project, level, parent_id, status, title, version, compacted, constraints
class Edge:          # from_id, to_id, edge_type, status, strength, alignment_count, contract
class HyperspaceVector:  # multi-axis: domain, entity, pattern, actor, nfr, tech_stack, biz_metrics, ...
class Cluster:       # id, members, shared_features, suggested_action
class MergePlan:     # cluster_id, strategy, affected_nodes, challenger_verdict
```

## Runtime Data

All runtime data lives in `~/.openclaw/workspace/ai-pm-data/`:

```
ai-pm-data/
├── config.json                    # Embedding provider, model selection, budgets
├── ai_pm.db                       # SQLite database (nodes, tags, edges, locks, knowledge)
├── vector_store/                  # ChromaDB persistence (4 collections)
├── patterns/                      # Cross-project pattern JSON files
└── projects/<name>/
    ├── files/                     # Per-node detail.md, summary.md, vector.json
    ├── interview.md               # Interview transcript
    ├── doc_digest.md              # Document analysis
    ├── requirements.md            # Requirements confirmation
    ├── session_brief.md           # Cold-start context (~300 tokens)
    ├── status.md                  # Current phase + progress
    ├── snapshots/                 # Full project snapshots (versioned)
    └── checkpoints/               # Diff-based checkpoints (rollback support)
```

## Testing

```bash
python -m pytest tests/ -v
```

Tests cover:
- **Prompt templates**: loading, rendering, vector schema validation
- **Response parsing**: JSON extraction from LLM responses
- **Vector extraction**: hyperspace tag generation
- **Database CRUD**: nodes, tags, edges, write locks
- **Edge management**: 6 types, lifecycle, alignment tracking, stale marking, GC
- **Knowledge base**: CRUD, topic mutex, amendment workflow, sync, search
- **Compaction**: summary + constraints update and persistence
- **Snapshots**: save/load with versioning
- **Checkpoints**: save/rollback with diff-based undo
- **Reconciliation**: file system vs DB consistency
- **Clustering**: weighted Jaccard, semantic DBSCAN, hybrid dedup
- **Similarity search**: tag-based nearest neighbors
- **CLI commands**: all command handlers with JSON output verification
- **Export**: tree assembly, polish mode
- **Interview flow**: dimension-by-dimension, phase gating, confirmation
- **Context assembly**: budget tracking, truncation, assembly

Tests use `tempfile` for isolation and do not require external services (no LLM calls, no Ollama, no network).

## Design Decisions

1. **Forward-backward separation** — Independent decomposition avoids O(N^2) alignment at every step. Forward pass is embarrassingly parallel (each branch only needs parent + project summary). Trade-off: clustering quality in Phase 2 depends on tag vocabulary consistency across branches (see Known Limitations).

2. **Content-rewriting backward optimization** — Not just edge creation: detects overlap between nodes, extracts shared components into new nodes, rewrites originals to reference shared content. Handles the a+b / b+c → shared(b) + a + c pattern.

3. **Weighted clustering** — Axis weights (domain=3.0, complexity=0.3) replace equal-weight Jaccard. Adaptive DBSCAN eps (`median(pairwise_distance) * 0.7`, clamped to [0.1, 0.5]) replaces fixed threshold. Embedding-based semantic clustering serves as fallback when tag vocabulary diverges.

4. **Adaptive depth, not fixed layers** — Decomposition depth is driven by content complexity. Some branches finish at depth-2, others at depth-12.

5. **No alignment during forward pass; edges only in backward/maintenance** — Alignment, edge creation, and cross-node comparison happen exclusively in Phase 2 (backward optimization) and during post-delivery maintenance. Phase 1 produces no edges and no cross-branch communication.

6. **Constraints survive all compaction** — Negative requirements are preserved at every compression level to prevent downstream assumptions from lossy summaries.

7. **RAG knowledge base with topic mutex** — All nodes share a knowledge base for background context. Topic-level uniqueness prevents conflicting entries; amendment workflow handles cross-owner modifications.

8. **Write locks for concurrency** — TTL-based locks prevent two modules from simultaneously modifying the same node. Lock holder identity + automatic expiry prevent deadlocks.

9. **Always compress from original** — Compaction always reads the full version, never re-compresses from a previous compaction, preventing telephone-game information loss.

10. **Convergence control** — Edges track `alignment_count`. After 4 failed convergence attempts, the system generates a concrete LLM resolution and applies it rather than looping forever.

11. **Quality floor** — If minimum context (850 tokens of mandatory Tier 1 material) cannot fit in the model window, the system stops rather than producing unreliable output.

## Known Limitations

1. **Tag vocabulary drift** — Forward decomposition generates tags independently per branch with minimal shared context. The same concept may produce `auth` / `login` / `authentication` across branches, degrading Jaccard clustering precision. Mitigations: (a) semantic clustering via embeddings catches synonyms that tags miss; (b) future work: controlled vocabulary or post-hoc tag normalization pass before clustering.

2. **No benchmark data** — Efficiency claims (parallelizability, complexity reduction) are architectural arguments, not measured results. No production workload benchmarks exist yet.

## License

MIT
