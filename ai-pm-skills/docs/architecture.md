# Architecture Design

## Three-Phase Hybrid Architecture

ai-pm-skills employs a three-phase pipeline to decompose a platform-level product idea into ten executable layers.

### Phase 1: V1 Forward Decomposition

Top-down layer-by-layer expansion. Each node is decomposed by the level-appropriate prompt template, simultaneously generating hyperspace vector tags.

**Levels:**
- L0 Vision -> L1 Subsystems -> L2 Modules -> L3 Features -> L4 API
- L5 Tech -> L6 Design -> L7 Skeleton -> L8 Code -> L9 Deploy

**Per-node outputs:** detail.md, summary.md, vector.json

### Phase 2: V3 Hyperspace Clustering + Comparator Agent

At checkpoint levels (L2, L4, L6, L9), the system pauses decomposition to analyze all nodes at the current level for reuse opportunities.

1. Structural clustering via set operations on tags
2. Semantic clustering via DBSCAN on summary embeddings
3. Comparator Agent analyzes each cluster for merge strategy
4. Challenger Agent adversarially validates merge plans

### Phase 3: V2 Local Backpropagation

Approved merge decisions are propagated upward through the tree:
- Create shared component nodes
- Invalidate merged duplicate nodes
- Update ancestor summaries
- Mark nodes for re-decomposition if heavily affected

## Context Management

Every LLM call is bounded to 100-150K tokens, composed of four layers:

| Layer | Budget | Source |
|-------|--------|--------|
| Global summary | <=10K | project/files/global_summary.md |
| Ancestor chain | <=20K | Parent chain summaries |
| Shared interfaces | <=30K | Referenced component interfaces |
| Current task | <=60K | Node detail.md |

## Storage Architecture

| Store | Purpose | Technology |
|-------|---------|------------|
| Structured data | Nodes, tags, edges | SQLite (WAL mode) |
| Vector search | Semantic similarity | ChromaDB |
| Full content | Detail/summary files | File system |

## State Machine

```
INIT -> DECOMPOSING -> [checkpoint?] -> CLUSTERING -> COMPARING -> CHALLENGING -> BACKPROP -> DECOMPOSING -> ... -> DONE
```

All state transitions are persisted to `state.json` for checkpoint/resume support.
