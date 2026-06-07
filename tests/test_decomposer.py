"""Tests for the decomposer module."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.config import Config
from shared.db import Database
from shared.models import HyperspaceVector, Node, NodeStatus

DECOMPOSER_DIR = Path(__file__).resolve().parents[1] / "skills" / "ai-pm-decomposer"
sys.path.insert(0, str(DECOMPOSER_DIR / "scripts"))

from decompose import (
    extract_vector_from_child,
    load_prompt_template,
    parse_children_from_response,
    render_prompt,
)


class TestPromptTemplates:
    def test_unified_template_exists(self):
        refs = DECOMPOSER_DIR / "references"
        template_path = refs / "prompt_decompose.md"
        assert template_path.exists(), "Unified decompose template not found"

    def test_no_fixed_layer_templates(self):
        refs = DECOMPOSER_DIR / "references"
        old_templates = list(refs.glob("prompt_L*_*.md"))
        assert len(old_templates) == 0, f"Found legacy fixed-layer templates: {old_templates}"

    def test_load_template(self):
        template = load_prompt_template()
        assert "{{ global_summary }}" in template
        assert "{{ current_task }}" in template

    def test_render_prompt(self):
        template = "Hello {{ name }}, you are working on {{ task }}"
        result = render_prompt(template, {"name": "Alice", "task": "testing"})
        assert result == "Hello Alice, you are working on testing"

    def test_vector_schema_valid(self):
        schema_path = DECOMPOSER_DIR / "references" / "vector_schema.json"
        assert schema_path.exists()
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert "properties" in schema
        expected_axes = ["domain", "entities", "patterns", "api_shape",
                        "tech_traits", "actors", "nfr", "rule_fingerprint"]
        for axis in expected_axes:
            assert axis in schema["properties"], f"Missing axis: {axis}"


class TestResponseParsing:
    def test_parse_json_block(self):
        response = '''Some text before
```json
{"children": [{"title": "Auth Service", "description": "Handles auth"}]}
```
Some text after'''
        children = parse_children_from_response(response)
        assert len(children) == 1
        assert children[0]["title"] == "Auth Service"

    def test_parse_direct_json(self):
        response = json.dumps({"children": [{"title": "A"}, {"title": "B"}]})
        children = parse_children_from_response(response)
        assert len(children) == 2

    def test_parse_json_array(self):
        response = json.dumps([{"title": "X"}, {"title": "Y"}])
        children = parse_children_from_response(response)
        assert len(children) == 2

    def test_parse_invalid_json(self):
        response = "This is not JSON at all"
        children = parse_children_from_response(response)
        assert children == []


class TestVectorExtraction:
    def test_extract_vector(self):
        child = {
            "title": "Test",
            "vector": {
                "domain": ["payments"],
                "entities": ["Order", "Payment"],
                "patterns": ["Saga"],
                "api_shape": {"inputs": ["order_id"], "outputs": ["receipt"], "side_effects": ["charge"]},
                "tech_traits": ["idempotent"],
                "actors": ["consumer"],
                "nfr": ["low_latency"],
                "rule_fingerprint": "order -> payment -> confirmation",
            },
        }
        vec = extract_vector_from_child(child)
        assert vec.domain == ["payments"]
        assert vec.entities == ["Order", "Payment"]
        assert vec.rule_fingerprint == "order -> payment -> confirmation"

    def test_extract_empty_vector(self):
        child = {"title": "Test"}
        vec = extract_vector_from_child(child)
        assert vec.domain == []
        assert vec.rule_fingerprint == ""

    def test_flat_tags(self):
        vec = HyperspaceVector(
            domain=["payments", "orders"],
            entities=["Order"],
            actors=["consumer", "merchant"],
        )
        tags = vec.flat_tags()
        assert ("domain", "payments") in tags
        assert ("domain", "orders") in tags
        assert ("entity", "Order") in tags
        assert ("actor", "consumer") in tags
        assert ("actor", "merchant") in tags


class TestDatabaseIntegration:
    def setup_method(self):
        self.tmp = tempfile.mkdtemp()
        self.config = Config(workspace_path=self.tmp)
        self.db = Database(self.config)

    def test_insert_and_get_node(self):
        node = Node(
            id="test_001",
            project="test_project",
            level=0,
            parent_id=None,
            status=NodeStatus.PENDING,
            title="Test Root",
        )
        self.db.insert_node(node)
        retrieved = self.db.get_node("test_001")
        assert retrieved is not None
        assert retrieved.title == "Test Root"
        assert retrieved.level == 0

    def test_parent_child_relationship(self):
        parent = Node(id="p1", project="test", level=0, parent_id=None, title="Parent")
        child = Node(id="c1", project="test", level=1, parent_id="p1", title="Child")
        self.db.insert_node(parent)
        self.db.insert_node(child)

        children = self.db.get_children("p1")
        assert len(children) == 1
        assert children[0].id == "c1"

    def test_ancestor_chain(self):
        self.db.insert_node(Node(id="a", project="t", level=0, parent_id=None, title="A"))
        self.db.insert_node(Node(id="b", project="t", level=1, parent_id="a", title="B"))
        self.db.insert_node(Node(id="c", project="t", level=2, parent_id="b", title="C"))

        chain = self.db.get_ancestor_chain("c")
        assert len(chain) == 3
        assert chain[0].id == "a"
        assert chain[1].id == "b"
        assert chain[2].id == "c"

    def test_tags(self):
        self.db.insert_node(Node(id="n1", project="t", level=0, parent_id=None, title="N"))
        self.db.set_tags("n1", [("domain", "payments"), ("entity", "Order")])

        tags = self.db.get_tags("n1")
        assert ("domain", "payments") in tags
        assert ("entity", "Order") in tags

    def test_find_by_tag(self):
        self.db.insert_node(Node(id="n1", project="t", level=0, parent_id=None, title="N1"))
        self.db.insert_node(Node(id="n2", project="t", level=0, parent_id=None, title="N2"))
        self.db.set_tags("n1", [("domain", "payments")])
        self.db.set_tags("n2", [("domain", "payments"), ("domain", "orders")])

        found = self.db.find_nodes_by_tag("domain", "payments")
        assert "n1" in found
        assert "n2" in found

    def test_update_status(self):
        self.db.insert_node(Node(id="n1", project="t", level=0, parent_id=None, title="N"))
        self.db.update_node_status("n1", NodeStatus.DONE)
        node = self.db.get_node("n1")
        assert node is not None
        assert node.status == NodeStatus.DONE
