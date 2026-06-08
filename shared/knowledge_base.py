"""RAG Knowledge Base for ai-pm-skills.

A vector-backed knowledge store that all nodes can query for background context.
Each entry has a single owner (source_node_id) — only the owner can modify/delete.
Other nodes can read and propose amendments (which create new linked entries).

Sync contract:
- Node created/updated → upsert KB entry with node content
- Node deleted/invalidated → soft-delete KB entry (mark stale, keep for history)
- No two modules can write the same entry simultaneously (owner lock via source_node_id)
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, TYPE_CHECKING

if TYPE_CHECKING:
    from shared.config import Config

logger = logging.getLogger(__name__)

KB_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS knowledge (
    entry_id        TEXT PRIMARY KEY,
    project         TEXT NOT NULL,
    source_node_id  TEXT NOT NULL,
    topic_key       TEXT NOT NULL DEFAULT '',
    category        TEXT NOT NULL DEFAULT 'general',
    title           TEXT NOT NULL DEFAULT '',
    content         TEXT NOT NULL DEFAULT '',
    content_hash    TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'active',
    version         INTEGER NOT NULL DEFAULT 1,
    locked_by       TEXT NOT NULL DEFAULT '',
    locked_at       TEXT NOT NULL DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS knowledge_refs (
    entry_id        TEXT NOT NULL,
    ref_node_id     TEXT NOT NULL,
    ref_type        TEXT NOT NULL DEFAULT 'cites',
    created_at      TEXT NOT NULL,
    PRIMARY KEY (entry_id, ref_node_id, ref_type)
);

CREATE TABLE IF NOT EXISTS knowledge_amendments (
    amendment_id    TEXT PRIMARY KEY,
    entry_id        TEXT NOT NULL,
    proposer_node_id TEXT NOT NULL,
    proposed_content TEXT NOT NULL DEFAULT '',
    reason          TEXT NOT NULL DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    resolved_at     TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_kb_project ON knowledge(project);
CREATE INDEX IF NOT EXISTS idx_kb_source ON knowledge(source_node_id);
CREATE INDEX IF NOT EXISTS idx_kb_status ON knowledge(status);
CREATE INDEX IF NOT EXISTS idx_kb_category ON knowledge(category);
CREATE INDEX IF NOT EXISTS idx_kb_topic ON knowledge(topic_key);
CREATE INDEX IF NOT EXISTS idx_kb_refs_node ON knowledge_refs(ref_node_id);
CREATE INDEX IF NOT EXISTS idx_kb_amend_entry ON knowledge_amendments(entry_id);
CREATE INDEX IF NOT EXISTS idx_kb_amend_status ON knowledge_amendments(status);
"""


class KnowledgeEntry:
    __slots__ = (
        "entry_id", "project", "source_node_id", "category",
        "title", "content", "content_hash", "status", "version",
        "created_at", "updated_at",
    )

    def __init__(self, **kwargs: Any):
        for k in self.__slots__:
            setattr(self, k, kwargs.get(k, ""))
        if not self.version:
            self.version = 1

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}


SEMANTIC_DEDUP_THRESHOLD = 0.85


class KnowledgeBase:
    """Vector-backed knowledge store with ownership and sync."""

    def __init__(self, config: "Config"):
        self.config = config
        self.db_path = config.db_path
        self._vector_store = None
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(KB_SCHEMA_SQL)

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        # FK off: KB entries can outlive nodes (stale entries kept for history)
        conn.execute("PRAGMA foreign_keys=OFF")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def _content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

    # ── Topic key generation ─────────────────────────────────────────

    @staticmethod
    def _derive_topic_key(title: str, category: str) -> str:
        """Derive a topic key for indexing. Used alongside semantic dedup."""
        normalized = title.strip().lower().replace(" ", "_")
        return f"{category}__{normalized[:60]}"

    def _find_semantic_duplicate(
        self, title: str, category: str, source_node_id: str, project: str,
    ) -> dict[str, str] | None:
        """Check if a semantically similar entry already exists from another node.

        Uses the knowledge_base ChromaDB collection instead of string matching.
        Returns conflict dict if near-duplicate found, None otherwise.
        """
        try:
            from shared.vector_store import VectorStore
            from shared.embeddings import get_embedding

            if self._vector_store is None:
                self._vector_store = VectorStore(self.config)

            coll = self._vector_store.collections.get("knowledge_base")
            if coll is None or coll.count() == 0:
                return None

            query_text = f"{category}: {title}"
            embedding = get_embedding(query_text, self.config)
            results = coll.query(
                query_embeddings=[embedding],
                n_results=1,
                where={"category": category},
            )

            if not results["ids"] or not results["ids"][0]:
                return None

            top_id = results["ids"][0][0]
            top_distance = results["distances"][0][0] if results.get("distances") else 1.0
            similarity = 1.0 - top_distance

            if similarity < SEMANTIC_DEDUP_THRESHOLD:
                return None

            # Check if it's from a different node
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT entry_id, source_node_id, title, topic_key FROM knowledge "
                    "WHERE entry_id = ? AND status = 'active' AND source_node_id != ?",
                    (top_id, source_node_id),
                ).fetchone()

            if not row:
                return None

            return {
                "conflict": "semantic_duplicate",
                "owner": row["source_node_id"],
                "existing_entry_id": row["entry_id"],
                "existing_title": row["title"],
                "similarity": f"{similarity:.3f}",
                "message": (
                    f"Semantically similar entry '{row['title']}' (similarity={similarity:.3f}) "
                    f"already exists from node '{row['source_node_id']}'. "
                    f"Use propose_amendment() to suggest changes."
                ),
            }
        except Exception as e:
            logger.debug(f"Semantic dedup check failed (falling back to string): {e}")
            return None

    def _sync_to_vector(self, entry_id: str, title: str, content: str, category: str) -> None:
        """Sync an entry to the knowledge_base ChromaDB collection."""
        try:
            from shared.vector_store import VectorStore
            from shared.embeddings import get_embedding

            if self._vector_store is None:
                self._vector_store = VectorStore(self.config)

            coll = self._vector_store.collections.get("knowledge_base")
            if coll is None:
                return

            query_text = f"{category}: {title}"
            embedding = get_embedding(query_text, self.config)
            coll.upsert(
                ids=[entry_id],
                embeddings=[embedding],
                metadatas=[{"category": category, "title": title}],
                documents=[content[:1000]],
            )
        except Exception as e:
            logger.debug(f"Vector sync failed (non-fatal): {e}")

    # ── Lock operations (topic-level mutex) ───────────────��───────────

    def _acquire_lock(self, conn: sqlite3.Connection, topic_key: str, node_id: str) -> str | None:
        """Try to acquire write lock on a topic. Returns conflicting owner if locked."""
        existing = conn.execute(
            "SELECT entry_id, source_node_id, locked_by FROM knowledge "
            "WHERE topic_key = ? AND status = 'active' AND source_node_id != ?",
            (topic_key, node_id),
        ).fetchone()

        if existing:
            return existing["source_node_id"]
        return None

    # ── Write operations (owner-only + topic mutex) ───────────────────

    def upsert(
        self,
        entry_id: str,
        project: str,
        source_node_id: str,
        title: str,
        content: str,
        category: str = "general",
        topic_key: str | None = None,
    ) -> KnowledgeEntry | dict[str, str]:
        """Insert or update a KB entry.

        Rules:
        1. Only the owner (source_node_id) can modify its own entry
        2. If another node already owns an active entry on the same topic,
           the write is REJECTED and a conflict dict is returned instead
        3. Caller should then use propose_amendment() to suggest changes

        Returns KnowledgeEntry on success, or dict with 'conflict' key on rejection.
        """
        now = datetime.now().isoformat()
        content_hash = self._content_hash(content)
        topic = topic_key or self._derive_topic_key(title, category)

        with self._connect() as conn:
            # Check if this entry already exists (update path)
            existing = conn.execute(
                "SELECT source_node_id, content_hash, version FROM knowledge WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()

            if existing:
                # Update path: only owner can modify
                if existing["source_node_id"] != source_node_id:
                    return {
                        "conflict": "ownership",
                        "owner": existing["source_node_id"],
                        "entry_id": entry_id,
                        "message": f"Entry owned by '{existing['source_node_id']}', use propose_amendment()",
                    }
                if existing["content_hash"] == content_hash:
                    return self.get(entry_id)  # type: ignore

                conn.execute(
                    """UPDATE knowledge
                       SET title=?, content=?, content_hash=?, category=?,
                           topic_key=?, version=version+1, updated_at=?,
                           status='active', locked_by=?, locked_at=?
                       WHERE entry_id=?""",
                    (title, content, content_hash, category, topic, now,
                     source_node_id, now, entry_id),
                )
            else:
                # Insert path: semantic dedup first, then string-based fallback
                semantic_conflict = self._find_semantic_duplicate(
                    title, category, source_node_id, project,
                )
                if semantic_conflict:
                    return semantic_conflict

                # Fallback: string-based topic mutex
                topic_owner = self._acquire_lock(conn, topic, source_node_id)
                if topic_owner:
                    conflicting = conn.execute(
                        "SELECT entry_id FROM knowledge "
                        "WHERE topic_key = ? AND status = 'active' AND source_node_id = ?",
                        (topic, topic_owner),
                    ).fetchone()
                    return {
                        "conflict": "topic_mutex",
                        "owner": topic_owner,
                        "existing_entry_id": conflicting["entry_id"] if conflicting else "",
                        "topic_key": topic,
                        "message": (
                            f"Topic '{topic}' already has active entry from node '{topic_owner}'. "
                            f"Use propose_amendment() or cite the existing entry."
                        ),
                    }

                conn.execute(
                    """INSERT INTO knowledge
                       (entry_id, project, source_node_id, topic_key, category, title,
                        content, content_hash, status, version, locked_by, locked_at,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?, ?, ?)""",
                    (entry_id, project, source_node_id, topic, category, title,
                     content, content_hash, source_node_id, now, now, now),
                )

        # Sync to vector store for future semantic dedup
        self._sync_to_vector(entry_id, title, content, category)

        return self.get(entry_id)  # type: ignore

    def mark_stale(self, entry_id: str, source_node_id: str) -> None:
        """Soft-delete: mark entry as stale. Only owner can do this."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT source_node_id FROM knowledge WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            if not existing:
                return
            if existing["source_node_id"] != source_node_id:
                raise PermissionError(
                    f"Entry '{entry_id}' owned by '{existing['source_node_id']}'"
                )
            conn.execute(
                "UPDATE knowledge SET status='stale', locked_by='', updated_at=? WHERE entry_id=?",
                (now, entry_id),
            )

    def delete(self, entry_id: str, source_node_id: str) -> None:
        """Hard delete. Only owner can do this."""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT source_node_id FROM knowledge WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            if not existing:
                return
            if existing["source_node_id"] != source_node_id:
                raise PermissionError(
                    f"Entry '{entry_id}' owned by '{existing['source_node_id']}'"
                )
            conn.execute("DELETE FROM knowledge_refs WHERE entry_id=?", (entry_id,))
            conn.execute("DELETE FROM knowledge_amendments WHERE entry_id=?", (entry_id,))
            conn.execute("DELETE FROM knowledge WHERE entry_id=?", (entry_id,))

    # ── Amendment mechanism (non-owners propose changes) ──────────────

    def propose_amendment(
        self,
        entry_id: str,
        proposer_node_id: str,
        proposed_content: str,
        reason: str = "",
    ) -> dict[str, str]:
        """Non-owner proposes a change to an existing entry.

        Creates a pending amendment that must be resolved (accepted/rejected)
        before the entry can be further modified.
        """
        now = datetime.now().isoformat()
        amend_id = f"amend_{hashlib.sha256(f'{entry_id}_{proposer_node_id}_{now}'.encode()).hexdigest()[:12]}"

        with self._connect() as conn:
            existing = conn.execute(
                "SELECT source_node_id FROM knowledge WHERE entry_id = ?",
                (entry_id,),
            ).fetchone()
            if not existing:
                return {"error": f"Entry '{entry_id}' not found"}

            if existing["source_node_id"] == proposer_node_id:
                return {"error": "Owner should use upsert(), not propose_amendment()"}

            conn.execute(
                """INSERT INTO knowledge_amendments
                   (amendment_id, entry_id, proposer_node_id, proposed_content,
                    reason, status, created_at)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?)""",
                (amend_id, entry_id, proposer_node_id, proposed_content, reason, now),
            )

        return {"amendment_id": amend_id, "status": "pending"}

    def resolve_amendment(
        self, amendment_id: str, action: str, resolver_node_id: str
    ) -> dict[str, str]:
        """Resolve a pending amendment: 'accept' merges content, 'reject' discards.

        Only the entry owner can resolve.
        """
        now = datetime.now().isoformat()
        with self._connect() as conn:
            amend = conn.execute(
                "SELECT * FROM knowledge_amendments WHERE amendment_id = ?",
                (amendment_id,),
            ).fetchone()
            if not amend:
                return {"error": "Amendment not found"}

            entry = conn.execute(
                "SELECT * FROM knowledge WHERE entry_id = ?",
                (amend["entry_id"],),
            ).fetchone()
            if not entry:
                return {"error": "Parent entry not found"}

            if entry["source_node_id"] != resolver_node_id:
                return {"error": f"Only owner '{entry['source_node_id']}' can resolve"}

            if action == "accept":
                # Merge: append proposed content to existing
                merged = entry["content"] + "\n\n" + amend["proposed_content"]
                new_hash = self._content_hash(merged)
                conn.execute(
                    """UPDATE knowledge SET content=?, content_hash=?,
                       version=version+1, updated_at=? WHERE entry_id=?""",
                    (merged, new_hash, now, amend["entry_id"]),
                )
                conn.execute(
                    "UPDATE knowledge_amendments SET status='accepted', resolved_at=? WHERE amendment_id=?",
                    (now, amendment_id),
                )
                return {"status": "accepted", "entry_id": amend["entry_id"]}

            elif action == "reject":
                conn.execute(
                    "UPDATE knowledge_amendments SET status='rejected', resolved_at=? WHERE amendment_id=?",
                    (now, amendment_id),
                )
                return {"status": "rejected", "amendment_id": amendment_id}

            return {"error": f"Invalid action: {action}. Use 'accept' or 'reject'"}

    def get_pending_amendments(self, entry_id: str) -> list[dict[str, Any]]:
        """Get all pending amendments for an entry."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge_amendments WHERE entry_id=? AND status='pending'",
                (entry_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def has_pending_amendments(self, entry_id: str) -> bool:
        """Check if entry has unresolved amendments (blocks further writes)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM knowledge_amendments WHERE entry_id=? AND status='pending'",
                (entry_id,),
            ).fetchone()
            return row["cnt"] > 0

    # ── Read operations (all nodes) ───────────────────────────���───────

    def get(self, entry_id: str) -> KnowledgeEntry | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM knowledge WHERE entry_id = ?", (entry_id,)
            ).fetchone()
            if not row:
                return None
            return KnowledgeEntry(**dict(row))

    def query_by_project(
        self, project: str, category: str | None = None, limit: int = 100
    ) -> list[KnowledgeEntry]:
        with self._connect() as conn:
            if category:
                rows = conn.execute(
                    "SELECT * FROM knowledge WHERE project=? AND category=? AND status='active' ORDER BY updated_at DESC LIMIT ?",
                    (project, category, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM knowledge WHERE project=? AND status='active' ORDER BY updated_at DESC LIMIT ?",
                    (project, limit),
                ).fetchall()
            return [KnowledgeEntry(**dict(r)) for r in rows]

    def query_by_node(self, source_node_id: str) -> list[KnowledgeEntry]:
        """Get all entries owned by a specific node."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM knowledge WHERE source_node_id=? AND status='active'",
                (source_node_id,),
            ).fetchall()
            return [KnowledgeEntry(**dict(r)) for r in rows]

    def full_text_search(self, project: str, query: str, limit: int = 10) -> list[KnowledgeEntry]:
        """Simple LIKE search (for when vector search is unavailable)."""
        pattern = f"%{query}%"
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM knowledge
                   WHERE project=? AND status='active'
                     AND (title LIKE ? OR content LIKE ?)
                   ORDER BY updated_at DESC LIMIT ?""",
                (project, pattern, pattern, limit),
            ).fetchall()
            return [KnowledgeEntry(**dict(r)) for r in rows]

    # ── Reference tracking ────────────────────────────────────────────

    def add_ref(self, entry_id: str, ref_node_id: str, ref_type: str = "cites") -> None:
        """Track which nodes reference (cite/use) a KB entry."""
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO knowledge_refs (entry_id, ref_node_id, ref_type, created_at) VALUES (?,?,?,?)",
                (entry_id, ref_node_id, ref_type, now),
            )

    def get_refs(self, entry_id: str) -> list[dict[str, str]]:
        """Get all nodes that reference this entry."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ref_node_id, ref_type FROM knowledge_refs WHERE entry_id=?",
                (entry_id,),
            ).fetchall()
            return [{"node_id": r["ref_node_id"], "type": r["ref_type"]} for r in rows]

    def get_entries_cited_by(self, node_id: str) -> list[KnowledgeEntry]:
        """Get all KB entries cited by a specific node."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT k.* FROM knowledge k
                   JOIN knowledge_refs kr ON k.entry_id = kr.entry_id
                   WHERE kr.ref_node_id = ? AND k.status = 'active'""",
                (node_id,),
            ).fetchall()
            return [KnowledgeEntry(**dict(r)) for r in rows]

    # ── Node sync hooks ──────────────────────��────────────────────────

    def sync_node(self, node_id: str, project: str, title: str, content: str) -> dict[str, Any] | None:
        """Called when a node is created or updated. Auto-upserts its KB entry.

        Each node's own content uses a node-scoped topic key (no conflict possible).
        Returns None on success, conflict dict if something unexpected happens.
        """
        if not content.strip():
            return None
        entry_id = f"node__{node_id}"
        result = self.upsert(
            entry_id=entry_id,
            project=project,
            source_node_id=node_id,
            title=title,
            content=content,
            category="node_content",
            topic_key=f"node__{node_id}",
        )
        if isinstance(result, dict) and "conflict" in result:
            logger.warning(f"Sync conflict for node {node_id}: {result}")
            return result
        self.index_entry(entry_id)
        return None

    def sync_node_knowledge(
        self, node_id: str, project: str, title: str, content: str, topic_key: str
    ) -> Any:
        """Sync derived knowledge (not the node's own content but knowledge it produces).

        THIS is subject to topic mutex: if another node owns this topic, returns conflict.
        Caller should use propose_amendment() if conflict occurs.
        """
        entry_id = f"kb__{node_id}__{self._content_hash(topic_key)}"
        result = self.upsert(
            entry_id=entry_id,
            project=project,
            source_node_id=node_id,
            title=title,
            content=content,
            category="derived",
            topic_key=topic_key,
        )
        if isinstance(result, KnowledgeEntry):
            self.index_entry(entry_id)
        return result

    def sync_node_removed(self, node_id: str) -> None:
        """Called when a node is invalidated/deleted. Marks ALL its KB entries stale."""
        with self._connect() as conn:
            entries = conn.execute(
                "SELECT entry_id FROM knowledge WHERE source_node_id = ? AND status = 'active'",
                (node_id,),
            ).fetchall()
        for row in entries:
            try:
                self.mark_stale(row["entry_id"], source_node_id=node_id)
            except PermissionError:
                pass

    # ── Vector search integration ───────────────────────��─────────────

    def semantic_search(
        self,
        query_text: str,
        project: str,
        n_results: int = 5,
    ) -> list[KnowledgeEntry]:
        """Semantic search via embedding similarity. Falls back to text search."""
        try:
            from shared.embeddings import get_embedding
            from shared.vector_store import VectorStore

            embedding = get_embedding(query_text, self.config)
            vs = VectorStore(self.config)
            coll = vs.collections.get("knowledge_base")
            if not coll:
                return self.full_text_search(project, query_text[:50], limit=n_results)

            results = coll.query(
                query_embeddings=[embedding],
                n_results=n_results,
                where={"project": project},
            )

            if not results or not results["ids"] or not results["ids"][0]:
                return self.full_text_search(project, query_text[:50], limit=n_results)

            entries = []
            for entry_id in results["ids"][0]:
                entry = self.get(entry_id)
                if entry and entry.status == "active":
                    entries.append(entry)
            return entries

        except Exception as e:
            logger.warning(f"Semantic search failed, falling back to text: {e}")
            return self.full_text_search(project, query_text[:50], limit=n_results)

    def index_entry(self, entry_id: str) -> None:
        """Index a KB entry into the vector store for semantic search."""
        entry = self.get(entry_id)
        if not entry or entry.status != "active":
            return

        try:
            from shared.embeddings import get_embedding
            from shared.vector_store import VectorStore

            text = f"{entry.title}\n{entry.content}"
            embedding = get_embedding(text, self.config)
            vs = VectorStore(self.config)
            coll = vs.collections.get("knowledge_base")
            if coll:
                coll.upsert(
                    ids=[entry_id],
                    documents=[text],
                    embeddings=[embedding],
                    metadatas=[{"project": entry.project, "source_node": entry.source_node_id, "category": entry.category}],
                )
        except Exception as e:
            logger.warning(f"Failed to index KB entry {entry_id}: {e}")
