# ai-pm-skills

An AI Product Manager system built as a set of [OpenClaw](https://github.com/anthropics/openclaw) Skills. Takes a product idea and transforms it into a fully decomposed, cross-aligned execution plan through adaptive interview, forward decomposition, and backward optimization.

Designed for complex projects that exceed single-LLM-call context limits, with structured data management (SQLite + ChromaDB) and multi-level compaction to keep every LLM call under budget.

## Architecture: Forward-Backward Pipeline

The system uses a two-pass architecture that separates concerns for better quality and lower cost:

```
Idea → Adaptive Interview → Requirements → Forward Decomposition → Backward Optimization → Report
                                              (independent)            (cluster-first)
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
- **9-axis hyperspace tags** attached to every node for later clustering.
- **Early compaction** of finished subtrees to free context budget.

Why no alignment during decomposition? It avoids O(N^2) cross-comparison costs at every step. Forward pass runs in parallel with minimal context per call (only parent + project summary needed).

### Phase 2: Backward Optimization (Cluster-First)

Once all leaf nodes are done, a single bottom-up optimization pass runs:

```
1. Cluster leaf nodes          → O(N) via tag Jaccard + DBSCAN
2. Compare cluster reps        → O(K^2) instead of O(N^2)
3. Detailed intra/cross-cluster alignment → filtered by step 2
4. Create edges with contracts  → 6 edge types, full lifecycle
5. Bottom-up parent re-derivation → constraints propagate upward
6. Root consistency check       → strategic alignment verification
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

## Quick Start

```bash
# 1. Clone and setup
git clone https://github.com/anthropics/ai-pm-skills.git
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
python cli.py cluster run <project> <depth>     # Jaccard-based clustering at depth
python cli.py search similar <node_id> [--n 5]  # Tag-based similarity search
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
| `ai-pm-hyperspace` | Multi-dimensional clustering (Jaccard + DBSCAN) |
| `ai-pm-comparator` | Merge strategy analysis for clusters |
| `ai-pm-challenger` | Adversarial validation of merge plans |
| `ai-pm-backprop` | Reverse propagation of optimization decisions |
| `ai-pm-context` | Context assembly with token budgets |
| `ai-pm-memory` | Cross-project pattern memory |

## Storage

| Store | Tables/Collections | Purpose |
|-------|-------------------|---------|
| **SQLite** | `nodes`, `tags`, `edges` | Structured queries, relationships |
| **ChromaDB** | `node_summaries`, `rule_fingerprints`, `project_patterns` | Vector search |
| **File system** | `detail.md`, `summary.md`, `vector.json` per node | Full content, compaction source |

### Database Schema

**nodes:** `node_id PK, project, level, parent_id FK, status, title, detail_path, summary_path, vector_path, version, compacted, constraints, created_at, updated_at`

**tags:** `(node_id, tag_key, tag_value) composite PK` — structured hyperspace tags

**edges:** `(from_id, to_id, edge_type) composite PK` + `status, strength, alignment_count, contract, from_version, to_version, created_at, updated_at`

## Data Models

```python
class NodeStatus(Enum):     # pending, active, done, invalidated
class EdgeType(Enum):        # parent, dependency, shared_ref + 6 functional types
class EdgeStatus(Enum):      # discovered, typed, specified, validated, stale, conflict
class CompactionLevel(Enum): # full, compacted, interface

@dataclass
class Node:          # id, project, level, parent_id, status, title, version, compacted, constraints
class Edge:          # from_id, to_id, edge_type, status, strength, alignment_count, contract
class HyperspaceVector:  # 9-axis: domain, entities, patterns, api_shape, tech_traits, actors, nfr, biz_metrics, rule_fingerprint
class Cluster:       # id, members, shared_features, suggested_action
class MergePlan:     # cluster_id, strategy, affected_nodes, challenger_verdict
```

## Runtime Data

All runtime data lives in `~/.openclaw/workspace/ai-pm-data/`:

```
ai-pm-data/
├── config.json                    # Embedding provider, model selection, budgets
├── ai_pm.db                       # SQLite database
├── vector_store/                  # ChromaDB persistence
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

136 tests covering:
- **Prompt templates**: loading, rendering, vector schema validation
- **Response parsing**: JSON extraction from LLM responses
- **Vector extraction**: hyperspace tag generation
- **Database CRUD**: nodes, tags, edges (insert, get, update, delete)
- **Edge management**: 6 types, lifecycle, alignment tracking, stale marking, GC
- **Compaction**: summary + constraints update and persistence
- **Snapshots**: save/load with versioning
- **Checkpoints**: save/rollback with diff-based undo
- **Reconciliation**: file system vs DB consistency
- **Clustering**: Jaccard-based clustering at depth levels
- **Similarity search**: tag-based nearest neighbors
- **CLI commands**: all command handlers with JSON output verification
- **Interview flow**: dimension-by-dimension, phase gating, confirmation
- **Context assembly**: budget tracking, truncation, assembly

Tests use `tempfile` for isolation and do not require external services (no LLM calls, no Ollama, no network).

## Design Decisions

1. **Forward-backward separation** — Independent decomposition avoids O(N^2) alignment at every step. Cost reduction ~35%, speed improvement ~58% (parallelizable), fidelity improvement ~25%.

2. **Cluster-first backward optimization** — Clustering leaf nodes first (O(N)) then comparing cluster representatives (O(K^2)) reduces backward pass from O(N^2) to O(K^2 + N).

3. **Adaptive depth, not fixed layers** — Decomposition depth is driven by content complexity. Some branches finish at depth-2, others at depth-12.

4. **Constraints survive all compaction** — Negative requirements are preserved at every compression level to prevent downstream assumptions from lossy summaries.

5. **Always compress from original** — Compaction always reads the full version, never re-compresses from a previous compaction, preventing telephone-game information loss.

6. **Event-driven edge lifecycle** — Edges track `alignment_count`. If two nodes keep re-aligning without converging (>4 attempts), the system forces a conflict and escalates to the user.

7. **Quality floor** — If minimum context (850 tokens) cannot be loaded, the system stops rather than producing unreliable output.

## License

MIT
