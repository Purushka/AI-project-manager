"""Tests for the context assembly module."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.config import Config
from shared.db import Database
from shared.llm import estimate_tokens
from shared.models import Node, NodeStatus

CONTEXT_DIR = Path(__file__).resolve().parents[1] / "skills" / "ai-pm-context"
sys.path.insert(0, str(CONTEXT_DIR / "scripts"))

from assemble import AssembledContext, assemble_context, truncate_to_budget


class TestTruncation:
    def test_within_budget(self):
        text = "Short text"
        result = truncate_to_budget(text, 1000)
        assert result == text

    def test_over_budget(self):
        text = "x" * 100000
        result = truncate_to_budget(text, 100)
        assert len(result) < len(text)
        assert "[truncated]" in result

    def test_empty_text(self):
        result = truncate_to_budget("", 100)
        assert result == ""


class TestTokenEstimation:
    def test_estimate(self):
        text = "Hello world this is a test"
        tokens = estimate_tokens(text)
        assert tokens > 0
        assert tokens < len(text)

    def test_empty(self):
        assert estimate_tokens("") == 0


class TestAssembledContext:
    def test_total_tokens(self):
        ctx = AssembledContext(
            global_summary="a" * 40,
            ancestor_chain="b" * 80,
            token_usage={"global_summary": 10, "ancestor_chain": 20,
                        "shared_interfaces": 0, "current_task": 0},
        )
        assert ctx.total_tokens == 30

    def test_to_dict(self):
        ctx = AssembledContext(
            global_summary="gs",
            ancestor_chain="ac",
            shared_interfaces="si",
            current_task="ct",
        )
        d = ctx.to_dict()
        assert d["global_summary"] == "gs"
        assert d["ancestor_chain"] == "ac"
        assert d["shared_interfaces"] == "si"
        assert d["current_task"] == "ct"


class TestContextAssemblyIntegration:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.config = Config(workspace_path=self.tmp)
        self.db = Database(self.config)
        self.project = "test_project"

        project_dir = Path(self.tmp) / self.project / "files"
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "idea.md").write_text("Test product idea", encoding="utf-8")

        self.db.insert_node(Node(
            id="root",
            project=self.project,
            level=0,
            parent_id=None,
            title="Root",
            detail_path=str(project_dir / "idea.md"),
        ))

    def test_assemble_root_node(self):
        ctx = assemble_context("root", self.project, config=self.config)
        assert ctx.current_task == "Test product idea"
        assert ctx.total_tokens > 0

    def test_budget_tracking(self):
        ctx = assemble_context("root", self.project, config=self.config)
        assert "global_summary" in ctx.token_usage
        assert "ancestor_chain" in ctx.token_usage
        assert "shared_interfaces" in ctx.token_usage
        assert "current_task" in ctx.token_usage
