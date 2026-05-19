"""AI PM Hyperspace - multi-dimensional clustering engine.

Performs structural tag clustering (set operations) and semantic
embedding clustering (KMeans/DBSCAN) to discover reuse opportunities.
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
JACCARD_THRESHOLD = 0.3


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def load_node_vectors(
    project: str, level: int, db: Database, config: Config
) -> dict[str, HyperspaceVector]:
    nodes = db.get_nodes_by_level(project, level)
    vectors: dict[str, HyperspaceVector] = {}
    for node in nodes:
        if node.status == NodeStatus.INVALIDATED:
            continue
        if node.vector_path and Path(node.vector_path).exists():
            raw = json.loads(Path(node.vector_path).read_text(encoding="utf-8"))
            vectors[node.id] = HyperspaceVector.from_dict(raw)
        else:
            tags = db.get_tags(node.id)
            vec = HyperspaceVector()
            for key, val in tags:
                if key == "domain":
                    vec.domain.append(val)
                elif key == "entity":
                    vec.entities.append(val)
                elif key == "pattern":
                    vec.patterns.append(val)
                elif key == "tech_trait":
                    vec.tech_traits.append(val)
                elif key == "actor":
                    vec.actors.append(val)
                elif key == "nfr":
                    vec.nfr.append(val)
            vectors[node.id] = vec
    return vectors


def structural_cluster(
    vectors: dict[str, HyperspaceVector],
) -> list[Cluster]:
    node_ids = list(vectors.keys())
    n = len(node_ids)
    if n < MIN_CLUSTER_SIZE:
        return []

    similarity_matrix: dict[tuple[str, str], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            id_a, id_b = node_ids[i], node_ids[j]
            va, vb = vectors[id_a], vectors[id_b]

            domain_sim = jaccard_similarity(set(va.domain), set(vb.domain))
            entity_sim = jaccard_similarity(set(va.entities), set(vb.entities))
            pattern_sim = jaccard_similarity(set(va.patterns), set(vb.patterns))
            actor_sim = jaccard_similarity(set(va.actors), set(vb.actors))

            avg_sim = (domain_sim + entity_sim + pattern_sim + actor_sim) / 4
            if avg_sim >= JACCARD_THRESHOLD:
                similarity_matrix[(id_a, id_b)] = avg_sim

    groups: dict[str, set[str]] = {}
    assigned: set[str] = set()

    sorted_pairs = sorted(similarity_matrix.items(), key=lambda x: x[1], reverse=True)
    for (id_a, id_b), sim in sorted_pairs:
        group_a = next((g for g, members in groups.items() if id_a in members), None)
        group_b = next((g for g, members in groups.items() if id_b in members), None)

        if group_a and group_b:
            if group_a != group_b:
                groups[group_a] |= groups[group_b]
                del groups[group_b]
        elif group_a:
            groups[group_a].add(id_b)
        elif group_b:
            groups[group_b].add(id_a)
        else:
            gid = f"cluster_{uuid.uuid4().hex[:8]}"
            groups[gid] = {id_a, id_b}

        assigned.add(id_a)
        assigned.add(id_b)

    clusters: list[Cluster] = []
    for gid, members in groups.items():
        if len(members) < MIN_CLUSTER_SIZE:
            continue

        member_vecs = [vectors[m] for m in members]
        shared_domains = set(member_vecs[0].domain)
        shared_entities = set(member_vecs[0].entities)
        for mv in member_vecs[1:]:
            shared_domains &= set(mv.domain)
            shared_entities &= set(mv.entities)

        shared_features = (
            [f"domain:{d}" for d in shared_domains]
            + [f"entity:{e}" for e in shared_entities]
        )

        strategy = MergeStrategy.EXTRACT_SHARED
        if len(shared_features) > 3:
            strategy = MergeStrategy.MERGE_DUPLICATES

        clusters.append(Cluster(
            id=gid,
            members=sorted(members),
            reason=f"Shared features: {', '.join(shared_features[:5])}",
            shared_features=shared_features,
            suggested_action=strategy,
        ))

    return clusters


def semantic_cluster(
    project: str,
    level: int,
    config: Config,
) -> list[Cluster]:
    try:
        from sklearn.cluster import DBSCAN
        import numpy as np
        from shared.vector_store import VectorStore
    except ImportError:
        logger.warning("sklearn or chromadb not available, skipping semantic clustering")
        return []

    vs = VectorStore(config)
    db = Database(config)
    nodes = db.get_nodes_by_level(project, level)
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

    clustering = DBSCAN(eps=0.3, min_samples=MIN_CLUSTER_SIZE, metric="cosine")
    labels = clustering.fit_predict(embeddings)

    label_groups: dict[int, list[str]] = defaultdict(list)
    for idx, label in enumerate(labels):
        if label >= 0:
            label_groups[label].append(id_list[idx])

    clusters: list[Cluster] = []
    for label, members in label_groups.items():
        clusters.append(Cluster(
            id=f"sem_cluster_{uuid.uuid4().hex[:8]}",
            members=sorted(members),
            reason=f"Semantic similarity cluster (DBSCAN label={label})",
            suggested_action=MergeStrategy.EXTRACT_SHARED,
        ))

    return clusters


def run_clustering(
    project: str,
    level: int,
    config: Config | None = None,
) -> list[Cluster]:
    config = config or load_config()
    db = Database(config)
    vectors = load_node_vectors(project, level, db, config)

    if len(vectors) < MIN_CLUSTER_SIZE:
        logger.info(f"Too few nodes at level {level} for clustering")
        return []

    struct_clusters = structural_cluster(vectors)
    sem_clusters = semantic_cluster(project, level, config)

    all_clusters = struct_clusters + sem_clusters
    logger.info(
        f"Clustering L{level}: {len(struct_clusters)} structural, "
        f"{len(sem_clusters)} semantic clusters"
    )
    return all_clusters
