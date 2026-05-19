"""SQLite database operations for ai-pm-skills.

Manages three tables: nodes, tags, edges.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Generator

from shared.config import Config, load_config
from shared.models import Edge, EdgeStatus, EdgeType, Node, NodeStatus


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    node_id     TEXT PRIMARY KEY,
    project     TEXT NOT NULL,
    level       INTEGER NOT NULL,
    parent_id   TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',
    title       TEXT NOT NULL DEFAULT '',
    detail_path TEXT NOT NULL DEFAULT '',
    summary_path TEXT NOT NULL DEFAULT '',
    vector_path TEXT NOT NULL DEFAULT '',
    version     INTEGER NOT NULL DEFAULT 1,
    compacted   TEXT NOT NULL DEFAULT '',
    constraints TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    FOREIGN KEY (parent_id) REFERENCES nodes(node_id)
);

CREATE TABLE IF NOT EXISTS tags (
    node_id   TEXT NOT NULL,
    tag_key   TEXT NOT NULL,
    tag_value TEXT NOT NULL,
    FOREIGN KEY (node_id) REFERENCES nodes(node_id),
    PRIMARY KEY (node_id, tag_key, tag_value)
);

CREATE TABLE IF NOT EXISTS edges (
    from_id         TEXT NOT NULL,
    to_id           TEXT NOT NULL,
    edge_type       TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'discovered',
    strength        REAL NOT NULL DEFAULT 0.5,
    alignment_count INTEGER NOT NULL DEFAULT 0,
    contract        TEXT NOT NULL DEFAULT '',
    from_version    INTEGER NOT NULL DEFAULT 0,
    to_version      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL DEFAULT '',
    updated_at      TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (from_id) REFERENCES nodes(node_id),
    FOREIGN KEY (to_id) REFERENCES nodes(node_id),
    PRIMARY KEY (from_id, to_id, edge_type)
);

CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes(project);
CREATE INDEX IF NOT EXISTS idx_nodes_level ON nodes(level);
CREATE INDEX IF NOT EXISTS idx_nodes_status ON nodes(status);
CREATE INDEX IF NOT EXISTS idx_nodes_parent ON nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_tags_key_value ON tags(tag_key, tag_value);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);
"""

MIGRATION_COLUMNS = {
    "nodes": [
        ("version", "INTEGER NOT NULL DEFAULT 1"),
        ("compacted", "TEXT NOT NULL DEFAULT ''"),
        ("constraints", "TEXT NOT NULL DEFAULT '[]'"),
    ],
    "edges": [
        ("status", "TEXT NOT NULL DEFAULT 'discovered'"),
        ("strength", "REAL NOT NULL DEFAULT 0.5"),
        ("alignment_count", "INTEGER NOT NULL DEFAULT 0"),
        ("contract", "TEXT NOT NULL DEFAULT ''"),
        ("from_version", "INTEGER NOT NULL DEFAULT 0"),
        ("to_version", "INTEGER NOT NULL DEFAULT 0"),
        ("created_at", "TEXT NOT NULL DEFAULT ''"),
        ("updated_at", "TEXT NOT NULL DEFAULT ''"),
    ],
}


class Database:
    def __init__(self, config: Config | None = None):
        self.config = config or load_config()
        self.db_path = self.config.db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            self._migrate(conn)

    def _migrate(self, conn: sqlite3.Connection) -> None:
        for table, columns in MIGRATION_COLUMNS.items():
            existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
            for col_name, col_def in columns:
                if col_name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def}")
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_status ON edges(status)")
        except sqlite3.OperationalError:
            pass

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def insert_node(self, node: Node) -> None:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO nodes
                   (node_id, project, level, parent_id, status, title,
                    detail_path, summary_path, vector_path,
                    version, compacted, constraints, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (node.id, node.project, node.level, node.parent_id,
                 node.status.value, node.title, node.detail_path,
                 node.summary_path, node.vector_path,
                 node.version, node.compacted, node.constraints, now, now),
            )
            if node.parent_id:
                conn.execute(
                    "INSERT OR IGNORE INTO edges (from_id, to_id, edge_type) VALUES (?, ?, ?)",
                    (node.parent_id, node.id, EdgeType.PARENT.value),
                )

    def get_node(self, node_id: str) -> Node | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM nodes WHERE node_id = ?", (node_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_node(row, conn)

    def get_children(self, node_id: str) -> list[Node]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT n.* FROM nodes n
                   JOIN edges e ON e.to_id = n.node_id
                   WHERE e.from_id = ? AND e.edge_type = 'parent'
                   ORDER BY n.node_id""",
                (node_id,),
            ).fetchall()
            return [self._row_to_node(r, conn) for r in rows]

    def get_nodes_by_level(self, project: str, level: int) -> list[Node]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM nodes WHERE project = ? AND level = ? ORDER BY node_id",
                (project, level),
            ).fetchall()
            return [self._row_to_node(r, conn) for r in rows]

    def get_nodes_by_status(self, project: str, status: NodeStatus) -> list[Node]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM nodes WHERE project = ? AND status = ? ORDER BY level, node_id",
                (project, status.value),
            ).fetchall()
            return [self._row_to_node(r, conn) for r in rows]

    def update_node_status(self, node_id: str, status: NodeStatus) -> None:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE nodes SET status = ?, updated_at = ? WHERE node_id = ?",
                (status.value, now, node_id),
            )

    def set_tags(self, node_id: str, tags: list[tuple[str, str]]) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM tags WHERE node_id = ?", (node_id,))
            conn.executemany(
                "INSERT INTO tags (node_id, tag_key, tag_value) VALUES (?, ?, ?)",
                [(node_id, k, v) for k, v in tags],
            )

    def get_tags(self, node_id: str) -> list[tuple[str, str]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tag_key, tag_value FROM tags WHERE node_id = ?", (node_id,)
            ).fetchall()
            return [(r["tag_key"], r["tag_value"]) for r in rows]

    def find_nodes_by_tag(self, tag_key: str, tag_value: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT node_id FROM tags WHERE tag_key = ? AND tag_value = ?",
                (tag_key, tag_value),
            ).fetchall()
            return [r["node_id"] for r in rows]

    def add_edge(self, from_id: str, to_id: str, edge_type: EdgeType,
                 strength: float = 0.5, status: EdgeStatus = EdgeStatus.DISCOVERED) -> None:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO edges
                   (from_id, to_id, edge_type, status, strength,
                    alignment_count, contract, from_version, to_version,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 0, '', 0, 0, ?, ?)""",
                (from_id, to_id, edge_type.value, status.value, strength, now, now),
            )

    def get_dependencies(self, node_id: str) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'dependency'",
                (node_id,),
            ).fetchall()
            return [r["to_id"] for r in rows]

    def get_ancestor_chain(self, node_id: str) -> list[Node]:
        chain: list[Node] = []
        current_id: str | None = node_id
        with self._connect() as conn:
            while current_id:
                row = conn.execute(
                    "SELECT * FROM nodes WHERE node_id = ?", (current_id,)
                ).fetchone()
                if row is None:
                    break
                node = self._row_to_node(row, conn)
                chain.append(node)
                current_id = row["parent_id"]
        chain.reverse()
        return chain

    # ── Edge management ─────────────────────────────────────────────

    def get_edges(self, node_id: str) -> list[Edge]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM edges WHERE from_id = ? OR to_id = ?",
                (node_id, node_id),
            ).fetchall()
            return [self._row_to_edge(r) for r in rows]

    def get_edges_by_status(self, project: str, status: EdgeStatus) -> list[Edge]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT e.* FROM edges e
                   JOIN nodes n ON e.from_id = n.node_id
                   WHERE n.project = ? AND e.status = ?""",
                (project, status.value),
            ).fetchall()
            return [self._row_to_edge(r) for r in rows]

    def update_edge(self, from_id: str, to_id: str, edge_type: str,
                    status: str | None = None, strength: float | None = None,
                    contract: str | None = None) -> None:
        now = datetime.now().isoformat()
        updates: list[str] = ["updated_at = ?"]
        params: list[str | float] = [now]
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if strength is not None:
            updates.append("strength = ?")
            params.append(strength)
        if contract is not None:
            updates.append("contract = ?")
            params.append(contract)
        params.extend([from_id, to_id, edge_type])
        with self._connect() as conn:
            conn.execute(
                f"UPDATE edges SET {', '.join(updates)} "
                "WHERE from_id = ? AND to_id = ? AND edge_type = ?",
                params,
            )

    def increment_edge_alignment(self, from_id: str, to_id: str, edge_type: str,
                                 from_ver: int, to_ver: int) -> int:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """UPDATE edges SET alignment_count = alignment_count + 1,
                   from_version = ?, to_version = ?, updated_at = ?
                   WHERE from_id = ? AND to_id = ? AND edge_type = ?""",
                (from_ver, to_ver, now, from_id, to_id, edge_type),
            )
            row = conn.execute(
                "SELECT alignment_count FROM edges WHERE from_id = ? AND to_id = ? AND edge_type = ?",
                (from_id, to_id, edge_type),
            ).fetchone()
            return row["alignment_count"] if row else 0

    def gc_edges(self, project: str) -> dict[str, int]:
        with self._connect() as conn:
            valid_ids = {r["node_id"] for r in conn.execute(
                "SELECT node_id FROM nodes WHERE project = ?", (project,)
            ).fetchall()}

            all_edges = conn.execute(
                """SELECT e.* FROM edges e
                   JOIN nodes n ON e.from_id = n.node_id
                   WHERE n.project = ?""",
                (project,),
            ).fetchall()

            orphan = 0
            weak = 0
            stale = 0
            for row in all_edges:
                should_delete = False
                if row["from_id"] not in valid_ids or row["to_id"] not in valid_ids:
                    should_delete = True
                    orphan += 1
                elif row["strength"] < 0.15 and row["edge_type"] != "parent":
                    should_delete = True
                    weak += 1
                elif row["status"] == "stale" and row["alignment_count"] >= 3:
                    should_delete = True
                    stale += 1

                if should_delete:
                    conn.execute(
                        "DELETE FROM edges WHERE from_id = ? AND to_id = ? AND edge_type = ?",
                        (row["from_id"], row["to_id"], row["edge_type"]),
                    )
            return {"orphan": orphan, "weak": weak, "stale": stale,
                    "total_removed": orphan + weak + stale}

    def mark_edges_stale(self, node_id: str) -> int:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """UPDATE edges SET status = 'stale', updated_at = ?
                   WHERE (from_id = ? OR to_id = ?) AND edge_type != 'parent'
                   AND status IN ('specified', 'validated')""",
                (now, node_id, node_id),
            )
            return cursor.rowcount

    # ── Node versioning & compaction ──────────────────────────────

    def increment_node_version(self, node_id: str) -> int:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE nodes SET version = version + 1, updated_at = ? WHERE node_id = ?",
                (now, node_id),
            )
            row = conn.execute(
                "SELECT version FROM nodes WHERE node_id = ?", (node_id,)
            ).fetchone()
            return row["version"] if row else 0

    def update_compacted(self, node_id: str, compacted: str, constraints: str) -> None:
        now = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE nodes SET compacted = ?, constraints = ?, updated_at = ? WHERE node_id = ?",
                (compacted, constraints, now, node_id),
            )

    # ── Snapshot & reconciliation ─────────────────────────────────

    def snapshot(self, project: str) -> dict:
        with self._connect() as conn:
            nodes = conn.execute(
                "SELECT * FROM nodes WHERE project = ? ORDER BY level, node_id",
                (project,),
            ).fetchall()
            edges = conn.execute(
                """SELECT e.* FROM edges e
                   JOIN nodes n ON e.from_id = n.node_id
                   WHERE n.project = ?""",
                (project,),
            ).fetchall()
            tags = conn.execute(
                """SELECT t.* FROM tags t
                   JOIN nodes n ON t.node_id = n.node_id
                   WHERE n.project = ?""",
                (project,),
            ).fetchall()
            return {
                "nodes": [dict(r) for r in nodes],
                "edges": [dict(r) for r in edges],
                "tags": [dict(r) for r in tags],
            }

    def reconcile(self, project: str, valid_node_ids: set[str]) -> dict[str, int]:
        with self._connect() as conn:
            db_ids = {r["node_id"] for r in conn.execute(
                "SELECT node_id FROM nodes WHERE project = ?", (project,)
            ).fetchall()}

            orphan_in_db = db_ids - valid_node_ids
            removed = 0
            for nid in orphan_in_db:
                conn.execute("DELETE FROM tags WHERE node_id = ?", (nid,))
                conn.execute(
                    "DELETE FROM edges WHERE from_id = ? OR to_id = ?", (nid, nid)
                )
                conn.execute("DELETE FROM nodes WHERE node_id = ?", (nid,))
                removed += 1

            return {"orphan_nodes_removed": removed, "checked": len(db_ids)}

    def _row_to_edge(self, row: sqlite3.Row) -> Edge:
        return Edge(
            from_id=row["from_id"],
            to_id=row["to_id"],
            edge_type=EdgeType(row["edge_type"]),
            status=EdgeStatus(row["status"]) if row["status"] else EdgeStatus.DISCOVERED,
            strength=row["strength"] if "strength" in row.keys() else 0.5,
            alignment_count=row["alignment_count"] if "alignment_count" in row.keys() else 0,
            contract=row["contract"] if "contract" in row.keys() else "",
            from_version=row["from_version"] if "from_version" in row.keys() else 0,
            to_version=row["to_version"] if "to_version" in row.keys() else 0,
        )

    def count_nodes(self, project: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM nodes WHERE project = ?", (project,)
            ).fetchone()
            return row["cnt"]

    def _row_to_node(self, row: sqlite3.Row, conn: sqlite3.Connection) -> Node:
        node_id = row["node_id"]
        children_rows = conn.execute(
            "SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'parent'",
            (node_id,),
        ).fetchall()
        dep_rows = conn.execute(
            "SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'dependency'",
            (node_id,),
        ).fetchall()
        shared_rows = conn.execute(
            "SELECT to_id FROM edges WHERE from_id = ? AND edge_type = 'shared_ref'",
            (node_id,),
        ).fetchall()
        return Node(
            id=node_id,
            project=row["project"],
            level=row["level"],
            parent_id=row["parent_id"],
            status=NodeStatus(row["status"]),
            title=row["title"],
            detail_path=row["detail_path"],
            summary_path=row["summary_path"],
            vector_path=row["vector_path"],
            version=row["version"] if "version" in row.keys() else 1,
            compacted=row["compacted"] if "compacted" in row.keys() else "",
            constraints=row["constraints"] if "constraints" in row.keys() else "[]",
            children_ids=[r["to_id"] for r in children_rows],
            dependency_ids=[r["to_id"] for r in dep_rows],
            shared_component_ids=[r["to_id"] for r in shared_rows],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
