#!/usr/bin/env python3
"""AI PM CLI - Shell interface for OpenClaw agent to call.

Usage:
    python cli.py project init <name> <idea_text>
    python cli.py project status <name>
    python cli.py project list
    python cli.py node add <project> <title> [--parent <id>] [--depth <n>]
    python cli.py node get <id>
    python cli.py node children <id>
    python cli.py node ancestors <id>
    python cli.py node status <id> <new_status>
    python cli.py node list <project> [--depth <n>]
    python cli.py tag set <node_id> <key=value> [key=value ...]
    python cli.py tag get <node_id>
    python cli.py tag find <key> <value>
    python cli.py cluster run <project> [--depth <n>]
    python cli.py search similar <node_id> [--n <count>]
    python cli.py export <project> [-o output.md]
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from shared.config import Config, load_config
from shared.db import Database
from shared.models import (
    Cluster, Edge, EdgeStatus, EdgeType,
    HyperspaceVector, Node, NodeStatus,
)


def _json_out(data: dict | list) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False, default=str))


# ── Project commands ───────────────────────────────────────────────

def cmd_project_init(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    project = args.name

    project_dir = config.data_dir / project / "files"
    project_dir.mkdir(parents=True, exist_ok=True)

    idea_path = project_dir / "idea.md"
    idea_text = args.idea
    if Path(idea_text).is_file():
        idea_text = Path(idea_text).read_text(encoding="utf-8")
    idea_path.write_text(idea_text, encoding="utf-8")

    root_id = f"{project}_root_{uuid.uuid4().hex[:6]}"
    root = Node(
        id=root_id, project=project, level=0, parent_id=None,
        status=NodeStatus.PENDING, title="Product Vision",
        detail_path=str(idea_path),
    )
    db.insert_node(root)

    status_path = config.data_dir / project / "status.md"
    status_path.write_text(
        f"# {project}\n- 阶段: 访谈\n- 根节点: {root_id}\n",
        encoding="utf-8",
    )
    _json_out({"project": project, "root_node": root_id, "idea_path": str(idea_path)})


def cmd_project_status(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    project = args.name
    total = db.count_nodes(project)
    all_nodes = db.get_all_nodes(project)
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
    depths = {f"depth_{d}": s for d, s in sorted(depth_stats.items())}
    leaf_nodes = db.get_leaf_nodes(project)
    pending_leaves = [n for n in leaf_nodes if n.status == NodeStatus.PENDING]
    _json_out({
        "project": project,
        "total_nodes": total,
        "max_depth": db.get_max_depth(project),
        "pending_leaves": len(pending_leaves),
        "depths": depths,
    })


def cmd_project_list(args: argparse.Namespace) -> None:
    config = load_config()
    projects_dir = config.data_dir
    projects = []
    if projects_dir.exists():
        for d in sorted(projects_dir.iterdir()):
            if d.is_dir() and (d / "files").exists():
                projects.append(d.name)
    _json_out({"projects": projects})


# ── Node commands ──────────────────────────────────────────────────

def cmd_node_add(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    depth = int(args.depth) if args.depth is not None else 0
    if args.parent:
        parent = db.get_node(args.parent)
        if parent:
            depth = parent.level + 1
    node_id = f"{args.project}_{uuid.uuid4().hex[:8]}"
    node = Node(
        id=node_id, project=args.project, level=depth,
        parent_id=args.parent, status=NodeStatus.PENDING, title=args.title,
    )
    db.insert_node(node)
    _json_out({"node_id": node_id, "project": args.project, "depth": depth, "title": args.title})


def cmd_node_get(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    node = db.get_node(args.id)
    if not node:
        _json_out({"error": f"Node {args.id} not found"})
        return
    _json_out({
        "id": node.id, "project": node.project, "level": node.level,
        "parent_id": node.parent_id, "status": node.status.value,
        "title": node.title, "children": node.children_ids,
        "dependencies": node.dependency_ids, "shared_refs": node.shared_component_ids,
    })


def cmd_node_children(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    children = db.get_children(args.id)
    _json_out({"parent": args.id, "children": [
        {"id": c.id, "level": c.level, "title": c.title, "status": c.status.value}
        for c in children
    ]})


def cmd_node_ancestors(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    chain = db.get_ancestor_chain(args.id)
    _json_out({"node": args.id, "ancestors": [
        {"id": n.id, "level": n.level, "title": n.title} for n in chain
    ]})


def cmd_node_update_status(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    try:
        status = NodeStatus(args.new_status)
    except ValueError:
        _json_out({"error": f"Invalid status: {args.new_status}", "valid": [s.value for s in NodeStatus]})
        return
    db.update_node_status(args.id, status)
    _json_out({"node_id": args.id, "new_status": status.value})


def cmd_node_list(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    if args.depth is not None:
        nodes = db.get_nodes_by_level(args.project, int(args.depth))
    else:
        nodes = db.get_all_nodes(args.project)
    _json_out({"project": args.project, "count": len(nodes), "nodes": [
        {"id": n.id, "level": n.level, "title": n.title, "status": n.status.value}
        for n in nodes
    ]})


# ── Tag commands ───────────────────────────────────────────────────

def cmd_tag_set(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    tags = []
    for kv in args.tags:
        if "=" not in kv:
            _json_out({"error": f"Invalid tag format: {kv}, expected key=value"})
            return
        k, v = kv.split("=", 1)
        tags.append((k, v))
    db.set_tags(args.node_id, tags)
    _json_out({"node_id": args.node_id, "tags_set": len(tags)})


def cmd_tag_get(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    tags = db.get_tags(args.node_id)
    _json_out({"node_id": args.node_id, "tags": [{"key": k, "value": v} for k, v in tags]})


def cmd_tag_find(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    nodes = db.find_nodes_by_tag(args.key, args.value)
    _json_out({"key": args.key, "value": args.value, "matching_nodes": nodes})


# ── Cluster command ────────────────────────────────────────────────

def cmd_cluster_run(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    if args.depth is not None:
        nodes = db.get_nodes_by_level(args.project, int(args.depth))
    else:
        nodes = db.get_leaf_nodes(args.project)

    if len(nodes) < 2:
        _json_out({"message": "Need at least 2 nodes to cluster", "node_count": len(nodes)})
        return

    # Structural clustering via Jaccard on tags
    node_tags: dict[str, set[str]] = {}
    for n in nodes:
        tags = db.get_tags(n.id)
        node_tags[n.id] = {f"{k}:{v}" for k, v in tags}

    clusters: list[dict] = []
    visited: set[str] = set()
    node_ids = list(node_tags.keys())

    for i, nid_a in enumerate(node_ids):
        if nid_a in visited:
            continue
        cluster_members = [nid_a]
        visited.add(nid_a)
        tags_a = node_tags[nid_a]
        if not tags_a:
            continue
        for nid_b in node_ids[i + 1:]:
            if nid_b in visited:
                continue
            tags_b = node_tags[nid_b]
            if not tags_b:
                continue
            intersection = tags_a & tags_b
            union = tags_a | tags_b
            jaccard = len(intersection) / len(union) if union else 0
            if jaccard >= 0.3:
                cluster_members.append(nid_b)
                visited.add(nid_b)
        if len(cluster_members) >= 2:
            shared = list(node_tags[cluster_members[0]])
            for m in cluster_members[1:]:
                shared = [t for t in shared if t in node_tags[m]]
            clusters.append({
                "id": f"cluster_{uuid.uuid4().hex[:6]}",
                "members": cluster_members,
                "shared_tags": shared,
                "size": len(cluster_members),
            })

    _json_out({
        "project": args.project, "depth_filter": args.depth,
        "total_nodes": len(nodes), "clusters_found": len(clusters),
        "clusters": clusters,
    })


# ── Search command ─────────────────────────────────────────────────

def cmd_search_similar(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    node = db.get_node(args.id)
    if not node:
        _json_out({"error": f"Node {args.id} not found"})
        return

    # Tag-based similarity search
    tags = db.get_tags(args.id)
    if not tags:
        _json_out({"node": args.id, "similar": [], "message": "No tags on this node"})
        return

    candidates: dict[str, int] = {}
    for k, v in tags:
        matching = db.find_nodes_by_tag(k, v)
        for mid in matching:
            if mid != args.id:
                candidates[mid] = candidates.get(mid, 0) + 1

    n = int(args.n) if args.n else 5
    ranked = sorted(candidates.items(), key=lambda x: x[1], reverse=True)[:n]

    results = []
    for nid, overlap in ranked:
        other = db.get_node(nid)
        if other:
            results.append({
                "id": nid, "title": other.title, "level": other.level,
                "tag_overlap": overlap, "status": other.status.value,
            })
    _json_out({"node": args.id, "similar": results})


# ── Edge commands ─────────────────────────────────────────────────

def cmd_edge_add(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    try:
        etype = EdgeType(args.type)
    except ValueError:
        _json_out({"error": f"Invalid edge type: {args.type}",
                   "valid": [e.value for e in EdgeType]})
        return
    strength = float(args.strength) if args.strength else 0.5
    db.add_edge(args.from_id, args.to_id, etype, strength=strength)
    _json_out({"from": args.from_id, "to": args.to_id,
               "type": etype.value, "strength": strength})


def cmd_edge_list(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    edges = db.get_edges(args.node_id)
    _json_out({"node": args.node_id, "edges": [
        {"from": e.from_id, "to": e.to_id, "type": e.edge_type.value,
         "status": e.status.value, "strength": e.strength,
         "alignment_count": e.alignment_count, "contract": e.contract}
        for e in edges
    ]})


def cmd_edge_update(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    db.update_edge(
        args.from_id, args.to_id, args.type,
        status=args.status,
        strength=float(args.strength) if args.strength else None,
        contract=args.contract,
    )
    _json_out({"from": args.from_id, "to": args.to_id, "type": args.type,
               "updated": True})


def cmd_edge_gc(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    result = db.gc_edges(args.project)
    _json_out({"project": args.project, **result})


# ── Compact command ───────────────────────────────────────────────

def cmd_compact(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    node = db.get_node(args.node_id)
    if not node:
        _json_out({"error": f"Node {args.node_id} not found"})
        return
    db.update_compacted(args.node_id, args.summary, args.constraints)
    _json_out({"node_id": args.node_id, "compacted": True})


# ── Snapshot commands ─────────────────────────────────────────────

def cmd_snapshot_save(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    data = db.snapshot(args.project)

    snap_dir = config.data_dir / args.project / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)

    existing = sorted(snap_dir.glob("snapshot_v*.json"))
    version = len(existing) + 1
    snap_path = snap_dir / f"snapshot_v{version}.json"
    snap_path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str),
                         encoding="utf-8")
    _json_out({"project": args.project, "version": version,
               "path": str(snap_path), "nodes": len(data["nodes"]),
               "edges": len(data["edges"])})


def cmd_snapshot_load(args: argparse.Namespace) -> None:
    config = load_config()
    snap_dir = config.data_dir / args.project / "snapshots"
    if args.version:
        snap_path = snap_dir / f"snapshot_v{args.version}.json"
    else:
        existing = sorted(snap_dir.glob("snapshot_v*.json"))
        if not existing:
            _json_out({"error": "No snapshots found"})
            return
        snap_path = existing[-1]

    if not snap_path.exists():
        _json_out({"error": f"Snapshot not found: {snap_path}"})
        return

    data = json.loads(snap_path.read_text(encoding="utf-8"))
    _json_out({"project": args.project, "path": str(snap_path),
               "nodes": len(data.get("nodes", [])),
               "edges": len(data.get("edges", []))})


# ── Checkpoint commands ───────────────────────────────────────────

def cmd_checkpoint_save(args: argparse.Namespace) -> None:
    config = load_config()
    cp_dir = config.data_dir / args.project / "checkpoints"
    cp_dir.mkdir(parents=True, exist_ok=True)
    cp_path = cp_dir / f"cp_{args.iteration}.json"
    cp_path.write_text(args.diff, encoding="utf-8")
    _json_out({"project": args.project, "iteration": args.iteration,
               "path": str(cp_path)})


def cmd_checkpoint_rollback(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    cp_dir = config.data_dir / args.project / "checkpoints"
    cp_path = cp_dir / f"cp_{args.iteration}.json"
    if not cp_path.exists():
        _json_out({"error": f"Checkpoint {args.iteration} not found"})
        return

    diff = json.loads(cp_path.read_text(encoding="utf-8"))

    for nid in diff.get("created_nodes", []):
        try:
            db.update_node_status(nid, NodeStatus.INVALIDATED)
        except Exception:
            pass

    for before_id, before_status in diff.get("status_before", {}).items():
        try:
            db.update_node_status(before_id, NodeStatus(before_status))
        except Exception:
            pass

    later_cps = sorted(cp_dir.glob("cp_*.json"))
    removed_cps = []
    for cp in later_cps:
        cp_num = int(cp.stem.split("_")[1])
        if cp_num >= int(args.iteration):
            cp.unlink()
            removed_cps.append(cp_num)

    _json_out({"project": args.project, "rolled_back_to": args.iteration,
               "invalidated_nodes": diff.get("created_nodes", []),
               "removed_checkpoints": removed_cps})


# ── Export command ────────────────────────────────────────────────

def cmd_export(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    project = args.project
    nodes = db.get_all_nodes(project)
    if not nodes:
        _json_out({"error": f"No nodes found for project '{project}'"})
        return

    node_map: dict[str, Node] = {n.id: n for n in nodes}
    children_map: dict[str, list[Node]] = {}
    roots: list[Node] = []

    for n in nodes:
        if n.parent_id and n.parent_id in node_map:
            children_map.setdefault(n.parent_id, []).append(n)
        else:
            roots.append(n)

    for children in children_map.values():
        children.sort(key=lambda n: n.id)

    files_dir = config.data_dir / project / "files"
    projects_dir = config.data_dir / "projects" / project

    def _find_content(node: Node) -> str:
        if node.detail_path:
            p = Path(node.detail_path)
            if p.exists():
                return p.read_text(encoding="utf-8").strip()

        candidate = files_dir / f"{node.id}_detail.md"
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()

        candidate = files_dir / f"{node.id}_summary.md"
        if candidate.exists():
            return candidate.read_text(encoding="utf-8").strip()

        if node.compacted:
            return node.compacted.strip()

        return ""

    def _format_tags(node: Node) -> str:
        tags = db.get_tags(node.id)
        if not tags:
            return ""
        grouped: dict[str, list[str]] = {}
        for k, v in tags:
            grouped.setdefault(k, []).append(v)
        parts = [f"**{k}**: {', '.join(vs)}" for k, vs in grouped.items()]
        return " | ".join(parts)

    lines: list[str] = []
    fmt = args.format if hasattr(args, "format") and args.format else "markdown"

    lines.append(f"# {project}")
    lines.append("")
    lines.append(f"> Exported from AI PM decomposition tree")
    lines.append(f"> Total nodes: {len(nodes)} | Max depth: {db.get_max_depth(project)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Include requirements doc if exists
    req_path = projects_dir / "requirements.md"
    if req_path.exists():
        req_text = req_path.read_text(encoding="utf-8").strip()
        req_lines = req_text.split("\n")
        # Use first heading as section title, skip it from body
        if req_lines and req_lines[0].startswith("# "):
            lines.append(f"## {req_lines[0].lstrip('# ').strip()}")
            req_lines = req_lines[1:]
        else:
            lines.append("## Requirements Summary")
        lines.append("")
        # Only first section (before first ---) as overview
        body = "\n".join(req_lines).strip()
        sections = body.split("\n---\n")
        lines.append(sections[0].strip() if sections else body)
        lines.append("")
        lines.append("---")
        lines.append("")

    polish = hasattr(args, "polish") and args.polish

    def _polish_section(node: Node, raw_content: str) -> str:
        """Polish one node's content via LLM. Context = parent + siblings only."""
        if not raw_content.strip():
            return raw_content

        from shared.llm import call_llm

        parent_title = node_map[node.parent_id].title if node.parent_id and node.parent_id in node_map else project
        siblings = children_map.get(node.parent_id or "", [])
        sibling_titles = [s.title for s in siblings if s.id != node.id]

        context = f"所属上级模块: {parent_title}\n"
        if sibling_titles:
            context += f"同级模块: {', '.join(sibling_titles)}\n"
        children = children_map.get(node.id, [])
        if children:
            context += f"下级模块: {', '.join(c.title for c in children)}\n"

        system = (
            "你是技术文档润色助手。对以下模块描述进行润色，要求：\n"
            "1. 保留所有事实信息，不添加、不删除内容\n"
            "2. 让表达更清晰、更专业、更有条理\n"
            "3. 如果原文已经很好，只做微调即可\n"
            "4. 输出纯 markdown，不要加代码块包裹\n"
            "5. 不要输出与润色无关的话"
        )
        prompt = f"## 上下文\n{context}\n## 当前模块: {node.title}\n\n## 原始内容\n{raw_content}"

        try:
            result = call_llm(prompt, config, depth=node.level, system_prompt=system, max_tokens=2048)
            return result.strip()
        except Exception as e:
            import logging
            logging.warning(f"Polish failed for {node.id}: {e}")
            return raw_content

    def _render_node(node: Node, heading_level: int) -> None:
        prefix = "#" * min(heading_level, 6)
        title = node.title or node.id
        lines.append(f"{prefix} {title}")
        lines.append("")

        tag_line = _format_tags(node)
        if tag_line:
            lines.append(f"> {tag_line}")
            lines.append("")

        content = _find_content(node)
        if content:
            content_lines = content.split("\n")
            if content_lines and content_lines[0].startswith("# "):
                content = "\n".join(content_lines[1:]).strip()
            if polish:
                content = _polish_section(node, content)
            lines.append(content)
            lines.append("")

        children = children_map.get(node.id, [])
        if children and not content:
            lines.append(f"*({len(children)} sub-nodes)*")
            lines.append("")

        for child in children:
            _render_node(child, heading_level + 1)

    for root in roots:
        _render_node(root, 2)

    output = "\n".join(lines)

    out_path = args.output if hasattr(args, "output") and args.output else None
    if out_path:
        Path(out_path).write_text(output, encoding="utf-8")
        _json_out({"project": project, "exported": out_path,
                   "nodes": len(nodes), "size_bytes": len(output.encode("utf-8")),
                   "polished": polish})
    else:
        print(output)


# ── Reconcile command ─────────────────────────────────────────────

def cmd_reconcile(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    project_dir = config.data_dir / args.project
    nodes_dir = project_dir / "files"

    valid_ids: set[str] = set()
    if nodes_dir.exists():
        for f in nodes_dir.iterdir():
            if f.is_file() and f.suffix == ".md":
                valid_ids.add(f.stem)

    node_rows = db.get_all_nodes(args.project)
    for n in node_rows:
        valid_ids.add(n.id)

    gc_result = db.gc_edges(args.project)
    _json_out({"project": args.project,
               "known_node_ids": len(valid_ids),
               "edge_gc": gc_result})


# ── Argument parser ────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ai-pm", description="AI PM CLI tools")
    sub = p.add_subparsers(dest="group")

    # project
    pg = sub.add_parser("project")
    psub = pg.add_subparsers(dest="cmd")
    pi = psub.add_parser("init")
    pi.add_argument("name")
    pi.add_argument("idea")
    ps = psub.add_parser("status")
    ps.add_argument("name")
    psub.add_parser("list")

    # node
    ng = sub.add_parser("node")
    nsub = ng.add_subparsers(dest="cmd")
    na = nsub.add_parser("add")
    na.add_argument("project")
    na.add_argument("title")
    na.add_argument("--parent", default=None)
    na.add_argument("--depth", default=None)
    nget = nsub.add_parser("get")
    nget.add_argument("id")
    nc = nsub.add_parser("children")
    nc.add_argument("id")
    nanc = nsub.add_parser("ancestors")
    nanc.add_argument("id")
    nus = nsub.add_parser("status")
    nus.add_argument("id")
    nus.add_argument("new_status")
    nl = nsub.add_parser("list")
    nl.add_argument("project")
    nl.add_argument("--depth", default=None)

    # tag
    tg = sub.add_parser("tag")
    tsub = tg.add_subparsers(dest="cmd")
    ts = tsub.add_parser("set")
    ts.add_argument("node_id")
    ts.add_argument("tags", nargs="+")
    tget = tsub.add_parser("get")
    tget.add_argument("node_id")
    tf = tsub.add_parser("find")
    tf.add_argument("key")
    tf.add_argument("value")

    # cluster
    cg = sub.add_parser("cluster")
    csub = cg.add_subparsers(dest="cmd")
    cr = csub.add_parser("run")
    cr.add_argument("project")
    cr.add_argument("--depth", default=None)

    # search
    sg = sub.add_parser("search")
    ssub = sg.add_subparsers(dest="cmd")
    ss = ssub.add_parser("similar")
    ss.add_argument("id")
    ss.add_argument("--n", default="5")

    # edge
    eg = sub.add_parser("edge")
    esub = eg.add_subparsers(dest="cmd")
    ea = esub.add_parser("add")
    ea.add_argument("from_id")
    ea.add_argument("to_id")
    ea.add_argument("type")
    ea.add_argument("--strength", default=None)
    el = esub.add_parser("list")
    el.add_argument("node_id")
    eu = esub.add_parser("update")
    eu.add_argument("from_id")
    eu.add_argument("to_id")
    eu.add_argument("type")
    eu.add_argument("--status", default=None)
    eu.add_argument("--strength", default=None)
    eu.add_argument("--contract", default=None)
    egc = esub.add_parser("gc")
    egc.add_argument("project")

    # compact
    cpg = sub.add_parser("compact")
    cpg.add_argument("node_id")
    cpg.add_argument("--summary", required=True)
    cpg.add_argument("--constraints", default="[]")

    # snapshot
    snp = sub.add_parser("snapshot")
    snsub = snp.add_subparsers(dest="cmd")
    sns = snsub.add_parser("save")
    sns.add_argument("project")
    snl = snsub.add_parser("load")
    snl.add_argument("project")
    snl.add_argument("--version", default=None)

    # checkpoint
    chk = sub.add_parser("checkpoint")
    chksub = chk.add_subparsers(dest="cmd")
    chs = chksub.add_parser("save")
    chs.add_argument("project")
    chs.add_argument("iteration")
    chs.add_argument("--diff", required=True)
    chr_ = chksub.add_parser("rollback")
    chr_.add_argument("project")
    chr_.add_argument("iteration")

    # reconcile
    rec = sub.add_parser("reconcile")
    rec.add_argument("project")

    # export
    exp = sub.add_parser("export")
    exp.add_argument("project")
    exp.add_argument("--output", "-o", default=None, help="Output file path (stdout if omitted)")
    exp.add_argument("--format", default="markdown", choices=["markdown"])
    exp.add_argument("--polish", action="store_true", help="Polish each section via LLM")

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        ("project", "init"): cmd_project_init,
        ("project", "status"): cmd_project_status,
        ("project", "list"): cmd_project_list,
        ("node", "add"): cmd_node_add,
        ("node", "get"): cmd_node_get,
        ("node", "children"): cmd_node_children,
        ("node", "ancestors"): cmd_node_ancestors,
        ("node", "status"): cmd_node_update_status,
        ("node", "list"): cmd_node_list,
        ("tag", "set"): cmd_tag_set,
        ("tag", "get"): cmd_tag_get,
        ("tag", "find"): cmd_tag_find,
        ("cluster", "run"): cmd_cluster_run,
        ("search", "similar"): cmd_search_similar,
        ("edge", "add"): cmd_edge_add,
        ("edge", "list"): cmd_edge_list,
        ("edge", "update"): cmd_edge_update,
        ("edge", "gc"): cmd_edge_gc,
        ("snapshot", "save"): cmd_snapshot_save,
        ("snapshot", "load"): cmd_snapshot_load,
        ("checkpoint", "save"): cmd_checkpoint_save,
        ("checkpoint", "rollback"): cmd_checkpoint_rollback,
    }

    single_dispatch = {
        "compact": cmd_compact,
        "reconcile": cmd_reconcile,
        "export": cmd_export,
    }

    if args.group in single_dispatch:
        single_dispatch[args.group](args)
        return

    key = (args.group, args.cmd) if hasattr(args, "cmd") else (args.group, None)
    fn = dispatch.get(key)
    if fn:
        fn(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
