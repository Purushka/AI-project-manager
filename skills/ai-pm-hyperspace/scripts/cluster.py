"""AI PM Hyperspace - embedding-primary hybrid clustering engine.

Primary signal: embedding cosine similarity (title + tags + detail summary).
Auxiliary signal: weighted Jaccard on structured tags.
Two-round search: Jaccard pre-filter → embedding refinement.
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

AXIS_WEIGHTS = {
    "domain": 3.0,
    "entity": 2.5,
    "pattern": 2.0,
    "actor": 1.5,
    "nfr": 1.0,
    "tech_stack": 0.8,
    "complexity": 0.3,
    "data_sensitivity": 0.5,
    "revenue_impact": 0.5,
    "user_facing": 0.3,
    "timeline_priority": 0.2,
    "dependency": 0.4,
    "biz_metrics": 1.0,
}

JACCARD_PREFILTER_THRESHOLD = 0.10
EMBEDDING_SIMILARITY_THRESHOLD = 0.55


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    if not set_a and not set_b:
        return 0.0
    return len(set_a & set_b) / len(set_a | set_b)


def weighted_jaccard(tags_a: list[tuple[str, str]], tags_b: list[tuple[str, str]]) -> float:
    if not tags_a and not tags_b:
        return 0.0

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


def build_embedding_text(title: str, tags: list[tuple[str, str]], detail: str = "") -> str:
    """Build text for embedding: title + tags + detail summary."""
    tag_parts = []
    by_axis: dict[str, list[str]] = defaultdict(list)
    for k, v in tags:
        by_axis[k].append(v)
    for axis in sorted(by_axis.keys()):
        tag_parts.append(f"{axis}:{','.join(by_axis[axis])}")
    tag_str = " ".join(tag_parts)

    detail_summary = detail[:300] if detail else ""
    return f"{title}\n{tag_str}\n{detail_summary}".strip()


def normalize_tags_via_llm(
    node_tags: dict[str, list[tuple[str, str]]],
    node_titles: dict[str, str],
    config: Config | None = None,
) -> dict[str, list[tuple[str, str]]]:
    """Use LLM to normalize inconsistent tag vocabularies across nodes."""
    from shared.llm import call_llm

    config = config or load_config()

    all_values: dict[str, set[str]] = defaultdict(set)
    for tags in node_tags.values():
        for k, v in tags:
            all_values[k].add(v)

    has_chinese = any(
        any("一" <= c <= "鿿" for c in v)
        for values in all_values.values()
        for v in values
    )
    if not has_chinese and len(all_values.get("domain", set())) < 20:
        return node_tags

    tag_summary = json.dumps(
        {k: sorted(v) for k, v in all_values.items()},
        ensure_ascii=False, indent=1,
    )

    prompt = f"""Below are all tag values used across nodes, grouped by axis.
Some are in Chinese, some in English. Some are free-text, some are enum-style.
Map each Chinese or inconsistent value to a canonical lowercase-english-kebab-case term.
Only output a JSON mapping: {{"original_value": "canonical_value", ...}}
Only include values that NEED normalization. Skip values already in correct English kebab-case.

Tags:
{tag_summary[:4000]}"""

    system = "You normalize tag vocabularies. Output only JSON, no explanation."

    try:
        response = call_llm(prompt, config, system_prompt=system, max_tokens=2048)
        mapping = _parse_json_safe(response)
        if not isinstance(mapping, dict):
            return node_tags

        normalized: dict[str, list[tuple[str, str]]] = {}
        for nid, tags in node_tags.items():
            new_tags = []
            for k, v in tags:
                mapped_v = mapping.get(v, v)
                new_tags.append((k, mapped_v))
            normalized[nid] = new_tags

        logger.info(f"Tag normalization: {len(mapping)} values mapped")
        return normalized
    except Exception as e:
        logger.warning(f"Tag normalization failed, using raw tags: {e}")
        return node_tags


def _parse_json_safe(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for ch in ["{", "["]:
            idx = text.find(ch)
            if idx >= 0:
                try:
                    return json.loads(text[idx:])
                except json.JSONDecodeError:
                    continue
        return None


def load_node_tags(
    project: str, depth: int | None, db: Database
) -> dict[str, list[tuple[str, str]]]:
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
    """Backward-compat wrapper."""
    node_tags: dict[str, list[tuple[str, str]]] = {}
    for nid, vec in vectors.items():
        node_tags[nid] = vec.flat_tags()
    return tag_cluster(node_tags)


def tag_cluster(
    node_tags: dict[str, list[tuple[str, str]]],
    node_titles: dict[str, str] | None = None,
    use_semantic: bool = False,
    config: Config | None = None,
) -> list[Cluster]:
    """Weighted Jaccard clustering (backward compat, used as pre-filter)."""
    node_ids = list(node_tags.keys())
    n = len(node_ids)
    if n < MIN_CLUSTER_SIZE:
        return []

    all_sims: dict[tuple[str, str], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            sim = weighted_jaccard(node_tags[node_ids[i]], node_tags[node_ids[j]])
            all_sims[(node_ids[i], node_ids[j])] = sim

    threshold = JACCARD_PREFILTER_THRESHOLD
    above_zero = [s for s in all_sims.values() if s > 0.05]
    if len(above_zero) >= 5:
        sorted_sims = sorted(above_zero, reverse=True)
        p30_idx = max(1, int(len(sorted_sims) * 0.3))
        adaptive = sorted_sims[min(p30_idx, len(sorted_sims) - 1)]
        threshold = max(adaptive, JACCARD_PREFILTER_THRESHOLD)

    pairs = [
        (id_a, id_b, sim)
        for (id_a, id_b), sim in all_sims.items()
        if sim >= threshold
    ]

    groups: dict[str, set[str]] = {}
    node_to_group: dict[str, str] = {}

    def avg_sim_to_group(node: str, group_members: set[str]) -> float:
        sims = []
        for member in group_members:
            key = (min(node, member), max(node, member))
            sims.append(all_sims.get(key, 0.0))
        return sum(sims) / len(sims) if sims else 0.0

    pairs.sort(key=lambda x: x[2], reverse=True)
    for id_a, id_b, sim in pairs:
        g_a = node_to_group.get(id_a)
        g_b = node_to_group.get(id_b)

        if g_a and g_b:
            if g_a != g_b:
                cross_sims = []
                for ma in groups[g_a]:
                    for mb in groups[g_b]:
                        key = (min(ma, mb), max(ma, mb))
                        cross_sims.append(all_sims.get(key, 0.0))
                if cross_sims and (sum(cross_sims) / len(cross_sims)) >= threshold:
                    groups[g_a] |= groups[g_b]
                    for member in groups[g_b]:
                        node_to_group[member] = g_a
                    del groups[g_b]
        elif g_a:
            if avg_sim_to_group(id_b, groups[g_a]) >= threshold:
                groups[g_a].add(id_b)
                node_to_group[id_b] = g_a
        elif g_b:
            if avg_sim_to_group(id_a, groups[g_b]) >= threshold:
                groups[g_b].add(id_a)
                node_to_group[id_a] = g_b
        else:
            gid = f"cluster_{uuid.uuid4().hex[:8]}"
            groups[gid] = {id_a, id_b}
            node_to_group[id_a] = gid
            node_to_group[id_b] = gid

    clusters: list[Cluster] = []
    for gid, members in groups.items():
        if len(members) < MIN_CLUSTER_SIZE:
            continue

        member_tag_sets = [set(f"{k}:{v}" for k, v in node_tags[m]) for m in members]
        shared = member_tag_sets[0]
        for s in member_tag_sets[1:]:
            shared &= s

        high_weight_shared = [
            t for t in shared
            if t.split(":")[0] in ("domain", "entity", "pattern")
        ]
        if len(high_weight_shared) >= 3:
            strategy = MergeStrategy.MERGE_DUPLICATES
        elif len(shared) >= 2:
            strategy = MergeStrategy.EXTRACT_SHARED
        else:
            strategy = MergeStrategy.KEEP_SEPARATE

        clusters.append(Cluster(
            id=gid,
            members=sorted(members),
            reason=f"Weighted tag similarity (shared: {', '.join(sorted(shared)[:5])})",
            shared_features=sorted(shared),
            suggested_action=strategy,
        ))

    return clusters


def embedding_cluster(
    node_data: list[dict[str, Any]],
    config: Config,
    embedding_threshold: float = EMBEDDING_SIMILARITY_THRESHOLD,
) -> list[Cluster]:
    """Embedding-primary clustering with Jaccard as auxiliary signal.

    node_data: [{id, title, tags: [(k,v),...], detail: str}, ...]
    Returns clusters based on embedding cosine similarity.
    """
    from shared.embeddings import get_embeddings_batch, cosine_similarity_matrix

    n = len(node_data)
    if n < MIN_CLUSTER_SIZE:
        return []

    logger.info(f"  Embedding {n} nodes via DashScope text-embedding-v3...")
    texts = [
        build_embedding_text(nd["title"], nd.get("tags", []), nd.get("detail", ""))
        for nd in node_data
    ]
    embeddings = get_embeddings_batch(texts, config)
    logger.info(f"  Embedding complete. Computing {n}x{n} similarity matrix...")

    sim_matrix = cosine_similarity_matrix(embeddings)
    node_ids = [nd["id"] for nd in node_data]

    # Build node_tags for Jaccard auxiliary
    node_tags = {nd["id"]: nd.get("tags", []) for nd in node_data}

    # Combine: 0.7 * embedding + 0.3 * jaccard
    all_sims: dict[tuple[str, str], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            emb_sim = float(sim_matrix[i, j])
            jac_sim = weighted_jaccard(
                node_tags[node_ids[i]], node_tags[node_ids[j]]
            )
            combined = 0.7 * emb_sim + 0.3 * jac_sim
            all_sims[(node_ids[i], node_ids[j])] = combined

    # Adaptive threshold based on distribution
    above_min = [s for s in all_sims.values() if s > 0.2]
    threshold = embedding_threshold
    if len(above_min) >= 10:
        sorted_sims = sorted(above_min, reverse=True)
        p30_idx = max(1, int(len(sorted_sims) * 0.3))
        adaptive = sorted_sims[min(p30_idx, len(sorted_sims) - 1)]
        threshold = max(adaptive, embedding_threshold)
    logger.info(f"  Embedding cluster threshold: {threshold:.3f}")

    pairs = [
        (id_a, id_b, sim)
        for (id_a, id_b), sim in all_sims.items()
        if sim >= threshold
    ]
    logger.info(f"  Pairs above threshold: {len(pairs)}")

    # Average-link agglomeration
    groups: dict[str, set[str]] = {}
    node_to_group: dict[str, str] = {}

    def avg_sim_to_group(node: str, group_members: set[str]) -> float:
        sims = []
        for member in group_members:
            key = (min(node, member), max(node, member))
            sims.append(all_sims.get(key, 0.0))
        return sum(sims) / len(sims) if sims else 0.0

    pairs.sort(key=lambda x: x[2], reverse=True)
    for id_a, id_b, sim in pairs:
        g_a = node_to_group.get(id_a)
        g_b = node_to_group.get(id_b)

        if g_a and g_b:
            if g_a != g_b:
                cross_sims = []
                for ma in groups[g_a]:
                    for mb in groups[g_b]:
                        key = (min(ma, mb), max(ma, mb))
                        cross_sims.append(all_sims.get(key, 0.0))
                if cross_sims and (sum(cross_sims) / len(cross_sims)) >= threshold:
                    groups[g_a] |= groups[g_b]
                    for member in groups[g_b]:
                        node_to_group[member] = g_a
                    del groups[g_b]
        elif g_a:
            if avg_sim_to_group(id_b, groups[g_a]) >= threshold:
                groups[g_a].add(id_b)
                node_to_group[id_b] = g_a
        elif g_b:
            if avg_sim_to_group(id_a, groups[g_b]) >= threshold:
                groups[g_b].add(id_a)
                node_to_group[id_a] = g_b
        else:
            gid = f"cluster_{uuid.uuid4().hex[:8]}"
            groups[gid] = {id_a, id_b}
            node_to_group[id_a] = gid
            node_to_group[id_b] = gid

    node_title_map = {nd["id"]: nd["title"] for nd in node_data}

    clusters: list[Cluster] = []
    for gid, members in groups.items():
        if len(members) < MIN_CLUSTER_SIZE:
            continue

        member_tag_sets = [set(f"{k}:{v}" for k, v in node_tags.get(m, [])) for m in members]
        shared = member_tag_sets[0] if member_tag_sets else set()
        for s in member_tag_sets[1:]:
            shared &= s

        high_weight_shared = [
            t for t in shared
            if t.split(":")[0] in ("domain", "entity", "pattern")
        ]
        if len(high_weight_shared) >= 3:
            strategy = MergeStrategy.MERGE_DUPLICATES
        elif len(high_weight_shared) >= 1:
            # At least one high-signal axis shared → safe to extract
            strategy = MergeStrategy.EXTRACT_SHARED
        else:
            # Only low-signal axes (data_sensitivity, user_facing, etc.) → reject
            strategy = MergeStrategy.KEEP_SEPARATE

        clusters.append(Cluster(
            id=gid,
            members=sorted(members),
            reason=f"Embedding+Jaccard hybrid (shared tags: {', '.join(sorted(shared)[:5])})",
            shared_features=sorted(shared),
            suggested_action=strategy,
        ))

    return clusters


def semantic_cluster(
    project: str,
    depth: int | None,
    config: Config,
) -> list[Cluster]:
    """Legacy embedding-based DBSCAN clustering."""
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
    import numpy as np
    embeddings = np.array(all_data["embeddings"])

    if len(embeddings) < MIN_CLUSTER_SIZE:
        return []

    from sklearn.metrics.pairwise import cosine_distances
    dist_matrix = cosine_distances(embeddings)
    upper = dist_matrix[np.triu_indices_from(dist_matrix, k=1)]
    eps = float(np.median(upper) * 0.7) if len(upper) > 0 else 0.3
    eps = max(0.1, min(eps, 0.5))

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
