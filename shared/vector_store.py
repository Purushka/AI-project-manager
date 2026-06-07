"""ChromaDB vector store operations for ai-pm-skills.

Manages three collections:
- node_summaries: node summary embeddings for semantic search
- rule_fingerprints: business rule fingerprint embeddings for dedup
- project_patterns: cross-project architecture pattern embeddings
"""

from __future__ import annotations

import logging
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from shared.config import Config

logger = logging.getLogger(__name__)

COLLECTION_NAMES = [
    "node_summaries",
    "rule_fingerprints",
    "project_patterns",
    "knowledge_base",
]


class VectorStore:
    def __init__(self, config: "Config"):
        import chromadb

        self.config = config
        persist_dir = str(config.vector_dir)
        config.vector_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.collections: dict[str, Any] = {}
        for name in COLLECTION_NAMES:
            self.collections[name] = self.client.get_or_create_collection(
                name=name,
                metadata={"hnsw:space": "cosine"},
            )

    def add_node_summary(
        self,
        node_id: str,
        summary_text: str,
        embedding: list[float],
        metadata: dict[str, str] | None = None,
    ) -> None:
        coll = self.collections["node_summaries"]
        meta = metadata or {}
        coll.upsert(
            ids=[node_id],
            documents=[summary_text],
            embeddings=[embedding],
            metadatas=[meta],
        )

    def query_similar_nodes(
        self,
        embedding: list[float],
        n_results: int = 10,
        where: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        coll = self.collections["node_summaries"]
        kwargs: dict[str, Any] = {
            "query_embeddings": [embedding],
            "n_results": n_results,
        }
        if where:
            kwargs["where"] = where
        results = coll.query(**kwargs)
        items: list[dict[str, Any]] = []
        if results and results["ids"]:
            for i, nid in enumerate(results["ids"][0]):
                items.append({
                    "node_id": nid,
                    "distance": results["distances"][0][i] if results.get("distances") else None,
                    "document": results["documents"][0][i] if results.get("documents") else None,
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else None,
                })
        return items

    def add_rule_fingerprint(
        self,
        node_id: str,
        rule_text: str,
        embedding: list[float],
    ) -> None:
        coll = self.collections["rule_fingerprints"]
        coll.upsert(
            ids=[node_id],
            documents=[rule_text],
            embeddings=[embedding],
        )

    def find_similar_rules(
        self,
        embedding: list[float],
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        coll = self.collections["rule_fingerprints"]
        results = coll.query(
            query_embeddings=[embedding],
            n_results=n_results,
        )
        items: list[dict[str, Any]] = []
        if results and results["ids"]:
            for i, nid in enumerate(results["ids"][0]):
                items.append({
                    "node_id": nid,
                    "distance": results["distances"][0][i] if results.get("distances") else None,
                    "document": results["documents"][0][i] if results.get("documents") else None,
                })
        return items

    def add_project_pattern(
        self,
        pattern_id: str,
        description: str,
        embedding: list[float],
        metadata: dict[str, str] | None = None,
    ) -> None:
        coll = self.collections["project_patterns"]
        coll.upsert(
            ids=[pattern_id],
            documents=[description],
            embeddings=[embedding],
            metadatas=[metadata or {}],
        )

    def query_patterns(
        self,
        embedding: list[float],
        n_results: int = 5,
    ) -> list[dict[str, Any]]:
        coll = self.collections["project_patterns"]
        results = coll.query(
            query_embeddings=[embedding],
            n_results=n_results,
        )
        items: list[dict[str, Any]] = []
        if results and results["ids"]:
            for i, pid in enumerate(results["ids"][0]):
                items.append({
                    "pattern_id": pid,
                    "distance": results["distances"][0][i] if results.get("distances") else None,
                    "document": results["documents"][0][i] if results.get("documents") else None,
                    "metadata": results["metadatas"][0][i] if results.get("metadatas") else None,
                })
        return items

    def delete_node(self, node_id: str) -> None:
        for coll in self.collections.values():
            try:
                coll.delete(ids=[node_id])
            except Exception:
                pass

    def collection_count(self, name: str) -> int:
        if name not in self.collections:
            return 0
        return self.collections[name].count()
