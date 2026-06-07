"""AI PM Challenger - adversarial merge plan validator.

Reviews merge plans from the Comparator and challenges them
from maintainability, performance, coupling, and team perspectives.
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
from shared.models import MergePlan, MergeStrategy

logger = logging.getLogger(__name__)

CHALLENGE_PROMPT = """你是一个资深软件架构师，负责对合并方案进行对抗性审查。
你的角色是"挑刺"——找出方案中的潜在问题和风险。

## 合并方案
- 策略: {strategy}
- 受影响节点: {affected_nodes}
- 共享组件设计:
{component_design}

## 受影响节点详情
{node_details}

## 审查维度

请从以下维度严格审查：

1. **耦合度风险**：合并是否引入了跨领域的不必要耦合？共享组件的变更是否会波及太多下游？
2. **性能瓶颈**：共享组件是否可能成为性能热点或单点故障？
3. **复杂度膨胀**：合并后的组件是否试图做太多事？是否违反单一职责？
4. **团队边界**：合并是否跨越了自然的团队分工边界？
5. **变更频率不匹配**：被合并的部分是否有截然不同的变更节奏？稳定模块和频繁变更模块合在一起？
6. **抽象泄漏**：共享接口是否为了兼容所有场景而变得过于复杂？

## 输出格式（JSON）

```json
{{
  "approved": true/false,
  "verdict": "批准/否决的详细理由",
  "risks": ["识别到的风险列表"],
  "improvements": ["改进建议（如果否决）"],
  "confidence": 0.0-1.0
}}
```

记住：你的职责是找问题。宁可误报也不要漏报。只有当合并方案确实安全且有显著收益时才批准。"""


def build_node_details(affected_nodes: list[str], db: Database) -> str:
    parts: list[str] = []
    for node_id in affected_nodes[:10]:
        node = db.get_node(node_id)
        if node is None:
            continue
        summary = ""
        if node.summary_path and Path(node.summary_path).exists():
            summary = Path(node.summary_path).read_text(encoding="utf-8")
        parts.append(f"- **{node.title}** ({node_id}, L{node.level}): {summary}")
    return "\n".join(parts) or "(No node details available)"


def challenge_plan(
    plan: MergePlan,
    project: str,
    config: Config,
) -> MergePlan:
    if plan.strategy == MergeStrategy.KEEP_SEPARATE:
        plan.approved = True
        plan.challenger_verdict = "KEEP_SEPARATE: no merge to challenge"
        return plan

    db = Database(config)
    node_details = build_node_details(plan.affected_nodes, db)

    prompt = CHALLENGE_PROMPT.format(
        strategy=plan.strategy.value,
        affected_nodes=", ".join(plan.affected_nodes[:10]),
        component_design=plan.new_component_design or "(No design provided)",
        node_details=node_details,
    )

    response = call_llm(prompt, config, depth=0)

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

    plan.approved = data.get("approved", False)
    plan.challenger_verdict = data.get("verdict", "Unable to parse verdict")
    if not plan.approved:
        plan.rejection_reason = "; ".join(data.get("improvements", []))

    return plan


def challenge_all_plans(
    plans: list[MergePlan],
    project: str,
    config: Config | None = None,
) -> list[MergePlan]:
    config = config or load_config()
    results: list[MergePlan] = []

    for plan in plans:
        challenged = challenge_plan(plan, project, config)
        results.append(challenged)
        status = "APPROVED" if challenged.approved else "REJECTED"
        logger.info(f"Plan {plan.cluster_id}: {status}")

    approved_count = sum(1 for p in results if p.approved)
    logger.info(f"Challenge complete: {approved_count}/{len(results)} plans approved")
    return results
