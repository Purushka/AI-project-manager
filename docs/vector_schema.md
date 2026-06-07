# Hyperspace Vector Schema

Each node carries weighted multi-axis tags stored in the `tags` table as (node_id, key, value) tuples. Axes have discriminative weights that control their influence on clustering.

## Axes and Weights

| Axis | Weight | Type | Purpose |
|------|--------|------|---------|
| domain | 3.0 | string | Business domain (strongest clustering signal) |
| entity | 2.5 | string | Core data entities involved |
| pattern | 2.0 | string | Architecture/design patterns |
| actor | 1.5 | string | User roles or system actors |
| nfr | 1.0 | string | Non-functional requirements |
| biz_metrics | 1.0 | string | Business metrics this node affects |
| tech_stack | 0.8 | string | Technology layer (frontend/backend/ai-model/etc) |
| data_sensitivity | 0.5 | string | public / internal / sensitive / critical |
| revenue_impact | 0.5 | string | direct / indirect / supporting / none |
| dependency | 0.4 | string | independent / light-dependency / heavy-dependency |
| complexity | 0.3 | string | low / medium / high / very-high |
| user_facing | 0.3 | string | user-facing / internal / hybrid |
| timeline_priority | 0.2 | string | mvp / phase-1 / phase-2 / phase-3 |

Weights reflect discriminative power: `domain=3.0` means "same domain is a strong reuse signal", while `complexity=0.3` means "same complexity is nearly meaningless for clustering."

## Examples

```
domain=payments, entity=Order, entity=Payment, pattern=event-driven,
actor=consumer, nfr=idempotent, tech_stack=backend, complexity=medium,
data_sensitivity=critical, revenue_impact=direct, timeline_priority=mvp
```

A single node can have multiple values per axis (multiple entity tags, multiple pattern tags, etc.).

## Clustering Usage

### Weighted Jaccard (Tag-based)

Per-axis Jaccard weighted by axis weights. Two nodes with matching `domain` tags contribute 3x more to similarity than matching `complexity` tags.

```
similarity = Σ(weight_i × jaccard(axis_i_A, axis_i_B)) / Σ(weight_i)
```

Threshold: 0.35 (pairs below this are never clustered together).

### Adaptive DBSCAN (Embedding-based)

Node summaries embedded in ChromaDB. DBSCAN with adaptive eps:
- `eps = median(pairwise_cosine_distance) × 0.7`
- Clamped to [0.1, 0.5]

### Hybrid

Tag clusters and semantic clusters are merged. If a semantic cluster is a superset of a tag cluster, the tag cluster is subsumed.
