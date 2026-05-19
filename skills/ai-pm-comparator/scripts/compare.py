"""AI PM Comparator - cluster analysis and merge strategy agent.

Analyzes each cluster to determine the best merge strategy,
then designs shared component interfaces for approved merges.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from shared.config import Config, load_config
from shared.db import Database
from shared.llm import call_llm
from shared.models import Cluster, MergePlan, MergeStrategy

logger = logging.getLogger(__name__)

COMPARE_PROMPT = """你是一个软件架构专家。分析以下聚类簇中的节点，决定最佳合并策略。

## 聚类信息
- 聚类 ID: {cluster_id}
- 聚类原因: {reason}
- 共同特征: {shared_features}

## 成员节点详情
{member_details}

## 你的任务

1. 分析这些节点的共同点和差异点
2. 评估合并的可行性和收益
3. 选择最佳策略（从以下四选一）：
   - EXTRACT_SHARED: 提取共同逻辑为共享组件，各节点引用之
   - MERGE_DUPLICATES: 节点几乎完全相同，合并为一个
   - PARAMETERIZE: 核心逻辑相同但参数不同，统一接口用参数区分
   - KEEP_SEPARATE: 差异太大，不值得合并
4. 如果选择合并，设计共享组件的接口

## 输出格式（JSON）

```json
{{
  "strategy": "EXTRACT_SHARED|MERGE_DUPLICATES|PARAMETERIZE|KEEP_SEPARATE",
  "reasoning": "选择该策略的详细理由",
  "commonalities": ["共同点列表"],
  "differences": ["差异点列表"],
  "new_component_design": "共享组件的接口设计描述（如选择KEEP_SEPARATE则留空）",
  "affected_nodes": ["受影响的节点ID列表"],
  "risk_assessment": "合并风险评估"
}}
```"""


def build_member_details(cluster: Cluster, db: Database) -> str:
    parts: list[str] = []
    for node_id in cluster.members:
        node = db.get_node(node_id)
        if node is None:
            continue

        detail = ""
        if node.detail_path and Path(node.detail_path).exists():
            detail = Path(node.detail_path).read_text(encoding="utf-8")[:2000]

        summary = ""
        if node.summary_path and Path(node.summary_path).exists():
            summary = Path(node.summary_path).read_text(encoding="utf-8")

        tags = db.get_tags(node_id)
        tag_str = ", ".join(f"{k}={v}" for k, v in tags[:20])

        parts.append(
            f"### {node.title} ({node_id})\n"
            f"- Level: {node.level}\n"
            f"- Summary: {summary}\n"
            f"- Tags: {tag_str}\n"
            f"- Detail (truncated):\n{detail}\n"
        )

    return "\n".join(parts)


def parse_strategy(raw: str) -> MergeStrategy:
    raw_upper = raw.strip().upper()
    mapping = {
        "EXTRACT_SHARED": MergeStrategy.EXTRACT_SHARED,
        "MERGE_DUPLICATES": MergeStrategy.MERGE_DUPLICATES,
        "PARAMETERIZE": MergeStrategy.PARAMETERIZE,
        "KEEP_SEPARATE": MergeStrategy.KEEP_SEPARATE,
    }
    return mapping.get(raw_upper, MergeStrategy.KEEP_SEPARATE)


def analyze_cluster(
    cluster: Cluster,
    project: str,
    config: Config,
) -> MergePlan:
    db = Database(config)
    member_details = build_member_details(cluster, db)

    prompt = COMPARE_PROMPT.format(
        cluster_id=cluster.id,
        reason=cluster.reason,
        shared_features=", ".join(cluster.shared_features),
        member_details=member_details,
    )

    response = call_llm(prompt, config, level=0)

    json_match = re.search(r"```json\s*([\s\S]*?)```", response)
    if json_match:
        try:
            data = json.loads(json_match.group(1).strip())
        except json.JSONDecodeError:
            data = {}
    else:
        try:
            data = json.loads(response)
        except json.JSONDecodeError:
            data = {}

    strategy = parse_strategy(data.get("strategy", "KEEP_SEPARATE"))

    return MergePlan(
        cluster_id=cluster.id,
        strategy=strategy,
        new_component_design=data.get("new_component_design", ""),
        affected_nodes=data.get("affected_nodes", cluster.members),
        challenger_verdict="",
        approved=False,
    )


def compare_clusters(
    clusters: list[Cluster],
    project: str,
    config: Config | None = None,
) -> list[MergePlan]:
    config = config or load_config()
    plans: list[MergePlan] = []

    for cluster in clusters:
        if len(cluster.members) < 2:
            continue

        plan = analyze_cluster(cluster, project, config)
        plans.append(plan)
        logger.info(
            f"Cluster {cluster.id}: strategy={plan.strategy.value}, "
            f"affected={len(plan.affected_nodes)} nodes"
        )

    return plans
