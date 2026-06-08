"""AI PM Backprop - content-rewriting backward optimization.

Unlike the original that only created edges, this version:
1. Detects shared content between clustered nodes via LLM
2. Extracts shared components into new nodes
3. Rewrites original nodes to reference shared components (removes duplication)
4. Resolves conflicts with concrete proposals
5. Propagates constraint changes upward with content updates
6. Syncs all changes to the knowledge base

All writes go through the lock mechanism: acquire_lock → write → release_lock.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from shared.config import Config, load_config
from shared.db import Database
from shared.knowledge_base import KnowledgeBase
from shared.models import (
    Cluster, Edge, EdgeStatus, EdgeType,
    MergePlan, MergeStrategy, Node, NodeStatus,
)

logger = logging.getLogger(__name__)

CALLER_ID = "backprop"  # Module identity for lock acquisition
BACKPROP_LOCK_TTL = 600  # 10 minutes — backprop operations include LLM calls


def _read_node_content(node: Node, config: Config) -> str:
    """Read the full content of a node from its detail file."""
    if node.detail_path and Path(node.detail_path).exists():
        return Path(node.detail_path).read_text(encoding="utf-8")
    # Fallback: check standard naming
    files_dir = config.data_dir / node.project / "files"
    candidate = files_dir / f"{node.id}_detail.md"
    if candidate.exists():
        return candidate.read_text(encoding="utf-8")
    return node.compacted or node.title


def _write_node_content(node_id: str, content: str, project: str, config: Config) -> str:
    """Write content to a node's detail file. Returns the file path."""
    files_dir = config.data_dir / project / "files"
    files_dir.mkdir(parents=True, exist_ok=True)
    path = files_dir / f"{node_id}_detail.md"
    path.write_text(content, encoding="utf-8")
    return str(path)


# ── Overlap detection ─────────────────────────────────────────────

def detect_overlap(
    node_a: Node,
    node_b: Node,
    config: Config,
) -> dict[str, Any]:
    """Use LLM to detect what content is shared between two nodes.

    Returns:
        {
            "has_overlap": bool,
            "shared_content": str,  # the overlapping part
            "a_unique": str,        # content unique to node A
            "b_unique": str,        # content unique to node B
            "relationship": str,    # calls/shares/produces_consumes/etc
        }
    """
    from shared.llm import call_llm_with_json

    content_a = _read_node_content(node_a, config)
    content_b = _read_node_content(node_b, config)

    if not content_a.strip() or not content_b.strip():
        return {"has_overlap": False, "shared_content": "", "a_unique": content_a, "b_unique": content_b, "relationship": ""}

    system = (
        "你是架构分析助手。分析两个模块的描述，判断它们是否有内容重叠。\n"
        "重叠 = 两者描述了同一个功能/数据/接口/约束。\n"
        "在输出中直接使用模块的实际名称，不要用'模块A/模块B'之类的占位词。\n"
        "shared_content 应概括重叠部分的具体功能名称，不要用完整散文。\n"
        "输出 JSON，格式如下（不要代码块之外的文字）：\n"
        "```json\n"
        '{"has_overlap": true/false, "shared_content": "重叠功能的简短描述(≤80字)", '
        '"a_unique": "第一个模块独有的部分", "b_unique": "第二个模块独有的部分", '
        '"relationship": "calls/shares/produces_consumes/constrains/none"}\n'
        "```"
    )
    prompt = f"## {node_a.title}\n{content_a}\n\n## {node_b.title}\n{content_b}"

    try:
        raw = call_llm_with_json(prompt, config, depth=node_a.level, system_prompt=system, max_tokens=2048)
        # Extract JSON from response
        import re
        match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Overlap detection failed for {node_a.id} vs {node_b.id}: {e}")
        return {"has_overlap": False, "shared_content": "", "a_unique": content_a, "b_unique": content_b, "relationship": ""}


# ── Shared component extraction ───────────────────────────────────

def _name_shared_component(shared_content: str, config: Config) -> str:
    """Generate a concise, descriptive name for a shared component via LLM."""
    from shared.llm import call_llm

    system = (
        "给共享组件起一个简洁的技术名称（不超过30字）。"
        "要求：名词短语，说明这个组件是什么（如'用户留存数据计算服务'），"
        "不要用'模块A/B'之类的占位词，不要用完整句子。只输出名称，不要其他内容。"
    )
    try:
        name = call_llm(shared_content[:500], config, system_prompt=system, max_tokens=64, temperature=0.1)
        name = name.strip().strip('"').strip("'").strip()
        if len(name) > 60:
            name = name[:60]
        if name:
            return name
    except Exception as e:
        logger.warning(f"Shared component naming failed: {e}")
    # Fallback: first meaningful sentence fragment
    for line in shared_content.split("\n"):
        line = line.strip().strip("#").strip()
        if len(line) > 5:
            return line[:50]
    return shared_content[:50]


def _clean_ab_references(content: str) -> str:
    """Remove 模块A/模块B placeholder references from rewritten content."""
    import re
    content = re.sub(r"模块\s*[AB]\s*", "", content)
    content = re.sub(r"Module\s*[AB]\s*", "", content, flags=re.IGNORECASE)
    return content


def extract_shared_component(
    overlap: dict[str, Any],
    cluster: Cluster,
    project: str,
    db: Database,
    config: Config,
    kb: KnowledgeBase,
) -> str | None:
    """Create a new shared node from detected overlap.

    - Creates a new node with the shared content
    - Rewrites original nodes to remove the shared part and reference the new node
    - Syncs changes to KB
    - All writes go through locks

    Returns the new shared node ID, or None if extraction not needed.
    """
    shared_content = overlap.get("shared_content", "")
    if not shared_content.strip():
        return None

    # Create shared component node
    comp_id = f"{project}_shared_{uuid.uuid4().hex[:8]}"
    comp_title = _name_shared_component(shared_content, config)

    # Acquire lock on the new node (create operation)
    db.acquire_lock(comp_id, CALLER_ID, ttl=BACKPROP_LOCK_TTL)

    try:
        detail_path = _write_node_content(comp_id, f"# {comp_title}\n\n{shared_content}", project, config)

        comp_node = Node(
            id=comp_id,
            project=project,
            level=cluster.members[0].split("_L")[0] if "_L" in cluster.members[0] else 0,  # inherit level
            parent_id=None,
            status=NodeStatus.DONE,
            title=comp_title,
            detail_path=detail_path,
        )
        # Get level from first member
        first_member = db.get_node(cluster.members[0])
        if first_member:
            comp_node.level = first_member.level
            comp_node.parent_id = first_member.parent_id

        db.insert_node(comp_node)

        # Sync to KB
        kb.sync_node(comp_id, project, comp_title, shared_content)

        # Create edges from affected nodes to shared component
        for member_id in cluster.members:
            db.add_edge(member_id, comp_id, EdgeType.SHARED_REF)

    finally:
        db.release_lock(comp_id, CALLER_ID)

    return comp_id


def rewrite_node_content(
    node_id: str,
    new_content: str,
    shared_ref_id: str,
    db: Database,
    config: Config,
    kb: KnowledgeBase,
) -> None:
    """Rewrite a node's content after extracting shared parts.

    Acquires lock, updates detail file, bumps version, syncs KB.
    """
    node = db.get_node(node_id)
    if not node:
        return

    if not db.acquire_lock(node_id, CALLER_ID, ttl=BACKPROP_LOCK_TTL):
        holder = db.is_locked(node_id)
        logger.warning(f"Cannot rewrite {node_id}: locked by {holder}")
        return

    try:
        # Clean 模块A/B placeholder references and add shared component reference
        new_content = _clean_ab_references(new_content)
        content_with_ref = (
            f"{new_content}\n\n"
            f"> 共享组件: 参见 [{shared_ref_id}]"
        )
        detail_path = _write_node_content(node_id, content_with_ref, node.project, config)
        db.update_node_content(node_id, CALLER_ID, detail_path=detail_path)

        # Sync to KB
        kb.sync_node(node_id, node.project, node.title, content_with_ref)

    finally:
        db.release_lock(node_id, CALLER_ID)


# ── Conflict resolution ───────────────────────────────────────────

def resolve_conflict(
    node_a: Node,
    node_b: Node,
    edge: Edge,
    config: Config,
) -> dict[str, Any]:
    """When alignment_count > 4, generate a concrete resolution proposal.

    Instead of just marking 'conflict' and giving up, produces:
    - What specifically is oscillating
    - A proposed resolution (who should own what)
    - Whether to merge, split responsibility, or escalate
    """
    from shared.llm import call_llm_with_json

    content_a = _read_node_content(node_a, config)
    content_b = _read_node_content(node_b, config)

    system = (
        "两个模块反复对齐但无法收敛（已对齐>4次）。分析冲突原因并提出解决方案。\n"
        "输出 JSON：\n"
        "```json\n"
        '{"oscillation_point": "具体哪个接口/约束/数据在来回变", '
        '"root_cause": "为什么无法收敛", '
        '"resolution": "merge_into_a/merge_into_b/split/create_shared/escalate", '
        '"action": "具体操作建议", '
        '"new_content_a": "如果需要修改A的内容(可空)", '
        '"new_content_b": "如果需要修改B的内容(可空)"}\n'
        "```"
    )
    prompt = (
        f"## 模块 A: {node_a.title}\n{content_a}\n\n"
        f"## 模块 B: {node_b.title}\n{content_b}\n\n"
        f"## 边类型: {edge.edge_type.value}, 对齐次数: {edge.alignment_count}\n"
        f"## 合约: {edge.contract}"
    )

    try:
        raw = call_llm_with_json(prompt, config, depth=node_a.level, system_prompt=system, max_tokens=2048)
        import re
        match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        return json.loads(raw)
    except Exception as e:
        logger.warning(f"Conflict resolution failed: {e}")
        return {"resolution": "escalate", "action": f"LLM resolution failed: {e}"}


def apply_resolution(
    resolution: dict[str, Any],
    node_a: Node,
    node_b: Node,
    db: Database,
    config: Config,
    kb: KnowledgeBase,
) -> dict[str, Any]:
    """Apply a conflict resolution. Rewrites affected nodes."""
    action = resolution.get("resolution", "escalate")
    result = {"action": action, "modified": []}

    if action == "escalate":
        return {"action": "escalate", "reason": resolution.get("action", "Needs human decision")}

    new_a = resolution.get("new_content_a", "")
    new_b = resolution.get("new_content_b", "")

    if new_a and db.acquire_lock(node_a.id, CALLER_ID, ttl=BACKPROP_LOCK_TTL):
        try:
            path = _write_node_content(node_a.id, new_a, node_a.project, config)
            db.update_node_content(node_a.id, CALLER_ID, detail_path=path)
            kb.sync_node(node_a.id, node_a.project, node_a.title, new_a)
            result["modified"].append(node_a.id)
        finally:
            db.release_lock(node_a.id, CALLER_ID)

    if new_b and db.acquire_lock(node_b.id, CALLER_ID, ttl=BACKPROP_LOCK_TTL):
        try:
            path = _write_node_content(node_b.id, new_b, node_b.project, config)
            db.update_node_content(node_b.id, CALLER_ID, detail_path=path)
            kb.sync_node(node_b.id, node_b.project, node_b.title, new_b)
            result["modified"].append(node_b.id)
        finally:
            db.release_lock(node_b.id, CALLER_ID)

    if action == "create_shared":
        overlap = {
            "shared_content": resolution.get("action", ""),
            "a_unique": new_a,
            "b_unique": new_b,
        }
        cluster = Cluster(
            id=f"conflict_{node_a.id}_{node_b.id}",
            members=[node_a.id, node_b.id],
        )
        comp_id = extract_shared_component(overlap, cluster, node_a.project, db, config, kb)
        if comp_id:
            result["shared_component"] = comp_id

    return result


# ── Parent re-derivation with content update ──────────────────────

def rederive_parent(
    parent_id: str,
    db: Database,
    config: Config,
    kb: KnowledgeBase,
) -> None:
    """Re-derive a parent node's summary from its children's updated content.

    Acquires lock on parent, regenerates summary, syncs KB.
    """
    parent = db.get_node(parent_id)
    if not parent:
        return

    children = db.get_children(parent_id)
    if not children:
        return

    # Build summary from children
    child_summaries = []
    for child in children:
        if child.status == NodeStatus.INVALIDATED:
            continue
        content = _read_node_content(child, config)
        child_summaries.append(f"- **{child.title}**: {content[:200]}")

    if not child_summaries:
        return

    if not db.acquire_lock(parent_id, CALLER_ID, ttl=BACKPROP_LOCK_TTL):
        logger.warning(f"Cannot rederive parent {parent_id}: locked")
        return

    try:
        from shared.llm import call_llm

        system = (
            "基于子模块的内容，生成父模块的汇总描述。\n"
            "要求：1行概述 + 子模块要点列表。保留所有约束。不超过300字。"
        )
        prompt = f"## 父模块: {parent.title}\n\n## 子模块:\n" + "\n".join(child_summaries)

        summary = call_llm(prompt, config, depth=parent.level, system_prompt=system, max_tokens=1024)

        # Write summary
        files_dir = config.data_dir / parent.project / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        summary_path = files_dir / f"{parent_id}_summary.md"
        summary_path.write_text(f"# {parent.title}\n\n{summary}", encoding="utf-8")

        db.update_node_content(parent_id, CALLER_ID, summary_path=str(summary_path))
        kb.sync_node(parent_id, parent.project, parent.title, summary)

    except Exception as e:
        logger.warning(f"Parent rederivation failed for {parent_id}: {e}")
    finally:
        db.release_lock(parent_id, CALLER_ID)


# ── Main backward optimization pipeline ──────────────────────────

def run_backward_optimization(
    project: str,
    clusters: list[Cluster],
    config: Config | None = None,
) -> dict[str, Any]:
    """Full backward optimization pass.

    Pipeline:
    1. For each cluster, detect overlap between member pairs
    2. Extract shared components where overlap found
    3. Rewrite original nodes (remove duplication, add reference)
    4. Check for stale edges with alignment_count > 4 → resolve conflicts
    5. Re-derive parent summaries bottom-up
    6. Sync everything to KB
    """
    config = config or load_config()
    db = Database(config)
    kb = KnowledgeBase(config)

    # Filter out KEEP_SEPARATE clusters (no high-signal shared axes)
    from shared.models import MergeStrategy
    actionable = [c for c in clusters if c.suggested_action != MergeStrategy.KEEP_SEPARATE]
    skipped = len(clusters) - len(actionable)
    if skipped:
        logger.info(f"  Filtered {skipped} KEEP_SEPARATE clusters, {len(actionable)} actionable")
    clusters = actionable

    results = {
        "shared_components": [],
        "rewritten_nodes": [],
        "conflicts_resolved": [],
        "parents_rederived": [],
        "errors": [],
        "clusters_skipped": skipped,
    }

    BACKPROP_WORKERS = 3

    def _process_cluster(cluster: Cluster) -> dict[str, Any]:
        """Process one cluster: detect overlap, extract shared, rewrite. Thread-safe."""
        local_db = Database(config)
        local_kb = KnowledgeBase(config)
        result = {"shared": [], "rewritten": [], "errors": []}

        if len(cluster.members) < 2:
            return result

        members = [local_db.get_node(m) for m in cluster.members]
        members = [m for m in members if m and m.status != NodeStatus.INVALIDATED]

        if len(members) < 2:
            return result

        for i in range(len(members) - 1):
            try:
                overlap = detect_overlap(members[i], members[i + 1], config)

                if not overlap.get("has_overlap"):
                    continue

                comp_id = extract_shared_component(overlap, cluster, project, local_db, config, local_kb)
                if comp_id:
                    result["shared"].append(comp_id)
                    a_unique = overlap.get("a_unique", "")
                    b_unique = overlap.get("b_unique", "")
                    if a_unique:
                        rewrite_node_content(members[i].id, a_unique, comp_id, local_db, config, local_kb)
                        result["rewritten"].append(members[i].id)
                    if b_unique:
                        rewrite_node_content(members[i + 1].id, b_unique, comp_id, local_db, config, local_kb)
                        result["rewritten"].append(members[i + 1].id)

                rel = overlap.get("relationship", "")
                if rel and rel != "none":
                    try:
                        etype = EdgeType(rel)
                        local_db.add_edge(members[i].id, members[i + 1].id, etype)
                    except ValueError:
                        local_db.add_edge(members[i].id, members[i + 1].id, EdgeType.SHARES)
            except Exception as e:
                result["errors"].append(f"{cluster.id}: {e}")
                logger.warning(f"Cluster {cluster.id} pair {i} error: {e}")

        return result

    # Step 1-3: Process clusters in parallel
    logger.info(f"  Processing {len(clusters)} clusters with {BACKPROP_WORKERS} workers...")
    done_count = 0
    with ThreadPoolExecutor(max_workers=BACKPROP_WORKERS) as pool:
        futures = {pool.submit(_process_cluster, c): c for c in clusters}
        for future in as_completed(futures):
            done_count += 1
            r = future.result()
            results["shared_components"].extend(r["shared"])
            results["rewritten_nodes"].extend(r["rewritten"])
            results["errors"].extend(r["errors"])
            if done_count % 20 == 0 or done_count == len(clusters):
                logger.info(f"  Clusters: {done_count}/{len(clusters)} done, "
                            f"{len(results['shared_components'])} shared components")

    # Step 4: Resolve stale conflicts
    stale_edges = db.get_edges_by_status(project, EdgeStatus.CONFLICT)
    for edge in stale_edges:
        if edge.alignment_count <= 4:
            continue
        node_a = db.get_node(edge.from_id)
        node_b = db.get_node(edge.to_id)
        if not node_a or not node_b:
            continue

        resolution = resolve_conflict(node_a, node_b, edge, config)
        apply_result = apply_resolution(resolution, node_a, node_b, db, config, kb)

        # Mark auto-resolved edges so export can flag them for human review
        action = resolution.get("resolution", "escalate")
        if action != "escalate":
            contract_info = json.dumps({
                "auto_resolved": True,
                "resolution": action,
                "rationale": resolution.get("root_cause", ""),
                "oscillation_point": resolution.get("oscillation_point", ""),
                "alignment_count_at_resolution": edge.alignment_count,
            }, ensure_ascii=False)
            db.update_edge(
                edge.from_id, edge.to_id, edge.edge_type.value,
                status=EdgeStatus.RESOLVED.value,
                contract=contract_info,
            )

        results["conflicts_resolved"].append({
            "edge": f"{edge.from_id} -> {edge.to_id}",
            "result": apply_result,
            "auto_resolved": action != "escalate",
        })

    # Step 5: Re-derive parents bottom-up
    max_depth = db.get_max_depth(project)
    for depth in range(max_depth - 1, -1, -1):
        parents = db.get_nodes_by_level(project, depth)
        for parent in parents:
            children = db.get_children(parent.id)
            # Only rederive if any child was modified in this pass
            modified_set = set(results["rewritten_nodes"])
            if any(c.id in modified_set for c in children):
                rederive_parent(parent.id, db, config, kb)
                results["parents_rederived"].append(parent.id)

    # Step 6: Release all locks held by backprop (safety net)
    db.release_all_locks(CALLER_ID)

    # Save results
    result_path = config.data_dir / project / "backprop_result.json"
    result_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    logger.info(
        f"Backward optimization complete: "
        f"{len(results['shared_components'])} shared, "
        f"{len(results['rewritten_nodes'])} rewritten, "
        f"{len(results['conflicts_resolved'])} conflicts resolved, "
        f"{len(results['parents_rederived'])} parents rederived"
    )

    return results


# ── Legacy compatibility ──────────────────────────────────────────

def apply_merge_plans(
    plans: list[MergePlan],
    project: str,
    config: Config | None = None,
) -> dict:
    """Legacy entry point for pre-existing merge plans."""
    config = config or load_config()
    db = Database(config)
    kb = KnowledgeBase(config)

    approved_plans = [p for p in plans if p.approved and p.strategy != MergeStrategy.KEEP_SEPARATE]
    if not approved_plans:
        return {"shared_components": [], "invalidated_nodes": [], "needs_review": []}

    shared_components: list[str] = []
    all_invalidated: list[str] = []

    for plan in approved_plans:
        cluster = Cluster(id=plan.cluster_id, members=plan.affected_nodes)

        if plan.strategy == MergeStrategy.EXTRACT_SHARED:
            overlap = {
                "shared_content": plan.new_component_design,
                "a_unique": "",
                "b_unique": "",
            }
            comp_id = extract_shared_component(overlap, cluster, project, db, config, kb)
            if comp_id:
                shared_components.append(comp_id)

        elif plan.strategy == MergeStrategy.MERGE_DUPLICATES:
            for nid in plan.affected_nodes[1:]:
                if db.acquire_lock(nid, CALLER_ID):
                    try:
                        db.update_node_status(nid, NodeStatus.INVALIDATED, caller_id=CALLER_ID)
                        kb.sync_node_removed(nid)
                        all_invalidated.append(nid)
                    finally:
                        db.release_lock(nid, CALLER_ID)

    db.release_all_locks(CALLER_ID)

    return {
        "shared_components": shared_components,
        "invalidated_nodes": all_invalidated,
        "needs_review": [],
    }
