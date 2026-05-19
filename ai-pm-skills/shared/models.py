"""Data models for ai-pm-skills.

All core data structures used across skills.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class NodeStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    DONE = "done"
    INVALIDATED = "invalidated"


class EdgeType(str, Enum):
    PARENT = "parent"
    DEPENDENCY = "dependency"
    SHARED_REF = "shared_ref"
    CALLS = "calls"
    PRODUCES_CONSUMES = "produces_consumes"
    SHARES = "shares"
    PRESENTS = "presents"
    CONSTRAINS = "constrains"
    MEASURES = "measures"


class EdgeStatus(str, Enum):
    DISCOVERED = "discovered"
    TYPED = "typed"
    SPECIFIED = "specified"
    VALIDATED = "validated"
    STALE = "stale"
    CONFLICT = "conflict"


class CompactionLevel(str, Enum):
    FULL = "full"
    COMPACTED = "compacted"
    INTERFACE = "interface"


class MergeStrategy(str, Enum):
    EXTRACT_SHARED = "extract_shared"
    MERGE_DUPLICATES = "merge_duplicates"
    KEEP_SEPARATE = "keep_separate"
    PARAMETERIZE = "parameterize"


@dataclass
class Node:
    id: str
    project: str
    level: int
    parent_id: str | None
    status: NodeStatus = NodeStatus.PENDING
    children_ids: list[str] = field(default_factory=list)
    dependency_ids: list[str] = field(default_factory=list)
    shared_component_ids: list[str] = field(default_factory=list)
    title: str = ""
    detail_path: str = ""
    summary_path: str = ""
    vector_path: str = ""
    version: int = 1
    compacted: str = ""
    constraints: str = "[]"
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class HyperspaceVector:
    domain: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    api_shape: dict[str, list[str]] = field(default_factory=lambda: {
        "inputs": [],
        "outputs": [],
        "side_effects": [],
    })
    tech_traits: list[str] = field(default_factory=list)
    actors: list[str] = field(default_factory=list)
    nfr: list[str] = field(default_factory=list)
    biz_metrics: list[str] = field(default_factory=list)
    rule_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "entities": self.entities,
            "patterns": self.patterns,
            "api_shape": self.api_shape,
            "tech_traits": self.tech_traits,
            "actors": self.actors,
            "nfr": self.nfr,
            "biz_metrics": self.biz_metrics,
            "rule_fingerprint": self.rule_fingerprint,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HyperspaceVector:
        return cls(
            domain=data.get("domain", []),
            entities=data.get("entities", []),
            patterns=data.get("patterns", []),
            api_shape=data.get("api_shape", {"inputs": [], "outputs": [], "side_effects": []}),
            tech_traits=data.get("tech_traits", []),
            actors=data.get("actors", []),
            nfr=data.get("nfr", []),
            biz_metrics=data.get("biz_metrics", []),
            rule_fingerprint=data.get("rule_fingerprint", ""),
        )

    def flat_tags(self) -> list[tuple[str, str]]:
        tags: list[tuple[str, str]] = []
        for d in self.domain:
            tags.append(("domain", d))
        for e in self.entities:
            tags.append(("entity", e))
        for p in self.patterns:
            tags.append(("pattern", p))
        for t in self.tech_traits:
            tags.append(("tech_trait", t))
        for a in self.actors:
            tags.append(("actor", a))
        for n in self.nfr:
            tags.append(("nfr", n))
        for b in self.biz_metrics:
            tags.append(("biz_metric", b))
        return tags


@dataclass
class Cluster:
    id: str
    members: list[str] = field(default_factory=list)
    reason: str = ""
    shared_features: list[str] = field(default_factory=list)
    suggested_action: MergeStrategy = MergeStrategy.KEEP_SEPARATE
    centroid_tags: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class Edge:
    from_id: str
    to_id: str
    edge_type: EdgeType
    status: EdgeStatus = EdgeStatus.DISCOVERED
    strength: float = 0.5
    alignment_count: int = 0
    contract: str = ""
    from_version: int = 0
    to_version: int = 0
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class MergePlan:
    cluster_id: str
    strategy: MergeStrategy
    new_component_design: str = ""
    affected_nodes: list[str] = field(default_factory=list)
    challenger_verdict: str = ""
    approved: bool = False
    rejection_reason: str = ""
