"""Tests for edge management, node versioning, compaction, and snapshots.

Covers: db.py edge CRUD, gc, stale marking, alignment tracking,
        node version increments, compaction updates, snapshot/reconcile,
        and models.py Edge/EdgeStatus/EdgeType enums.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.config import Config
from shared.db import Database
from shared.models import (
    CompactionLevel, Edge, EdgeStatus, EdgeType,
    HyperspaceVector, MergeStrategy, Node, NodeStatus,
)


@pytest.fixture
def db():
    """Fresh in-memory-like database using a temp directory."""
    tmp = tempfile.mkdtemp()
    config = Config(workspace_path=tmp)
    return Database(config)


@pytest.fixture
def seeded_db(db):
    """Database with a small tree: root -> [child_a, child_b, child_c]."""
    db.insert_node(Node(id="root", project="proj", level=0, parent_id=None, title="Root"))
    db.insert_node(Node(id="child_a", project="proj", level=1, parent_id="root", title="Child A"))
    db.insert_node(Node(id="child_b", project="proj", level=1, parent_id="root", title="Child B"))
    db.insert_node(Node(id="child_c", project="proj", level=1, parent_id="root", title="Child C"))
    return db


# ── Model enum tests ─────────────────────────────────────────────────


class TestEdgeTypeEnum:
    def test_all_6_functional_types(self):
        functional = [EdgeType.CALLS, EdgeType.PRODUCES_CONSUMES, EdgeType.SHARES,
                      EdgeType.PRESENTS, EdgeType.CONSTRAINS, EdgeType.MEASURES]
        assert len(functional) == 6

    def test_structural_types(self):
        assert EdgeType.PARENT.value == "parent"
        assert EdgeType.DEPENDENCY.value == "dependency"
        assert EdgeType.SHARED_REF.value == "shared_ref"

    def test_from_string(self):
        assert EdgeType("calls") == EdgeType.CALLS
        assert EdgeType("produces_consumes") == EdgeType.PRODUCES_CONSUMES

    def test_invalid_type(self):
        with pytest.raises(ValueError):
            EdgeType("nonexistent")


class TestEdgeStatusEnum:
    def test_lifecycle_order(self):
        statuses = [EdgeStatus.DISCOVERED, EdgeStatus.TYPED, EdgeStatus.SPECIFIED,
                    EdgeStatus.VALIDATED, EdgeStatus.STALE, EdgeStatus.CONFLICT]
        assert len(statuses) == 6
        assert EdgeStatus.DISCOVERED.value == "discovered"
        assert EdgeStatus.CONFLICT.value == "conflict"


class TestCompactionLevelEnum:
    def test_three_levels(self):
        assert CompactionLevel.FULL.value == "full"
        assert CompactionLevel.COMPACTED.value == "compacted"
        assert CompactionLevel.INTERFACE.value == "interface"


class TestEdgeDataclass:
    def test_defaults(self):
        e = Edge(from_id="a", to_id="b", edge_type=EdgeType.CALLS)
        assert e.status == EdgeStatus.DISCOVERED
        assert e.strength == 0.5
        assert e.alignment_count == 0
        assert e.contract == ""
        assert e.from_version == 0
        assert e.to_version == 0

    def test_custom_values(self):
        e = Edge(from_id="a", to_id="b", edge_type=EdgeType.SHARES,
                 status=EdgeStatus.VALIDATED, strength=0.9,
                 alignment_count=3, contract="shared schema v2")
        assert e.strength == 0.9
        assert e.contract == "shared schema v2"


class TestHyperspaceVectorBizMetrics:
    def test_biz_metrics_in_flat_tags(self):
        vec = HyperspaceVector(
            domain=["payments"],
            biz_metrics=["conversion_rate", "arpu"],
        )
        tags = vec.flat_tags()
        assert ("biz_metric", "conversion_rate") in tags
        assert ("biz_metric", "arpu") in tags
        assert ("domain", "payments") in tags

    def test_to_dict_includes_biz_metrics(self):
        vec = HyperspaceVector(biz_metrics=["ltv"])
        d = vec.to_dict()
        assert d["biz_metrics"] == ["ltv"]

    def test_from_dict_includes_biz_metrics(self):
        d = {"biz_metrics": ["mrr", "churn"]}
        vec = HyperspaceVector.from_dict(d)
        assert vec.biz_metrics == ["mrr", "churn"]


# ── Edge CRUD tests ──────────────────────────────────────────────────


class TestEdgeAdd:
    def test_add_edge(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS, strength=0.7)
        edges = seeded_db.get_edges("child_a")
        call_edges = [e for e in edges if e.edge_type == EdgeType.CALLS]
        assert len(call_edges) == 1
        assert call_edges[0].to_id == "child_b"
        assert call_edges[0].strength == 0.7
        assert call_edges[0].status == EdgeStatus.DISCOVERED

    def test_add_edge_default_strength(self, seeded_db):
        seeded_db.add_edge("child_a", "child_c", EdgeType.SHARES)
        edges = seeded_db.get_edges("child_a")
        shares = [e for e in edges if e.edge_type == EdgeType.SHARES]
        assert shares[0].strength == 0.5

    def test_add_edge_with_custom_status(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CONSTRAINS,
                           status=EdgeStatus.TYPED)
        edges = seeded_db.get_edges("child_a")
        constrains = [e for e in edges if e.edge_type == EdgeType.CONSTRAINS]
        assert constrains[0].status == EdgeStatus.TYPED

    def test_add_duplicate_edge_ignored(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS, strength=0.7)
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS, strength=0.9)
        edges = seeded_db.get_edges("child_a")
        call_edges = [e for e in edges if e.edge_type == EdgeType.CALLS]
        assert len(call_edges) == 1
        assert call_edges[0].strength == 0.7  # OR IGNORE keeps original

    def test_add_multiple_types_same_pair(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS)
        seeded_db.add_edge("child_a", "child_b", EdgeType.SHARES)
        edges = seeded_db.get_edges("child_a")
        ab_edges = [e for e in edges if e.to_id == "child_b" and e.edge_type != EdgeType.PARENT]
        assert len(ab_edges) == 2
        types = {e.edge_type for e in ab_edges}
        assert EdgeType.CALLS in types
        assert EdgeType.SHARES in types


class TestEdgeGet:
    def test_get_edges_both_directions(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS)
        # child_b should see this edge too (query uses from_id OR to_id)
        edges_b = seeded_db.get_edges("child_b")
        call_edges = [e for e in edges_b if e.edge_type == EdgeType.CALLS]
        assert len(call_edges) == 1
        assert call_edges[0].from_id == "child_a"

    def test_get_edges_includes_parent(self, seeded_db):
        edges = seeded_db.get_edges("child_a")
        parent_edges = [e for e in edges if e.edge_type == EdgeType.PARENT]
        assert len(parent_edges) == 1
        assert parent_edges[0].from_id == "root"

    def test_get_edges_empty(self, db):
        db.insert_node(Node(id="lonely", project="p", level=0, parent_id=None, title="L"))
        edges = db.get_edges("lonely")
        assert edges == []


class TestEdgeGetByStatus:
    def test_filter_by_status(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS,
                           status=EdgeStatus.VALIDATED)
        seeded_db.add_edge("child_a", "child_c", EdgeType.SHARES,
                           status=EdgeStatus.STALE)
        validated = seeded_db.get_edges_by_status("proj", EdgeStatus.VALIDATED)
        stale = seeded_db.get_edges_by_status("proj", EdgeStatus.STALE)
        assert len(validated) == 1
        assert validated[0].to_id == "child_b"
        assert len(stale) == 1
        assert stale[0].to_id == "child_c"


class TestEdgeUpdate:
    def test_update_status(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS)
        seeded_db.update_edge("child_a", "child_b", EdgeType.CALLS.value,
                              status=EdgeStatus.SPECIFIED.value)
        edges = seeded_db.get_edges("child_a")
        call = [e for e in edges if e.edge_type == EdgeType.CALLS][0]
        assert call.status == EdgeStatus.SPECIFIED

    def test_update_strength(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS, strength=0.5)
        seeded_db.update_edge("child_a", "child_b", EdgeType.CALLS.value,
                              strength=0.85)
        edges = seeded_db.get_edges("child_a")
        call = [e for e in edges if e.edge_type == EdgeType.CALLS][0]
        assert abs(call.strength - 0.85) < 0.001

    def test_update_contract(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS)
        contract = "auth.verify(jwt) -> user.permissions(uid) -> PermissionSet"
        seeded_db.update_edge("child_a", "child_b", EdgeType.CALLS.value,
                              contract=contract)
        edges = seeded_db.get_edges("child_a")
        call = [e for e in edges if e.edge_type == EdgeType.CALLS][0]
        assert call.contract == contract

    def test_update_multiple_fields(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.PRODUCES_CONSUMES)
        seeded_db.update_edge("child_a", "child_b", EdgeType.PRODUCES_CONSUMES.value,
                              status=EdgeStatus.VALIDATED.value,
                              strength=0.95,
                              contract="OrderEvent schema v2")
        edges = seeded_db.get_edges("child_a")
        pc = [e for e in edges if e.edge_type == EdgeType.PRODUCES_CONSUMES][0]
        assert pc.status == EdgeStatus.VALIDATED
        assert abs(pc.strength - 0.95) < 0.001
        assert pc.contract == "OrderEvent schema v2"


class TestAlignmentTracking:
    def test_increment_alignment(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS)
        count = seeded_db.increment_edge_alignment(
            "child_a", "child_b", EdgeType.CALLS.value,
            from_ver=1, to_ver=1,
        )
        assert count == 1

    def test_multiple_increments(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS)
        for i in range(5):
            count = seeded_db.increment_edge_alignment(
                "child_a", "child_b", EdgeType.CALLS.value,
                from_ver=i + 1, to_ver=i + 1,
            )
        assert count == 5  # oscillation threshold exceeded

    def test_versions_tracked(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS)
        seeded_db.increment_edge_alignment(
            "child_a", "child_b", EdgeType.CALLS.value,
            from_ver=3, to_ver=5,
        )
        edges = seeded_db.get_edges("child_a")
        call = [e for e in edges if e.edge_type == EdgeType.CALLS][0]
        assert call.from_version == 3
        assert call.to_version == 5


class TestStaleMarking:
    def test_mark_edges_stale(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS,
                           status=EdgeStatus.VALIDATED)
        seeded_db.add_edge("child_a", "child_c", EdgeType.SHARES,
                           status=EdgeStatus.SPECIFIED)
        count = seeded_db.mark_edges_stale("child_a")
        assert count == 2
        edges = seeded_db.get_edges("child_a")
        for e in edges:
            if e.edge_type in (EdgeType.CALLS, EdgeType.SHARES):
                assert e.status == EdgeStatus.STALE

    def test_parent_edges_not_marked_stale(self, seeded_db):
        """Parent edges should never be marked stale."""
        seeded_db.mark_edges_stale("child_a")
        edges = seeded_db.get_edges("child_a")
        parent = [e for e in edges if e.edge_type == EdgeType.PARENT]
        assert all(e.status != EdgeStatus.STALE for e in parent)

    def test_discovered_edges_not_marked_stale(self, seeded_db):
        """Only specified/validated become stale, not discovered."""
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS,
                           status=EdgeStatus.DISCOVERED)
        count = seeded_db.mark_edges_stale("child_a")
        assert count == 0


# ── Edge GC tests ────────────────────────────────────────────────────


class TestEdgeGC:
    def test_gc_orphan_edges(self, seeded_db):
        """Edges pointing to removed nodes should be cleaned up by GC."""
        # Create a temp node, add edge, then remove the node via reconcile
        seeded_db.insert_node(Node(id="temp", project="proj", level=1,
                                   parent_id="root", title="Temp"))
        seeded_db.add_edge("child_a", "temp", EdgeType.CALLS, strength=0.8)
        # Reconcile with temp not in valid set → removes temp + its edges
        seeded_db.reconcile("proj", {"root", "child_a", "child_b", "child_c"})
        # Verify the edge to temp is gone
        edges = seeded_db.get_edges("child_a")
        to_temp = [e for e in edges if e.to_id == "temp"]
        assert len(to_temp) == 0

    def test_gc_weak_edges(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS, strength=0.1)
        result = seeded_db.gc_edges("proj")
        assert result["weak"] == 1
        assert result["total_removed"] >= 1
        # Verify edge is gone
        edges = seeded_db.get_edges("child_a")
        call_edges = [e for e in edges if e.edge_type == EdgeType.CALLS]
        assert len(call_edges) == 0

    def test_gc_preserves_strong_edges(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS, strength=0.8)
        result = seeded_db.gc_edges("proj")
        assert result["weak"] == 0
        edges = seeded_db.get_edges("child_a")
        call_edges = [e for e in edges if e.edge_type == EdgeType.CALLS]
        assert len(call_edges) == 1

    def test_gc_parent_edges_preserved(self, seeded_db):
        """Parent edges should never be GC'd even with low strength."""
        result = seeded_db.gc_edges("proj")
        edges = seeded_db.get_edges("root")
        parent_edges = [e for e in edges if e.edge_type == EdgeType.PARENT]
        assert len(parent_edges) == 3  # root -> child_a, child_b, child_c

    def test_gc_stale_with_high_alignment(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS,
                           status=EdgeStatus.STALE)
        # Simulate high alignment count
        for _ in range(4):
            seeded_db.increment_edge_alignment(
                "child_a", "child_b", EdgeType.CALLS.value, 1, 1)
        result = seeded_db.gc_edges("proj")
        assert result["stale"] == 1

    def test_gc_returns_summary(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS, strength=0.05)
        result = seeded_db.gc_edges("proj")
        assert "orphan" in result
        assert "weak" in result
        assert "stale" in result
        assert "total_removed" in result


# ── Node versioning tests ───────────────────────────────────────────


class TestNodeVersioning:
    def test_initial_version(self, seeded_db):
        node = seeded_db.get_node("child_a")
        assert node.version == 1

    def test_increment_version(self, seeded_db):
        new_ver = seeded_db.increment_node_version("child_a")
        assert new_ver == 2
        node = seeded_db.get_node("child_a")
        assert node.version == 2

    def test_multiple_increments(self, seeded_db):
        for expected in range(2, 6):
            ver = seeded_db.increment_node_version("child_a")
            assert ver == expected


# ── Compaction tests ─────────────────────────────────────────────────


class TestCompaction:
    def test_update_compacted(self, seeded_db):
        seeded_db.update_compacted(
            "child_a",
            "Auth service: handles JWT verification and session management",
            '["only supports JWT", "no OAuth"]',
        )
        node = seeded_db.get_node("child_a")
        assert "JWT verification" in node.compacted
        assert "only supports JWT" in node.constraints

    def test_compacted_initially_empty(self, seeded_db):
        node = seeded_db.get_node("child_a")
        assert node.compacted == ""
        assert node.constraints == "[]"

    def test_constraints_parse_as_json(self, seeded_db):
        constraints = '["must use PostgreSQL", "max 100ms latency"]'
        seeded_db.update_compacted("child_a", "summary", constraints)
        node = seeded_db.get_node("child_a")
        parsed = json.loads(node.constraints)
        assert len(parsed) == 2
        assert "must use PostgreSQL" in parsed

    def test_overwrite_compacted(self, seeded_db):
        seeded_db.update_compacted("child_a", "v1 summary", "[]")
        seeded_db.update_compacted("child_a", "v2 summary", '["new constraint"]')
        node = seeded_db.get_node("child_a")
        assert node.compacted == "v2 summary"
        assert "new constraint" in node.constraints


# ── Snapshot tests ───────────────────────────────────────────────────


class TestSnapshot:
    def test_snapshot_contains_all_data(self, seeded_db):
        seeded_db.set_tags("child_a", [("domain", "auth"), ("entity", "User")])
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS, strength=0.7)
        snap = seeded_db.snapshot("proj")
        assert len(snap["nodes"]) == 4  # root + 3 children
        assert len(snap["tags"]) == 2
        # edges: 3 parent edges + 1 calls edge
        assert len(snap["edges"]) >= 4

    def test_snapshot_nodes_have_all_fields(self, seeded_db):
        snap = seeded_db.snapshot("proj")
        node_dict = snap["nodes"][0]
        assert "node_id" in node_dict
        assert "project" in node_dict
        assert "version" in node_dict
        assert "compacted" in node_dict
        assert "constraints" in node_dict

    def test_snapshot_edges_have_all_fields(self, seeded_db):
        seeded_db.add_edge("child_a", "child_b", EdgeType.CALLS)
        snap = seeded_db.snapshot("proj")
        edge_dict = next(e for e in snap["edges"] if e["edge_type"] == "calls")
        assert "status" in edge_dict
        assert "strength" in edge_dict
        assert "alignment_count" in edge_dict
        assert "contract" in edge_dict

    def test_snapshot_only_project_data(self, seeded_db):
        seeded_db.insert_node(Node(id="other_root", project="other_proj",
                                   level=0, parent_id=None, title="Other"))
        snap = seeded_db.snapshot("proj")
        node_ids = [n["node_id"] for n in snap["nodes"]]
        assert "other_root" not in node_ids


# ── Reconciliation tests ────────────────────────────────────────────


class TestReconcile:
    def test_reconcile_removes_orphans(self, seeded_db):
        valid_ids = {"root", "child_a", "child_b"}
        # child_c is not in valid_ids → should be removed
        result = seeded_db.reconcile("proj", valid_ids)
        assert result["orphan_nodes_removed"] == 1
        assert seeded_db.get_node("child_c") is None

    def test_reconcile_preserves_valid(self, seeded_db):
        valid_ids = {"root", "child_a", "child_b", "child_c"}
        result = seeded_db.reconcile("proj", valid_ids)
        assert result["orphan_nodes_removed"] == 0
        assert seeded_db.get_node("child_a") is not None

    def test_reconcile_cleans_tags_and_edges(self, seeded_db):
        seeded_db.set_tags("child_c", [("domain", "temp")])
        seeded_db.add_edge("child_a", "child_c", EdgeType.CALLS)
        valid_ids = {"root", "child_a", "child_b"}
        seeded_db.reconcile("proj", valid_ids)
        # Tags for child_c should be gone
        tags = seeded_db.get_tags("child_c")
        assert len(tags) == 0
        # Edge to child_c should be gone
        edges = seeded_db.get_edges("child_a")
        to_c = [e for e in edges if e.to_id == "child_c"]
        assert len(to_c) == 0


# ── Migration tests ─────────────────────────────────────────────────


class TestMigration:
    def test_idempotent_migration(self, db):
        """Running migration twice should not error."""
        db._init_schema()
        db._init_schema()
        db.insert_node(Node(id="test", project="p", level=0,
                            parent_id=None, title="Test"))
        assert db.get_node("test") is not None

    def test_new_db_has_all_columns(self, db):
        """A fresh database should have all columns without migration."""
        db.insert_node(Node(id="n", project="p", level=0, parent_id=None,
                            title="N", version=5, compacted="summary",
                            constraints='["c1"]'))
        node = db.get_node("n")
        assert node.version == 5
        assert node.compacted == "summary"
        assert node.constraints == '["c1"]'


# ── Nodes by status tests ───────────────────────────────────────────


class TestGetNodesByStatus:
    def test_get_pending_nodes(self, seeded_db):
        nodes = seeded_db.get_nodes_by_status("proj", NodeStatus.PENDING)
        assert len(nodes) == 4  # all start as pending

    def test_get_done_nodes(self, seeded_db):
        seeded_db.update_node_status("child_a", NodeStatus.DONE)
        seeded_db.update_node_status("child_b", NodeStatus.DONE)
        done = seeded_db.get_nodes_by_status("proj", NodeStatus.DONE)
        assert len(done) == 2
        ids = {n.id for n in done}
        assert "child_a" in ids
        assert "child_b" in ids
