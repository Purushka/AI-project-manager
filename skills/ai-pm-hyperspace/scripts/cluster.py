"""AI PM Hyperspace - hybrid clustering engine.

Combines weighted tag similarity with embedding-based semantic similarity.
Tag axes are weighted by discriminative power, not equal.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from shared.config import Config, load_config
from shared.db import Database
from shared.models import Cluster, HyperspaceVector, MergeStrategy, NodeStatus

logger = logging.getLogger(__name__)

MIN_CLUSTER_SIZE = 2

# Axis weights: higher = more discriminative for clustering
AXIS_WEIGHTS = {
    "domain": 3.0,       # strongest signal — same domain = likely related
    "entity": 2.5,       # shared entities = shared data model
    "pattern": 2.0,      # shared patterns = shared architecture
    "actor": 1.5,        # same actors = same user-facing area
    "nfr": 1.0,          # non-functional overlap is weaker signal
    "tech_stack": 0.8,   # "backend" is too common to be useful
    "complexity": 0.3,   # almost no discriminative power
    "data_sensitivity": 0.5,
    "revenue_impact": 0.5,
    "user_facing": 0.3,
    "timeline_priority": 0.2,
    "dependency": 0.4,
    "biz_metrics": 1.0,
}

SIMILARITY_THRESHOLD = 0.35


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Classic unweighted Jaccard on flat sets (backward compat for tests)."""
    if not set_a and not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def weighted_jaccard(tags_a: list[tuple[str, str]], tags_b: list[tuple[str, str]]) -> float:
    """Compute weighted Jaccard similarity between two tag sets."""
    if not tags_a and not tags_b:
        return 0.0

    # Group by axis
    axes_a: dict[str, set[str]] = defaultdict(set)
    axes_b: dict[str, set[str]] = defaultdict(set)
    for k, v in tags_a:
        axes_a[k].add(v)
    for k, v in tags_b:
        axes_b[k].add(v)

    all_axes = set(axes_a.keys()) | set(axes_b.keys())
    if not all_axes:
        return 0.0

    weighted_sum = 0.0
    weight_total = 0.0

    for axis in all_axes:
        w = AXIS_WEIGHTS.get(axis, 1.0)
        set_a = axes_a.get(axis, set())
        set_b = axes_b.get(axis, set())

        if not set_a and not set_b:
            continue

        intersection = set_a & set_b
        union = set_a | set_b
        sim = len(intersection) / len(union) if union else 0.0

        weighted_sum += w * sim
        weight_total += w

    return weighted_sum / weight_total if weight_total > 0 else 0.0


def load_node_tags(
    project: str, depth: int | None, db: Database
) -> dict[str, list[tuple[str, str]]]:
    """Load tags for clustering target nodes."""
    if depth is not None:
        nodes = db.get_nodes_by_level(project, depth)
    else:
        nodes = db.get_leaf_nodes(project)

    result: dict[str, list[tuple[str, str]]] = {}
    for node in nodes:
        if node.status == NodeStatus.INVALIDATED:
            continue
        tags = db.get_tags(node.id)
        if tags:
            result[node.id] = tags
    return result


def structural_cluster(vectors: dict[str, "HyperspaceVector"]) -> list[Cluster]:
    """Backward-compat wrapper: accepts HyperspaceVector dict, converts to tag-based clustering."""
    node_tags: dict[str, list[tuple[str, str]]] = {}
    for nid, vec in vectors.items():
        node_tags[nid] = vec.flat_tags()
    return tag_cluster(node_tags)


def tag_cluster(
    node_tags: dict[str, list[tuple[str, str]]],
) -> list[Cluster]:
    """Weighted Jaccard clustering with single-link agglomeration."""
    node_ids = list(node_tags.keys())
    n = len(node_ids)
    if n < MIN_CLUSTER_SIZE:
        return []

    # Compute pairwise similarity (only above threshold)
    pairs: list[tuple[str, str, float]] = []
    for i in range(n):
        for j in range(i + 1, n):
            sim = weighted_jaccard(node_tags[node_ids[i]], node_tags[node_ids[j]])
            if sim >= SIMILARITY_THRESHOLD:
                pairs.append((node_ids[i], node_ids[j], sim))

    # Single-link agglomeration
    groups: dict[str, set[str]] = {}
    node_to_group: dict[str, str] = {}

    pairs.sort(key=lambda x: x[2], reverse=True)
    for id_a, id_b, sim in pairs:
        g_a = node_to_group.get(id_a)
        g_b = node_to_group.get(id_b)

        if g_a and g_b:
            if g_a != g_b:
                # Merge groups
                groups[g_a] |= groups[g_b]
                for member in groups[g_b]:
                    node_to_group[member] = g_a
                del groups[g_b]
        elif g_a:
            groups[g_a].add(id_b)
            node_to_group[id_b] = g_a
        elif g_b:
            groups[g_b].add(id_a)
            node_to_group[id_a] = g_b
        else:
            gid = f"cluster_{uuid.uuid4().hex[:8]}"
            groups[gid] = {id_a, id_b}
            node_to_group[id_a] = gid
            node_to_group[id_b] = gid

    # Build Cluster objects
    clusters: list[Cluster] = []
    for gid, members in groups.items():
        if len(members) < MIN_CLUSTER_SIZE:
            continue

        # Find shared tags across all members
        member_tag_sets = [set(f"{k}:{v}" for k, v in node_tags[m]) for m in members]
        shared = member_tag_sets[0]
        for s in member_tag_sets[1:]:
            shared &= s

        strategy = MergeStrategy.EXTRACT_SHARED if len(shared) <= 3 else MergeStrategy.MERGE_DUPLICATES

        clusters.append(Cluster(
            id=gid,
            members=sorted(members),
            reason=f"Weighted tag similarity (shared: {', '.join(sorted(shared)[:5])})",
            shared_features=sorted(shared),
            suggested_action=strategy,
        ))

    return clusters


def semantic_cluster(
    project: str,
    depth: int | None,
    config: Config,
) -> list[Cluster]:
    """Embedding-based DBSCAN clustering with adaptive eps."""
    try:
        from sklearn.cluster import DBSCAN
        import numpy as np
        from shared.vector_store import VectorStore
    except ImportError:
        logger.warning("sklearn or chromadb not available, skipping semantic clustering")
        return []

    vs = VectorStore(config)
    db = Database(config)
    if depth is not None:
        nodes = db.get_nodes_by_level(project, depth)
    else:
        nodes = db.get_leaf_nodes(project)
    valid_nodes = [n for n in nodes if n.status != NodeStatus.INVALIDATED]

    if len(valid_nodes) < MIN_CLUSTER_SIZE:
        return []

    coll = vs.collections["node_summaries"]
    all_data = coll.get(
        ids=[n.id for n in valid_nodes],
        include=["embeddings"],
    )

    if not all_data or not all_data.get("embeddings"):
        return []

    id_list = all_data["ids"]
    embeddings = np.array(all_data["embeddings"])

    if len(embeddings) < MIN_CLUSTER_SIZE:
        return []

    # Adaptive eps: use median pairwise distance * 0.7
    from sklearn.metrics.pairwise import cosine_distances
    dist_matrix = cosine_distances(embeddings)
    # Get upper triangle (excluding diagonal)
    upper = dist_matrix[np.triu_indices_from(dist_matrix, k=1)]
    eps = float(np.median(upper) * 0.7) if len(upper) > 0 else 0.3
    eps = max(0.1, min(eps, 0.5))  # clamp

    clustering = DBSCAN(eps=eps, min_samples=MIN_CLUSTER_SIZE, metric="cosine")
    labels = clustering.fit_predict(embeddings)

    label_groups: dict[int, list[str]] = defaultdict(list)
    for idx, label in enumerate(labels):
        if label >= 0:
            label_groups[label].append(id_list[idx])

    clusters: list[Cluster] = []
    for label, members in label_groups.items():
        if len(members) < MIN_CLUSTER_SIZE:
            continue
        clusters.append(Cluster(
            id=f"sem_{uuid.uuid4().hex[:8]}",
            members=sorted(members),
            reason=f"Semantic embedding cluster (eps={eps:.3f})",
            suggested_action=MergeStrategy.EXTRACT_SHARED,
        ))

    return clusters


def hybrid_cluster(
    project: str,
    depth: int | None,
    config: Config,
    db: Database,
) -> list[Cluster]:
    """Combine tag clusters and semantic clusters, dedup overlaps."""
    node_tags = load_node_tags(project, depth, db)
    tag_clusters = tag_cluster(node_tags)
    sem_clusters = semantic_cluster(project, depth, config)

    # Merge: if a semantic cluster is a superset of a tag cluster, keep semantic
    final: list[Cluster] = list(sem_clusters)
    sem_member_sets = [set(c.members) for c in sem_clusters]

    for tc in tag_clusters:
        tc_set = set(tc.members)
        is_subset = any(tc_set <= s for s in sem_member_sets)
        if not is_subset:
            final.append(tc)

    logger.info(
        f"Hybrid clustering: {len(tag_clusters)} tag + {len(sem_clusters)} semantic "
        f"→ {len(final)} final clusters"
    )
    return final


def run_clustering(
    project: str,
    depth: int | None = None,
    config: Config | None = None,
) -> list[Cluster]:
    """Main entry: hybrid cluster nodes at a given depth or leaf nodes."""
    config = config or load_config()
    db = Database(config)
    return hybrid_cluster(project, depth, config, db)
