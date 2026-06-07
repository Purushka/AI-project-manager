"""AI PM Memory - cross-project pattern memory system.

Stores and retrieves architecture patterns, decomposition strategies,
and clustering experiences across projects for transfer learning.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from shared.config import Config, load_config
from shared.db import Database
from shared.embeddings import EmbeddingError, get_embedding
from shared.models import HyperspaceVector

logger = logging.getLogger(__name__)


@dataclass
class PatternRecord:
    id: str
    description: str
    source_project: str
    source_node: str
    tags: dict[str, list[str]]
    relevance_score: float = 0.0


def store_pattern(
    description: str,
    source_project: str,
    source_node: str,
    tags: dict[str, list[str]] | None = None,
    config: Config | None = None,
) -> str:
    config = config or load_config()

    try:
        from shared.vector_store import VectorStore
        embedding = get_embedding(description, config)
        vs = VectorStore(config)
    except (ImportError, EmbeddingError) as e:
        logger.warning(f"Vector store unavailable, storing metadata only: {e}")
        embedding = None
        vs = None

    pattern_id = f"pattern_{uuid.uuid4().hex[:8]}"
    metadata = {
        "source_project": source_project,
        "source_node": source_node,
    }
    if tags:
        for key, values in tags.items():
            metadata[f"tag_{key}"] = ",".join(values[:5])

    if vs and embedding:
        vs.add_project_pattern(
            pattern_id=pattern_id,
            description=description,
            embedding=embedding,
            metadata=metadata,
        )

    pattern_dir = config.data_dir / "patterns"
    pattern_dir.mkdir(parents=True, exist_ok=True)
    pattern_file = pattern_dir / f"{pattern_id}.json"
    with open(pattern_file, "w", encoding="utf-8") as f:
        json.dump({
            "id": pattern_id,
            "description": description,
            "source_project": source_project,
            "source_node": source_node,
            "tags": tags or {},
        }, f, indent=2, ensure_ascii=False)

    logger.info(f"Stored pattern {pattern_id} from {source_project}/{source_node}")
    return pattern_id


def search_patterns(
    query: str,
    n_results: int = 5,
    config: Config | None = None,
) -> list[PatternRecord]:
    config = config or load_config()

    try:
        from shared.vector_store import VectorStore
        embedding = get_embedding(query, config)
        vs = VectorStore(config)
    except (ImportError, EmbeddingError) as e:
        logger.warning(f"Vector search unavailable: {e}")
        return _fallback_search(query, n_results, config)

    results = vs.query_patterns(embedding, n_results=n_results)
    records: list[PatternRecord] = []
    for item in results:
        meta = item.get("metadata", {})
        tags: dict[str, list[str]] = {}
        for key, val in meta.items():
            if key.startswith("tag_"):
                tags[key[4:]] = val.split(",")

        records.append(PatternRecord(
            id=item.get("pattern_id", ""),
            description=item.get("document", ""),
            source_project=meta.get("source_project", ""),
            source_node=meta.get("source_node", ""),
            tags=tags,
            relevance_score=1.0 - (item.get("distance", 1.0) or 1.0),
        ))

    return records


def search_by_vector(
    vector: HyperspaceVector,
    n_results: int = 5,
    config: Config | None = None,
) -> list[PatternRecord]:
    description = (
        f"Domain: {', '.join(vector.domain)}. "
        f"Entity: {', '.join(vector.entity)}. "
        f"Pattern: {', '.join(vector.pattern)}. "
        f"Actor: {', '.join(vector.actor)}"
    )
    return search_patterns(description, n_results, config)


def _fallback_search(
    query: str,
    n_results: int,
    config: Config,
) -> list[PatternRecord]:
    pattern_dir = config.data_dir / "patterns"
    if not pattern_dir.exists():
        return []

    query_lower = query.lower()
    records: list[PatternRecord] = []

    for f in pattern_dir.glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        desc = data.get("description", "").lower()
        score = sum(1 for word in query_lower.split() if word in desc)
        if score > 0:
            records.append(PatternRecord(
                id=data["id"],
                description=data["description"],
                source_project=data.get("source_project", ""),
                source_node=data.get("source_node", ""),
                tags=data.get("tags", {}),
                relevance_score=score / len(query_lower.split()),
            ))

    records.sort(key=lambda r: r.relevance_score, reverse=True)
    return records[:n_results]


def extract_patterns_from_project(
    project: str,
    config: Config | None = None,
) -> list[str]:
    config = config or load_config()
    db = Database(config)

    from shared.models import NodeStatus
    done_nodes = db.get_nodes_by_status(project, NodeStatus.DONE)

    stored_ids: list[str] = []
    for node in done_nodes:
        if not node.vector_path or not Path(node.vector_path).exists():
            continue

        vec_data = json.loads(Path(node.vector_path).read_text(encoding="utf-8"))
        vector = HyperspaceVector.from_dict(vec_data)

        summary = ""
        if node.summary_path and Path(node.summary_path).exists():
            summary = Path(node.summary_path).read_text(encoding="utf-8")

        description = f"{node.title}: {summary}" if summary else node.title
        tags = {k: [v for _, v in vector.flat_tags() if _ == k]
                for k in set(k for k, _ in vector.flat_tags())}

        pid = store_pattern(
            description=description,
            source_project=project,
            source_node=node.id,
            tags=tags,
            config=config,
        )
        stored_ids.append(pid)

    logger.info(f"Extracted {len(stored_ids)} patterns from project {project}")
    return stored_ids
