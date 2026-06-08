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
    RESOLVED = "resolved"


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
    """Multi-axis tag vector for clustering. Axes match AXIS_WEIGHTS in cluster.py.

    All axes are list[str] — a node can have multiple values per axis.
    The DB stores these as flat (key, value) tuples in the tags table.
    """
    domain: list[str] = field(default_factory=list)
    entity: list[str] = field(default_factory=list)
    pattern: list[str] = field(default_factory=list)
    actor: list[str] = field(default_factory=list)
    nfr: list[str] = field(default_factory=list)
    biz_metrics: list[str] = field(default_factory=list)
    tech_stack: list[str] = field(default_factory=list)
    data_sensitivity: list[str] = field(default_factory=list)
    revenue_impact: list[str] = field(default_factory=list)
    dependency: list[str] = field(default_factory=list)
    complexity: list[str] = field(default_factory=list)
    user_facing: list[str] = field(default_factory=list)
    timeline_priority: list[str] = field(default_factory=list)

    # Legacy compat: these are accepted in from_dict but mapped to new axes
    _LEGACY_MAP = {
        "entities": "entity",
        "patterns": "pattern",
        "actors": "actor",
        "tech_traits": "tech_stack",
        "priority": "timeline_priority",
        "rule_fingerprint": None,  # dropped — use biz_metrics or entity instead
        "api_shape": None,  # dropped — not representable as flat tags
    }

    AXES = [
        "domain", "entity", "pattern", "actor", "nfr", "biz_metrics",
        "tech_stack", "data_sensitivity", "revenue_impact", "dependency",
        "complexity", "user_facing", "timeline_priority",
    ]

    def to_dict(self) -> dict[str, Any]:
        return {axis: getattr(self, axis) for axis in self.AXES}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HyperspaceVector":
        kwargs: dict[str, Any] = {}
        for key, value in data.items():
            # Map legacy field names
            mapped = cls._LEGACY_MAP.get(key, key)
            if mapped is None:
                continue  # dropped field
            if mapped not in cls.AXES:
                continue  # unknown field
            if isinstance(value, str):
                kwargs.setdefault(mapped, []).append(value)
            elif isinstance(value, list):
                kwargs.setdefault(mapped, []).extend(
                    v for v in value if isinstance(v, str)
                )
            # dicts (like old api_shape) are silently dropped
        return cls(**{k: v for k, v in kwargs.items() if k in cls.AXES})

    def flat_tags(self) -> list[tuple[str, str]]:
        """Convert to flat (axis, value) tuples for DB storage and clustering."""
        tags: list[tuple[str, str]] = []
        for axis in self.AXES:
            for value in getattr(self, axis):
                tags.append((axis, value))
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
