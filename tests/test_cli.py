"""Tests for CLI command functions: edge, compact, snapshot, checkpoint, reconcile.

Tests call the command handler functions directly (not subprocess),
using argparse.Namespace to mock CLI args, so we can control the workspace.
"""

from __future__ import annotations

import argparse
import io
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.config import Config
from shared.db import Database
from shared.models import EdgeType, Node, NodeStatus

# Import CLI command functions
from cli import (
    cmd_cluster_run,
    cmd_compact,
    cmd_checkpoint_save,
    cmd_checkpoint_rollback,
    cmd_edge_add,
    cmd_edge_gc,
    cmd_edge_list,
    cmd_edge_update,
    cmd_node_add,
    cmd_node_get,
    cmd_node_list,
    cmd_reconcile,
    cmd_search_similar,
    cmd_snapshot_load,
    cmd_snapshot_save,
)


def capture_json(func, args_ns: argparse.Namespace) -> dict:
    """Call a CLI function and capture its JSON output."""
    buf = io.StringIO()
    with patch("sys.stdout", buf):
        func(args_ns)
    output = buf.getvalue().strip()
    return json.loads(output) if output else {}


@pytest.fixture
def workspace():
    """Temp workspace with config."""
    tmp = tempfile.mkdtemp()
    return tmp


@pytest.fixture
def seeded(workspace):
    """Workspace with a small project tree: root -> [a, b]."""
    config = Config(workspace_path=workspace)
    db = Database(config)

    project_dir = Path(workspace) / "test_proj" / "files"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "idea.md").write_text("Test idea", encoding="utf-8")

    db.insert_node(Node(id="root", project="test_proj", level=0,
                        parent_id=None, title="Root"))
    db.insert_node(Node(id="a", project="test_proj", level=1,
                        parent_id="root", title="Module A"))
    db.insert_node(Node(id="b", project="test_proj", level=1,
                        parent_id="root", title="Module B"))
    return config


# ── Edge CLI tests ───────────────────────────────────────────────────


class TestEdgeAddCLI:
    def test_add_edge(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            ns = argparse.Namespace(from_id="a", to_id="b", type="calls", strength="0.8")
            result = capture_json(cmd_edge_add, ns)
        assert result["from"] == "a"
        assert result["to"] == "b"
        assert result["type"] == "calls"
        assert result["strength"] == 0.8

    def test_add_edge_default_strength(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            ns = argparse.Namespace(from_id="a", to_id="b", type="shares", strength=None)
            result = capture_json(cmd_edge_add, ns)
        assert result["strength"] == 0.5

    def test_add_invalid_type(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            ns = argparse.Namespace(from_id="a", to_id="b", type="bogus", strength=None)
            result = capture_json(cmd_edge_add, ns)
        assert "error" in result
        assert "valid" in result

    def test_add_all_6_types(self, seeded):
        for etype in ["calls", "produces_consumes", "shares", "presents",
                      "constrains", "measures"]:
            with patch("cli.load_config", return_value=seeded):
                ns = argparse.Namespace(from_id="a", to_id="b", type=etype, strength=None)
                result = capture_json(cmd_edge_add, ns)
            assert result["type"] == etype


class TestEdgeListCLI:
    def test_list_edges(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            cmd_edge_add(argparse.Namespace(from_id="a", to_id="b",
                                            type="calls", strength="0.7"))
            ns = argparse.Namespace(node_id="a")
            result = capture_json(cmd_edge_list, ns)
        assert result["node"] == "a"
        edge_types = [e["type"] for e in result["edges"]]
        assert "calls" in edge_types

    def test_list_includes_all_fields(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            cmd_edge_add(argparse.Namespace(from_id="a", to_id="b",
                                            type="calls", strength=None))
            result = capture_json(cmd_edge_list, argparse.Namespace(node_id="a"))
        call_edges = [e for e in result["edges"] if e["type"] == "calls"]
        assert len(call_edges) == 1
        e = call_edges[0]
        assert "status" in e
        assert "strength" in e
        assert "alignment_count" in e
        assert "contract" in e


class TestEdgeUpdateCLI:
    def test_update_status(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            cmd_edge_add(argparse.Namespace(from_id="a", to_id="b",
                                            type="calls", strength=None))
            ns = argparse.Namespace(from_id="a", to_id="b", type="calls",
                                    status="validated", strength=None, contract=None)
            result = capture_json(cmd_edge_update, ns)
        assert result["updated"] is True

    def test_update_contract(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            cmd_edge_add(argparse.Namespace(from_id="a", to_id="b",
                                            type="calls", strength=None))
            contract = "POST /api/order -> 201"
            ns = argparse.Namespace(from_id="a", to_id="b", type="calls",
                                    status=None, strength=None, contract=contract)
            result = capture_json(cmd_edge_update, ns)
        assert result["updated"] is True


class TestEdgeGCCLI:
    def test_gc_weak_edges(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            cmd_edge_add(argparse.Namespace(from_id="a", to_id="b",
                                            type="produces_consumes", strength="0.05"))
            result = capture_json(cmd_edge_gc, argparse.Namespace(project="test_proj"))
        assert result["project"] == "test_proj"
        assert result["total_removed"] >= 1
        assert result["weak"] >= 1

    def test_gc_no_removals(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            cmd_edge_add(argparse.Namespace(from_id="a", to_id="b",
                                            type="calls", strength="0.9"))
            result = capture_json(cmd_edge_gc, argparse.Namespace(project="test_proj"))
        assert result["weak"] == 0


# ── Compact CLI tests ────────────────────────────────────────────────


class TestCompactCLI:
    def test_compact_node(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            ns = argparse.Namespace(
                node_id="a",
                summary="Auth module: JWT + sessions",
                constraints='["only JWT", "no OAuth"]',
            )
            result = capture_json(cmd_compact, ns)
        assert result["node_id"] == "a"
        assert result["compacted"] is True

    def test_compact_nonexistent(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            ns = argparse.Namespace(node_id="nonexistent",
                                    summary="x", constraints="[]")
            result = capture_json(cmd_compact, ns)
        assert "error" in result

    def test_compact_default_constraints(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            ns = argparse.Namespace(node_id="a",
                                    summary="summary", constraints="[]")
            result = capture_json(cmd_compact, ns)
        assert result["compacted"] is True

    def test_compact_persists(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            cmd_compact(argparse.Namespace(
                node_id="a",
                summary="Auth: JWT validation",
                constraints='["must use RS256"]',
            ))
        db = Database(seeded)
        node = db.get_node("a")
        assert "JWT validation" in node.compacted
        assert "RS256" in node.constraints


# ── Snapshot CLI tests ───────────────────────────────────────────────


class TestSnapshotCLI:
    def test_snapshot_save(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            result = capture_json(cmd_snapshot_save,
                                  argparse.Namespace(project="test_proj"))
        assert result["project"] == "test_proj"
        assert result["version"] == 1
        assert result["nodes"] == 3
        assert Path(result["path"]).exists()

    def test_snapshot_increments_version(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            capture_json(cmd_snapshot_save, argparse.Namespace(project="test_proj"))
            result = capture_json(cmd_snapshot_save,
                                  argparse.Namespace(project="test_proj"))
        assert result["version"] == 2

    def test_snapshot_load_latest(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            capture_json(cmd_snapshot_save, argparse.Namespace(project="test_proj"))
            result = capture_json(cmd_snapshot_load,
                                  argparse.Namespace(project="test_proj", version=None))
        assert result["nodes"] == 3

    def test_snapshot_load_specific_version(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            capture_json(cmd_snapshot_save, argparse.Namespace(project="test_proj"))
            capture_json(cmd_snapshot_save, argparse.Namespace(project="test_proj"))
            result = capture_json(cmd_snapshot_load,
                                  argparse.Namespace(project="test_proj", version="1"))
        assert result["nodes"] == 3

    def test_snapshot_load_no_snapshots(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            result = capture_json(cmd_snapshot_load,
                                  argparse.Namespace(project="test_proj", version=None))
        assert "error" in result

    def test_snapshot_contains_edges(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            cmd_edge_add(argparse.Namespace(from_id="a", to_id="b",
                                            type="calls", strength="0.7"))
            result = capture_json(cmd_snapshot_save,
                                  argparse.Namespace(project="test_proj"))
        assert result["edges"] >= 3  # 2 parent + 1 calls


# ── Checkpoint CLI tests ─────────────────────────────────────────────


class TestCheckpointCLI:
    def test_checkpoint_save(self, seeded):
        diff = json.dumps({"created_nodes": ["child_1"], "status_before": {}})
        with patch("cli.load_config", return_value=seeded):
            result = capture_json(cmd_checkpoint_save,
                                  argparse.Namespace(project="test_proj",
                                                     iteration="1", diff=diff))
        assert result["project"] == "test_proj"
        assert result["iteration"] == "1"
        assert Path(result["path"]).exists()

    def test_checkpoint_rollback(self, seeded):
        db = Database(seeded)
        db.insert_node(Node(id="child_1", project="test_proj", level=2,
                            parent_id="a", title="Child 1"))
        diff = json.dumps({"created_nodes": ["child_1"], "status_before": {}})
        with patch("cli.load_config", return_value=seeded):
            capture_json(cmd_checkpoint_save,
                         argparse.Namespace(project="test_proj",
                                            iteration="1", diff=diff))
            result = capture_json(cmd_checkpoint_rollback,
                                  argparse.Namespace(project="test_proj",
                                                     iteration="1"))
        assert "child_1" in result["invalidated_nodes"]

    def test_checkpoint_rollback_nonexistent(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            result = capture_json(cmd_checkpoint_rollback,
                                  argparse.Namespace(project="test_proj",
                                                     iteration="99"))
        assert "error" in result

    def test_checkpoint_removes_later_cps(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            for i in range(1, 4):
                diff = json.dumps({"created_nodes": [], "status_before": {}})
                capture_json(cmd_checkpoint_save,
                             argparse.Namespace(project="test_proj",
                                                iteration=str(i), diff=diff))
            result = capture_json(cmd_checkpoint_rollback,
                                  argparse.Namespace(project="test_proj",
                                                     iteration="2"))
        assert 2 in result["removed_checkpoints"]
        assert 3 in result["removed_checkpoints"]


# ── Reconcile CLI tests ──────────────────────────────────────────────


class TestReconcileCLI:
    def test_reconcile(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            result = capture_json(cmd_reconcile,
                                  argparse.Namespace(project="test_proj"))
        assert result["project"] == "test_proj"
        assert "edge_gc" in result


# ── Cluster CLI tests ────────────────────────────────────────────────


class TestClusterCLI:
    def test_cluster_with_similar_tags(self, seeded):
        db = Database(seeded)
        db.set_tags("a", [("domain", "payments"), ("entity", "Order"),
                          ("pattern", "Saga")])
        db.set_tags("b", [("domain", "payments"), ("entity", "Order"),
                          ("pattern", "Repository")])
        with patch("cli.load_config", return_value=seeded):
            result = capture_json(cmd_cluster_run,
                                  argparse.Namespace(project="test_proj", level="1"))
        assert result["total_nodes"] == 2
        assert result["clusters_found"] >= 1

    def test_cluster_dissimilar_tags(self, seeded):
        db = Database(seeded)
        db.set_tags("a", [("domain", "payments")])
        db.set_tags("b", [("domain", "logistics")])
        with patch("cli.load_config", return_value=seeded):
            result = capture_json(cmd_cluster_run,
                                  argparse.Namespace(project="test_proj", level="1"))
        assert result["clusters_found"] == 0

    def test_cluster_insufficient_nodes(self, seeded):
        db = Database(seeded)
        db.insert_node(Node(id="solo", project="test_proj", level=5,
                            parent_id="a", title="Solo"))
        with patch("cli.load_config", return_value=seeded):
            result = capture_json(cmd_cluster_run,
                                  argparse.Namespace(project="test_proj", level="5"))
        assert "Need at least 2" in result.get("message", "")


# ── Search CLI tests ─────────────────────────────────────────────────


class TestSearchCLI:
    def test_search_similar(self, seeded):
        db = Database(seeded)
        db.set_tags("a", [("domain", "payments"), ("entity", "Order")])
        db.set_tags("b", [("domain", "payments"), ("entity", "Invoice")])
        with patch("cli.load_config", return_value=seeded):
            result = capture_json(cmd_search_similar,
                                  argparse.Namespace(id="a", n="5"))
        assert result["node"] == "a"
        assert len(result["similar"]) >= 1
        assert result["similar"][0]["id"] == "b"

    def test_search_no_tags(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            result = capture_json(cmd_search_similar,
                                  argparse.Namespace(id="a", n="5"))
        assert result["similar"] == []


# ── Node CLI tests ───────────────────────────────────────────────────


class TestNodeCLI:
    def test_node_add(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            result = capture_json(cmd_node_add,
                                  argparse.Namespace(project="test_proj", level="2",
                                                     title="Sub Module", parent="a"))
        assert result["project"] == "test_proj"
        assert result["level"] == "2"
        assert result["title"] == "Sub Module"

    def test_node_get(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            result = capture_json(cmd_node_get, argparse.Namespace(id="a"))
        assert result["id"] == "a"
        assert result["title"] == "Module A"
        assert result["level"] == 1

    def test_node_list(self, seeded):
        with patch("cli.load_config", return_value=seeded):
            result = capture_json(cmd_node_list,
                                  argparse.Namespace(project="test_proj", level="1"))
        assert result["count"] == 2
