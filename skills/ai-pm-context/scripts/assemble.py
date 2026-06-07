"""AI PM Context - context assembly engine.

Builds LLM call context with three-tier priority:
- Tier 1 (mandatory): project summary + current node + parent compacted
- Tier 2 (important): related node interfaces + edge contracts
- Tier 3 (auxiliary): sibling titles + ancestor interfaces

Token budgets are configured via config.json context_budget dict.
Quality floor: if Tier 1 cannot fit, stop rather than degrade.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from shared.config import Config, load_config
from shared.db import Database
from shared.llm import estimate_tokens

logger = logging.getLogger(__name__)


@dataclass
class AssembledContext:
    global_summary: str = ""
    ancestor_chain: str = ""
    shared_interfaces: str = ""
    current_task: str = ""
    token_usage: dict[str, int] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return sum(self.token_usage.values())

    def to_dict(self) -> dict[str, str]:
        return {
            "global_summary": self.global_summary,
            "ancestor_chain": self.ancestor_chain,
            "shared_interfaces": self.shared_interfaces,
            "current_task": self.current_task,
        }


def truncate_to_budget(text: str, max_tokens: int) -> str:
    current = estimate_tokens(text)
    if current <= max_tokens:
        return text

    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text

    head_size = int(max_chars * 0.7)
    tail_size = int(max_chars * 0.25)
    return (
        text[:head_size]
        + "\n\n... [truncated] ...\n\n"
        + text[-tail_size:]
    )


def read_file_safe(path: str | Path) -> str:
    p = Path(path)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def assemble_global_summary(project: str, config: Config) -> str:
    path = config.data_dir / project / "files" / "global_summary.md"
    content = read_file_safe(path)
    if not content:
        idea_path = config.data_dir / project / "files" / "idea.md"
        content = read_file_safe(idea_path)
    return content


def assemble_ancestor_chain(node_id: str, db: Database) -> str:
    ancestors = db.get_ancestor_chain(node_id)
    parts: list[str] = []
    for anc in ancestors:
        summary = ""
        if anc.summary_path:
            summary = read_file_safe(anc.summary_path)
        if not summary:
            summary = anc.title
        parts.append(f"## L{anc.level}: {anc.title}\n\n{summary}")
    return "\n\n---\n\n".join(parts)


def assemble_shared_interfaces(node_id: str, db: Database, config: Config, project: str) -> str:
    node = db.get_node(node_id)
    if node is None:
        return ""

    shared_ids = node.shared_component_ids
    dep_ids = node.dependency_ids

    all_ref_ids = list(set(shared_ids + dep_ids))
    if not all_ref_ids:
        return ""

    parts: list[str] = []
    for ref_id in all_ref_ids[:10]:
        ref_node = db.get_node(ref_id)
        if ref_node is None:
            continue
        summary = ""
        if ref_node.summary_path:
            summary = read_file_safe(ref_node.summary_path)
        parts.append(f"### {ref_node.title} ({ref_id})\n\n{summary}")

    return "\n\n".join(parts)


def assemble_current_task(node_id: str, db: Database) -> str:
    node = db.get_node(node_id)
    if node is None:
        return ""
    if node.detail_path:
        content = read_file_safe(node.detail_path)
        if content:
            return content
    return node.title


def assemble_context(
    node_id: str,
    project: str,
    purpose: str = "decompose",
    config: Config | None = None,
) -> AssembledContext:
    config = config or load_config()
    db = Database(config)
    budget = config.context_budget

    ctx = AssembledContext()

    raw_global = assemble_global_summary(project, config)
    ctx.global_summary = truncate_to_budget(raw_global, budget["global_summary"])
    ctx.token_usage["global_summary"] = estimate_tokens(ctx.global_summary)

    raw_ancestors = assemble_ancestor_chain(node_id, db)
    ctx.ancestor_chain = truncate_to_budget(raw_ancestors, budget["ancestor_chain"])
    ctx.token_usage["ancestor_chain"] = estimate_tokens(ctx.ancestor_chain)

    raw_shared = assemble_shared_interfaces(node_id, db, config, project)
    ctx.shared_interfaces = truncate_to_budget(raw_shared, budget["shared_interfaces"])
    ctx.token_usage["shared_interfaces"] = estimate_tokens(ctx.shared_interfaces)

    raw_task = assemble_current_task(node_id, db)
    ctx.current_task = truncate_to_budget(raw_task, budget["current_task"])
    ctx.token_usage["current_task"] = estimate_tokens(ctx.current_task)

    logger.info(
        f"Context assembled for {node_id} ({purpose}): "
        f"{ctx.total_tokens} tokens total "
        f"(global={ctx.token_usage['global_summary']}, "
        f"ancestors={ctx.token_usage['ancestor_chain']}, "
        f"shared={ctx.token_usage['shared_interfaces']}, "
        f"task={ctx.token_usage['current_task']})"
    )

    return ctx
