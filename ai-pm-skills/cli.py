#!/usr/bin/env python3
"""AI PM CLI - Shell interface for OpenClaw agent to call.

Usage:
    python cli.py project init <name> <idea_text>
    python cli.py project status <name>
    python cli.py project list
    python cli.py node add <project> <level> <title> [--parent <id>]
    python cli.py node get <id>
    python cli.py node children <id>
    python cli.py node ancestors <id>
    python cli.py node status <id> <new_status>
    python cli.py node list <project> [--level <n>]
    python cli.py tag set <node_id> <key=value> [key=value ...]
    python cli.py tag get <node_id>
    python cli.py tag find <key> <value>
    python cli.py cluster run <project> <level>
    python cli.py search similar <node_id> [--n <count>]
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

    root_id = f"{project}_L0_root"
    root = Node(
        id=root_id, project=project, level=0, parent_id=None,
        status=NodeStatus.PENDING, title="Product Vision",
        detail_path=str(idea_path),
    )
    db.insert_node(root)

    status_path = config.data_dir / project / "status.md"
    status_path.write_text(
        f"# {project}\n- 阶段: 访谈\n- 当前层级: L0\n- 已完成: 无\n",
        encoding="utf-8",
    )
    _json_out({"project": project, "root_node": root_id, "idea_path": str(idea_path)})


def cmd_project_status(args: argparse.Namespace) -> None:
    config = load_config()
    db = Database(config)
    project = args.name
    total = db.count_nodes(project)
    levels = {}
    for lv in range(10):
        nodes = db.get_nodes_by_level(project, lv)
        if nodes:
            levels[f"L{lv}"] = {
                "total": len(nodes),
                "done": sum(1 for n in nodes if n.status == NodeStatus.DONE),
                "pending": sum(1 for n in nodes if n.status == NodeStatus.PENDING),
            }
    _json_out({"project": project, "total_nodes": total, "levels": levels})


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
    node_id = f"{args.project}_L{args.level}_{uuid.uuid4().hex[:6]}"
    node = Node(
        id=node_id, project=args.project, level=int(args.level),
        parent_id=args.parent, status=NodeStatus.PENDING, title=args.title,
    )
    db.insert_node(node)
    _json_out({"node_id": node_id, "project": args.project, "level": args.level, "title": args.title})


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
    if args.level is not None:
        nodes = db.get_nodes_by_level(args.project, int(args.level))
    else:
        nodes = []
        for lv in range(10):
            nodes.extend(db.get_nodes_by_level(args.project, lv))
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
    level = int(args.level)
    nodes = db.get_nodes_by_level(args.project, level)

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
        "project": args.project, "level": level,
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

    node_rows = db.get_nodes_by_level(args.project, -1)
    if not node_rows:
        for lv in range(100):
            node_rows.extend(db.get_nodes_by_level(args.project, lv))
            if not db.get_nodes_by_level(args.project, lv):
                break
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
    na.add_argument("level")
    na.add_argument("title")
    na.add_argument("--parent", default=None)
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
    nl.add_argument("--level", default=None)

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
    cr.add_argument("level")

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
