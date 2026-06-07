"""AI PM Dashboard — real-time decomposition monitor.

Run:
    python dashboard/server.py [--port 8501] [--project <name>]

Opens a browser with live tree visualization of node decomposition.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from shared.config import load_config
from shared.db import Database
from shared.models import NodeStatus

app = FastAPI(title="AI PM Dashboard")

STATIC_DIR = Path(__file__).parent / "static"


def get_db() -> Database:
    return Database(load_config())


@app.get("/api/projects")
def list_projects():
    db = get_db()
    with db._connect() as conn:
        rows = conn.execute("SELECT DISTINCT project FROM nodes").fetchall()
    return [r["project"] for r in rows]


@app.get("/api/tree/{project}")
def get_tree(project: str):
    """Return the full node tree for a project."""
    db = get_db()
    nodes = db.get_all_nodes(project)
    if not nodes:
        return {"tree": None, "stats": {}}

    node_map: dict[str, dict] = {}
    for n in nodes:
        tags = db.get_tags(n.id)
        node_map[n.id] = {
            "id": n.id,
            "title": n.title,
            "depth": n.level,
            "status": n.status.value if isinstance(n.status, NodeStatus) else n.status,
            "parent_id": n.parent_id,
            "children": [],
            "tags": {k: v for k, v in tags},
            "created_at": getattr(n, "created_at", ""),
        }

    for nid, node in node_map.items():
        pid = node["parent_id"]
        if pid and pid in node_map:
            node_map[pid]["children"].append(node)

    roots = [n for n in node_map.values() if not n["parent_id"] or n["parent_id"] not in node_map]
    tree = roots[0] if len(roots) == 1 else {"id": "virtual_root", "title": project, "depth": -1, "status": "root", "children": roots, "tags": {}}

    total = len(nodes)
    by_status = {}
    by_depth = {}
    for n in nodes:
        st = n.status.value if isinstance(n.status, NodeStatus) else n.status
        by_status[st] = by_status.get(st, 0) + 1
        by_depth[n.level] = by_depth.get(n.level, 0) + 1

    leaf_count = len(db.get_leaf_nodes(project))
    max_depth = db.get_max_depth(project)

    stats = {
        "total_nodes": total,
        "leaf_nodes": leaf_count,
        "max_depth": max_depth,
        "by_status": by_status,
        "by_depth": by_depth,
    }
    return {"tree": tree, "stats": stats}


@app.get("/api/node/{node_id}")
def get_node_detail(node_id: str):
    """Return detailed info for a single node."""
    db = get_db()
    node = db.get_node(node_id)
    if not node:
        return {"error": "not found"}

    tags = db.get_tags(node_id)
    children = db.get_children(node_id)
    ancestors = db.get_ancestor_chain(node_id)

    detail_text = ""
    if node.detail_path and Path(node.detail_path).exists():
        detail_text = Path(node.detail_path).read_text(encoding="utf-8")[:5000]

    return {
        "id": node.id,
        "title": node.title,
        "depth": node.level,
        "status": node.status.value if isinstance(node.status, NodeStatus) else node.status,
        "parent_id": node.parent_id,
        "tags": {k: v for k, v in tags},
        "children": [{"id": c.id, "title": c.title, "status": c.status.value if isinstance(c.status, NodeStatus) else c.status} for c in children],
        "ancestors": [{"id": a.id, "title": a.title, "depth": a.level} for a in ancestors],
        "detail": detail_text,
        "created_at": getattr(node, "created_at", ""),
    }


@app.get("/api/edges/{project}")
def get_edges(project: str):
    """Return all edges for a project."""
    db = get_db()
    with db._connect() as conn:
        rows = conn.execute(
            """SELECT e.* FROM edges e
               JOIN nodes n ON e.from_id = n.node_id
               WHERE n.project = ?""",
            (project,),
        ).fetchall()
    return [
        {
            "from": r["from_id"],
            "to": r["to_id"],
            "type": r["edge_type"],
            "status": r["status"],
            "strength": r["strength"],
        }
        for r in rows
    ]


@app.get("/api/export/{project}")
def export_project(project: str):
    """Export project tree as a structured markdown document."""
    import subprocess
    result = subprocess.run(
        ["python", str(Path(__file__).resolve().parents[1] / "cli.py"),
         "export", project],
        capture_output=True, text=True, encoding="utf-8",
    )
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(result.stdout, media_type="text/markdown; charset=utf-8")


@app.get("/api/stream/{project}")
async def event_stream(project: str):
    """SSE endpoint — polls DB for changes and pushes updates."""
    async def generate():
        last_count = 0
        last_hash = ""
        while True:
            db = get_db()
            nodes = db.get_all_nodes(project)
            count = len(nodes)
            current_hash = f"{count}:{sum(hash(n.status) for n in nodes)}"

            if current_hash != last_hash:
                last_hash = current_hash
                stats = {
                    "total_nodes": count,
                    "leaf_nodes": len(db.get_leaf_nodes(project)),
                    "max_depth": db.get_max_depth(project),
                    "by_status": {},
                }
                for n in nodes:
                    st = n.status.value if isinstance(n.status, NodeStatus) else n.status
                    stats["by_status"][st] = stats["by_status"].get(st, 0) + 1

                if count > last_count:
                    new_nodes = nodes[last_count:]
                    for nn in new_nodes[-5:]:
                        yield f"event: node_added\ndata: {json.dumps({'id': nn.id, 'title': nn.title, 'depth': nn.level, 'parent_id': nn.parent_id}, ensure_ascii=False)}\n\n"

                yield f"event: stats\ndata: {json.dumps(stats, ensure_ascii=False)}\n\n"
                last_count = count

            await asyncio.sleep(2)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8501)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    print(f"Dashboard: http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")
