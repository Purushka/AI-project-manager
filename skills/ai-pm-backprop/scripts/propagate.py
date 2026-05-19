"""AI PM Backprop - reverse propagation of merge decisions.

Takes approved merge plans and propagates their effects upward
through the decomposition tree, invalidating stale nodes and
creating shared component entries.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from shared.config import Config, load_config
from shared.db import Database
from shared.models import EdgeType, MergePlan, MergeStrategy, Node, NodeStatus

logger = logging.getLogger(__name__)


def create_shared_component(
    plan: MergePlan,
    project: str,
    db: Database,
    config: Config,
) -> str:
    comp_id = f"{project}_shared_{uuid.uuid4().hex[:8]}"
    first_member = db.get_node(plan.affected_nodes[0]) if plan.affected_nodes else None
    level = first_member.level if first_member else 0

    comp_dir = config.data_dir / project / "files" / comp_id
    comp_dir.mkdir(parents=True, exist_ok=True)

    detail_path = comp_dir / "detail.md"
    detail_path.write_text(
        f"# Shared Component\n\n"
        f"Strategy: {plan.strategy.value}\n\n"
        f"## Design\n\n{plan.new_component_design}\n\n"
        f"## Source Nodes\n\n"
        + "\n".join(f"- {nid}" for nid in plan.affected_nodes),
        encoding="utf-8",
    )

    summary_path = comp_dir / "summary.md"
    summary_path.write_text(
        f"Shared component ({plan.strategy.value}) from {len(plan.affected_nodes)} nodes",
        encoding="utf-8",
    )

    comp_node = Node(
        id=comp_id,
        project=project,
        level=level,
        parent_id=first_member.parent_id if first_member else None,
        status=NodeStatus.DONE,
        title=f"Shared: {plan.cluster_id}",
        detail_path=str(detail_path),
        summary_path=str(summary_path),
    )
    db.insert_node(comp_node)

    for nid in plan.affected_nodes:
        db.add_edge(nid, comp_id, EdgeType.SHARED_REF)

    return comp_id


def invalidate_merged_nodes(
    plan: MergePlan,
    db: Database,
) -> list[str]:
    invalidated: list[str] = []
    if plan.strategy == MergeStrategy.MERGE_DUPLICATES:
        for nid in plan.affected_nodes[1:]:
            db.update_node_status(nid, NodeStatus.INVALIDATED)
            invalidated.append(nid)
    return invalidated


def propagate_to_ancestors(
    node_id: str,
    db: Database,
    config: Config,
    project: str,
) -> list[str]:
    needs_review: list[str] = []
    ancestors = db.get_ancestor_chain(node_id)

    for ancestor in ancestors[:-1]:
        children = db.get_children(ancestor.id)
        invalidated_children = [
            c for c in children if c.status == NodeStatus.INVALIDATED
        ]

        if len(invalidated_children) > len(children) * 0.3:
            needs_review.append(ancestor.id)
            logger.info(
                f"Node {ancestor.id} needs review: "
                f"{len(invalidated_children)}/{len(children)} children invalidated"
            )

        summary_path = config.data_dir / project / "files" / ancestor.id / "summary.md"
        if summary_path.exists():
            current = summary_path.read_text(encoding="utf-8")
            updated = current + f"\n\n[Updated: merge applied to child {node_id}]"
            summary_path.write_text(updated, encoding="utf-8")

    return needs_review


def apply_merge_plans(
    plans: list[MergePlan],
    project: str,
    config: Config | None = None,
) -> dict:
    config = config or load_config()
    db = Database(config)

    approved_plans = [p for p in plans if p.approved and p.strategy != MergeStrategy.KEEP_SEPARATE]
    if not approved_plans:
        return {
            "shared_components": [],
            "invalidated_nodes": [],
            "needs_review": [],
        }

    shared_components: list[str] = []
    all_invalidated: list[str] = []
    all_needs_review: list[str] = []

    for plan in approved_plans:
        comp_id = create_shared_component(plan, project, db, config)
        shared_components.append(comp_id)

        invalidated = invalidate_merged_nodes(plan, db)
        all_invalidated.extend(invalidated)

        for nid in plan.affected_nodes:
            needs_review = propagate_to_ancestors(nid, db, config, project)
            all_needs_review.extend(needs_review)

    all_needs_review = list(set(all_needs_review))

    result_path = config.data_dir / project / "backprop_result.json"
    with open(result_path, "w", encoding="utf-8") as f:
        json.dump({
            "shared_components": shared_components,
            "invalidated_nodes": all_invalidated,
            "needs_review": all_needs_review,
        }, f, indent=2, ensure_ascii=False)

    logger.info(
        f"Backprop complete: {len(shared_components)} shared components, "
        f"{len(all_invalidated)} invalidated, {len(all_needs_review)} need review"
    )

    return {
        "shared_components": shared_components,
        "invalidated_nodes": all_invalidated,
        "needs_review": all_needs_review,
    }
