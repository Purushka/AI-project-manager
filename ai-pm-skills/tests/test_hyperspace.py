"""Tests for the hyperspace clustering module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.models import HyperspaceVector, MergeStrategy

HYPERSPACE_DIR = Path(__file__).resolve().parents[1] / "skills" / "ai-pm-hyperspace"
sys.path.insert(0, str(HYPERSPACE_DIR / "scripts"))

from cluster import jaccard_similarity, structural_cluster


class TestJaccardSimilarity:
    def test_identical_sets(self):
        assert jaccard_similarity({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert jaccard_similarity({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        sim = jaccard_similarity({"a", "b", "c"}, {"b", "c", "d"})
        assert abs(sim - 0.5) < 0.01

    def test_empty_sets(self):
        assert jaccard_similarity(set(), set()) == 0.0

    def test_one_empty(self):
        assert jaccard_similarity({"a"}, set()) == 0.0


class TestStructuralCluster:
    def test_two_similar_nodes(self):
        vectors = {
            "node_a": HyperspaceVector(
                domain=["payments", "orders"],
                entities=["Order", "Payment"],
                patterns=["Saga"],
                actors=["consumer"],
            ),
            "node_b": HyperspaceVector(
                domain=["payments", "orders"],
                entities=["Order", "Refund"],
                patterns=["Saga"],
                actors=["consumer"],
            ),
        }
        clusters = structural_cluster(vectors)
        assert len(clusters) >= 1
        assert len(clusters[0].members) == 2

    def test_no_similar_nodes(self):
        vectors = {
            "node_a": HyperspaceVector(
                domain=["payments"],
                entities=["Payment"],
                patterns=["Saga"],
                actors=["consumer"],
            ),
            "node_b": HyperspaceVector(
                domain=["logistics"],
                entities=["Delivery"],
                patterns=["Observer"],
                actors=["rider"],
            ),
        }
        clusters = structural_cluster(vectors)
        assert len(clusters) == 0

    def test_three_nodes_two_similar(self):
        vectors = {
            "node_a": HyperspaceVector(
                domain=["payments"],
                entities=["Order"],
                patterns=["Repository"],
                actors=["consumer"],
            ),
            "node_b": HyperspaceVector(
                domain=["payments"],
                entities=["Order"],
                patterns=["Repository"],
                actors=["merchant"],
            ),
            "node_c": HyperspaceVector(
                domain=["analytics"],
                entities=["Report"],
                patterns=["CQRS"],
                actors=["admin"],
            ),
        }
        clusters = structural_cluster(vectors)
        similar_cluster = [c for c in clusters if "node_a" in c.members and "node_b" in c.members]
        assert len(similar_cluster) == 1
        assert "node_c" not in similar_cluster[0].members

    def test_single_node_no_cluster(self):
        vectors = {
            "node_a": HyperspaceVector(domain=["x"]),
        }
        clusters = structural_cluster(vectors)
        assert len(clusters) == 0

    def test_empty_input(self):
        clusters = structural_cluster({})
        assert clusters == []
