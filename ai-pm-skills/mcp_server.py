#!/usr/bin/env python3
"""MCP Server wrapper for AI PM Skills.

Exposes the AI PM CLI as MCP tools so any MCP-compatible client
(Claude Code, Claude Desktop, etc.) can call them directly.

Run: python mcp_server.py
Or:  uvx mcp run ai-pm-skills

Requires: pip install mcp
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from mcp.server.fastmcp import FastMCP
except ImportError:
    print("MCP SDK not installed. Run: pip install mcp", file=sys.stderr)
    sys.exit(1)

from shared.config import Config, load_config
from shared.db import Database
from shared.models import EdgeStatus, EdgeType, Node, NodeStatus

mcp = FastMCP(
    "ai-pm-skills",
    description="AI Product Manager: adaptive decomposition + backward optimization for complex projects",
)


def _get_db() -> Database:
    return Database(load_config())


# ── Project tools ────────────────────────────────────────────────────


@mcp.tool()
def project_init(name: str, idea: str) -> dict:
    """Initialize a new AI PM project with an idea.

    Args:
        name: Project name (used as directory name)
        idea: The product idea text
    """
    config = load_config()
    db = Database(config)
    project_dir = config.data_dir / name / "files"
    project_dir.mkdir(parents=True, exist_ok=True)

    idea_path = project_dir / "idea.md"
    idea_path.write_text(idea, encoding="utf-8")

    import uuid as _uuid
    root_id = f"{name}_root_{_uuid.uuid4().hex[:6]}"
    root = Node(
        id=root_id, project=name, level=0, parent_id=None,
        status=NodeStatus.PENDING, title="Product Vision",
        detail_path=str(idea_path),
    )
    db.insert_node(root)
    return {"project": name, "root_node": root_id}


@mcp.tool()
def project_status(name: str) -> dict:
    """Get project status with node counts per depth.

    Args:
        name: Project name
    """
    db = _get_db()
    total = db.count_nodes(name)
    all_nodes = db.get_all_nodes(name)
    depth_stats = {}
    for n in all_nodes:
        d = n.level
        if d not in depth_stats:
            depth_stats[d] = {"total": 0, "done": 0, "pending": 0}
        depth_stats[d]["total"] += 1
        if n.status == NodeStatus.DONE:
            depth_stats[d]["done"] += 1
        elif n.status == NodeStatus.PENDING:
            depth_stats[d]["pending"] += 1
    leaf_nodes = db.get_leaf_nodes(name)
    pending_leaves = [n for n in leaf_nodes if n.status == NodeStatus.PENDING]
    return {
        "project": name,
        "total_nodes": total,
        "max_depth": db.get_max_depth(name),
        "pending_leaves": len(pending_leaves),
        "depths": {f"depth_{d}": s for d, s in sorted(depth_stats.items())},
    }


# ── Node tools ───────────────────────────────────────────────────────


@mcp.tool()
def node_add(project: str, title: str, parent_id: str | None = None) -> dict:
    """Add a new node to the project tree. Depth is auto-computed from parent.

    Args:
        project: Project name
        title: Node title
        parent_id: Parent node ID (optional, omit for root)
    """
    import uuid
    db = _get_db()
    depth = 0
    if parent_id:
        parent = db.get_node(parent_id)
        if parent:
            depth = parent.level + 1
    node_id = f"{project}_{uuid.uuid4().hex[:8]}"
    node = Node(id=node_id, project=project, level=depth,
                parent_id=parent_id, status=NodeStatus.PENDING, title=title)
    db.insert_node(node)
    return {"node_id": node_id, "project": project, "depth": depth, "title": title}


@mcp.tool()
def node_get(node_id: str) -> dict:
    """Get a node's details by ID.

    Args:
        node_id: The node identifier
    """
    db = _get_db()
    node = db.get_node(node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}
    return {
        "id": node.id, "project": node.project, "level": node.level,
        "parent_id": node.parent_id, "status": node.status.value,
        "title": node.title, "version": node.version,
        "children": node.children_ids,
    }


@mcp.tool()
def node_children(node_id: str) -> dict:
    """List children of a node.

    Args:
        node_id: Parent node ID
    """
    db = _get_db()
    children = db.get_children(node_id)
    return {"parent": node_id, "children": [
        {"id": c.id, "level": c.level, "title": c.title, "status": c.status.value}
        for c in children
    ]}


@mcp.tool()
def node_update_status(node_id: str, status: str) -> dict:
    """Update a node's status.

    Args:
        node_id: Node ID to update
        status: New status (pending, active, done, invalidated)
    """
    db = _get_db()
    try:
        new_status = NodeStatus(status)
    except ValueError:
        return {"error": f"Invalid status: {status}", "valid": [s.value for s in NodeStatus]}
    db.update_node_status(node_id, new_status)
    return {"node_id": node_id, "new_status": new_status.value}


# ── Tag tools ────────────────────────────────────────────────────────


@mcp.tool()
def tag_set(node_id: str, tags: dict[str, str]) -> dict:
    """Set hyperspace tags on a node.

    Args:
        node_id: Node to tag
        tags: Dictionary of key-value tag pairs
    """
    db = _get_db()
    tag_list = list(tags.items())
    db.set_tags(node_id, tag_list)
    return {"node_id": node_id, "tags_set": len(tag_list)}


@mcp.tool()
def tag_get(node_id: str) -> dict:
    """Get all tags for a node.

    Args:
        node_id: Node ID
    """
    db = _get_db()
    tags = db.get_tags(node_id)
    return {"node_id": node_id, "tags": [{"key": k, "value": v} for k, v in tags]}


# ── Edge tools ───────────────────────────────────────────────────────


@mcp.tool()
def edge_add(from_id: str, to_id: str, edge_type: str, strength: float = 0.5) -> dict:
    """Add an edge between two nodes.

    Args:
        from_id: Source node ID
        to_id: Target node ID
        edge_type: Edge type (calls, produces_consumes, shares, presents, constrains, measures)
        strength: Edge strength 0.0-1.0
    """
    db = _get_db()
    try:
        etype = EdgeType(edge_type)
    except ValueError:
        return {"error": f"Invalid edge type: {edge_type}",
                "valid": [e.value for e in EdgeType]}
    db.add_edge(from_id, to_id, etype, strength=strength)
    return {"from": from_id, "to": to_id, "type": etype.value, "strength": strength}


@mcp.tool()
def edge_list(node_id: str) -> dict:
    """List all edges for a node (both directions).

    Args:
        node_id: Node ID to query edges for
    """
    db = _get_db()
    edges = db.get_edges(node_id)
    return {"node": node_id, "edges": [
        {"from": e.from_id, "to": e.to_id, "type": e.edge_type.value,
         "status": e.status.value, "strength": e.strength,
         "alignment_count": e.alignment_count, "contract": e.contract}
        for e in edges
    ]}


@mcp.tool()
def edge_update(from_id: str, to_id: str, edge_type: str,
                status: str | None = None, strength: float | None = None,
                contract: str | None = None) -> dict:
    """Update an edge's properties.

    Args:
        from_id: Source node ID
        to_id: Target node ID
        edge_type: Edge type
        status: New status (discovered, typed, specified, validated, stale, conflict)
        strength: New strength value
        contract: Interface contract description
    """
    db = _get_db()
    db.update_edge(from_id, to_id, edge_type, status=status,
                   strength=strength, contract=contract)
    return {"from": from_id, "to": to_id, "type": edge_type, "updated": True}


@mcp.tool()
def edge_gc(project: str) -> dict:
    """Garbage collect weak, orphan, and stale edges.

    Args:
        project: Project name
    """
    db = _get_db()
    result = db.gc_edges(project)
    return {"project": project, **result}


# ── Compact tool ─────────────────────────────────────────────────────


@mcp.tool()
def compact(node_id: str, summary: str, constraints: str = "[]") -> dict:
    """Compact a node with a summary and constraints.

    Args:
        node_id: Node to compact
        summary: Compacted summary text
        constraints: JSON array of constraints that survive compression
    """
    db = _get_db()
    node = db.get_node(node_id)
    if not node:
        return {"error": f"Node {node_id} not found"}
    db.update_compacted(node_id, summary, constraints)
    return {"node_id": node_id, "compacted": True}


# ── Snapshot tool ────────────────────────────────────────────────────


@mcp.tool()
def snapshot_save(project: str) -> dict:
    """Save a full project snapshot (versioned).

    Args:
        project: Project name
    """
    config = load_config()
    db = Database(config)
    data = db.snapshot(project)

    snap_dir = config.data_dir / project / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(snap_dir.glob("snapshot_v*.json"))
    version = len(existing) + 1
    snap_path = snap_dir / f"snapshot_v{version}.json"
    snap_path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                         encoding="utf-8")
    return {"project": project, "version": version, "nodes": len(data["nodes"]),
            "edges": len(data["edges"])}


if __name__ == "__main__":
    mcp.run()
