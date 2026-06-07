"""AI PM Core - main orchestrator.

Manages the full pipeline:
1. Adaptive requirements interview (INTERVIEWING)
2. Requirements confirmation (CONFIRMING)
3. Forward decomposition — iterative, depth-adaptive (FORWARD)
4. Backward optimization — cluster-first (BACKWARD)
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from shared.config import Config, load_config
from shared.db import Database
from shared.llm import call_llm, call_llm_with_json, estimate_tokens
from shared.models import Node, NodeStatus

logger = logging.getLogger(__name__)

INTERVIEW_DIMENSIONS = [
    {
        "id": "target_users",
        "label": "目标用户",
        "prompt": (
            "请描述这个产品的目标用户群体：\n"
            "- 主要用户画像是谁？（年龄、职业、使用场景）\n"
            "- 有哪些不同的用户角色？（比如消费者、商家、管理员）\n"
            "- 用户当前用什么替代方案？痛点是什么？"
        ),
    },
    {
        "id": "core_value",
        "label": "核心价值",
        "prompt": (
            "请澄清产品的核心价值主张：\n"
            "- 这个产品解决什么核心问题？\n"
            "- 跟竞品相比，你的差异化优势是什么？\n"
            "- 用户愿意为什么付费？（或者商业模式是什么？）"
        ),
    },
    {
        "id": "scope_boundary",
        "label": "范围边界",
        "prompt": (
            "请明确产品的范围边界：\n"
            "- MVP 阶段必须包含哪些功能？\n"
            "- 哪些功能明确不做（至少第一版不做）？\n"
            "- 有没有分期规划？（比如 P0/P1/P2 优先级）"
        ),
    },
    {
        "id": "tech_constraints",
        "label": "技术约束",
        "prompt": (
            "请说明技术方面的约束和偏好：\n"
            "- 有没有必须使用的技术栈？（比如团队只会 Java、必须用 AWS）\n"
            "- 有没有必须对接的外部系统？（支付、地图、第三方 API）\n"
            "- 对性能、并发量、数据量有什么预期？"
        ),
    },
    {
        "id": "business_context",
        "label": "业务上下文",
        "prompt": (
            "请补充业务上下文信息：\n"
            "- 团队规模和构成？（几个前端、几个后端、有没有 DevOps）\n"
            "- 期望的上线时间？\n"
            "- 有没有合规性要求？（数据隐私、支付资质、行业牌照）\n"
            "- 预算范围？（影响技术选型和第三方服务选择）"
        ),
    },
]

INTERVIEW_ANALYSIS_PROMPT = """你是一位资深产品经理。用户提供了一个产品 idea，你已经对他进行了多轮访谈。

## 原始 idea
{{ idea_text }}

## 访谈记录
{% for record in interview_records %}
### {{ record.dimension_label }}（第 {{ record.round }} 轮）
**问题**: {{ record.question }}
**回答**: {{ record.answer }}
{% endfor %}

## 任务
请基于以上信息，分析还有哪些关键信息缺失或模糊。输出 JSON：

```json
{
  "completeness_score": 0-100,
  "missing_critical": ["缺失的关键信息1", "缺失的关键信息2"],
  "ambiguous_points": ["模糊点1", "模糊点2"],
  "follow_up_questions": ["追问1", "追问2"],
  "ready_to_proceed": true/false,
  "summary": "一段话总结当前对需求的理解"
}
```"""

REQUIREMENTS_DOC_PROMPT = """你是一位资深产品经理。基于原始 idea 和多轮访谈记录，生成一份结构化的需求确认书。

## 原始 idea
{{ idea_text }}

## 访谈记录
{% for record in interview_records %}
### {{ record.dimension_label }}
**问题**: {{ record.question }}
**回答**: {{ record.answer }}
{% endfor %}

## 要求
请输出一份结构化的需求确认书，使用 Markdown 格式，包含以下章节：

1. **产品概述**：一段话描述产品定位
2. **目标用户**：用户角色列表，每个角色的核心需求
3. **核心功能范围**：MVP 必须包含的功能（按子系统分组）
4. **明确不做的事**：排除项列表
5. **技术约束与偏好**：技术栈、外部依赖、性能要求
6. **业务约束**：团队、时间、预算、合规
7. **关键风险**：已识别的风险点
8. **成功指标**：如何判断产品成功

这份文档将作为后续自适应分解的输入，所以要尽可能具体和可操作。"""


class Phase(str, Enum):
    INIT = "init"
    INTERVIEWING = "interviewing"
    CONFIRMING = "confirming"
    FORWARD = "forward"
    BACKWARD = "backward"
    DONE = "done"


class ProjectState:
    def __init__(self, project: str, config: Config):
        self.project = project
        self.config = config
        self.state_path = config.data_dir / project / "state.json"

    def load(self) -> dict:
        if self.state_path.exists():
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "phase": Phase.INIT.value,
            "decompose_iterations": 0,
            "interview": {
                "current_dimension": 0,
                "round": 1,
                "records": [],
                "analysis": None,
                "follow_up_pending": [],
            },
        }

    def save(self, state: dict) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)


def init_project(idea_text: str, project_name: str | None = None, config: Config | None = None) -> dict:
    """Initialize a project and return the first interview question."""
    config = config or load_config()
    project = project_name or f"project_{uuid.uuid4().hex[:8]}"

    project_dir = config.data_dir / project / "files"
    project_dir.mkdir(parents=True, exist_ok=True)

    idea_path = project_dir / "idea.md"
    with open(idea_path, "w", encoding="utf-8") as f:
        f.write(idea_text)

    state_mgr = ProjectState(project, config)
    state_mgr.save({
        "phase": Phase.INTERVIEWING.value,
        "decompose_iterations": 0,
        "interview": {
            "current_dimension": 0,
            "round": 1,
            "records": [],
            "analysis": None,
            "follow_up_pending": [],
        },
    })

    first_dim = INTERVIEW_DIMENSIONS[0]
    logger.info(f"Project '{project}' initialized, starting interview")
    return {
        "project": project,
        "status": "interviewing",
        "message": f"项目已创建。在开始分解之前，我需要向你确认几个关键维度的信息。\n\n## {first_dim['label']}\n\n{first_dim['prompt']}",
        "current_dimension": first_dim["id"],
        "total_dimensions": len(INTERVIEW_DIMENSIONS),
        "progress": "1/" + str(len(INTERVIEW_DIMENSIONS)),
    }


def submit_interview_answer(
    project: str,
    answer: str,
    config: Config | None = None,
) -> dict:
    """Process user's answer to an interview question and return the next question or analysis."""
    config = config or load_config()
    state_mgr = ProjectState(project, config)
    state = state_mgr.load()

    if state["phase"] != Phase.INTERVIEWING.value:
        return {"status": "error", "message": f"Project is in '{state['phase']}' phase, not interviewing"}

    interview = state["interview"]
    dim_idx = interview["current_dimension"]
    round_num = interview["round"]

    if interview["follow_up_pending"]:
        question_text = interview["follow_up_pending"].pop(0)
        dim_label = "追问"
    else:
        dim = INTERVIEW_DIMENSIONS[dim_idx]
        question_text = dim["prompt"]
        dim_label = dim["label"]

    interview["records"].append({
        "dimension_id": INTERVIEW_DIMENSIONS[min(dim_idx, len(INTERVIEW_DIMENSIONS) - 1)]["id"],
        "dimension_label": dim_label,
        "round": round_num,
        "question": question_text,
        "answer": answer,
        "timestamp": datetime.now().isoformat(),
    })

    if not interview["follow_up_pending"]:
        next_dim_idx = dim_idx + 1
    else:
        next_dim_idx = dim_idx

    if not interview["follow_up_pending"] and next_dim_idx >= len(INTERVIEW_DIMENSIONS):
        state_mgr.save(state)
        return _analyze_interview(project, config)

    if not interview["follow_up_pending"]:
        interview["current_dimension"] = next_dim_idx
        next_dim = INTERVIEW_DIMENSIONS[next_dim_idx]
        next_question = next_dim["prompt"]
        next_label = next_dim["label"]
        progress = f"{next_dim_idx + 1}/{len(INTERVIEW_DIMENSIONS)}"
    else:
        next_question = interview["follow_up_pending"][0]
        next_label = "追问"
        progress = f"追问 ({len(interview['follow_up_pending'])} 个待回答)"

    state_mgr.save(state)
    return {
        "status": "interviewing",
        "message": f"收到。下一个问题：\n\n## {next_label}\n\n{next_question}",
        "current_dimension": INTERVIEW_DIMENSIONS[min(next_dim_idx, len(INTERVIEW_DIMENSIONS) - 1)]["id"],
        "progress": progress,
    }


def _analyze_interview(project: str, config: Config) -> dict:
    """Use LLM to analyze interview completeness and decide whether to proceed."""
    state_mgr = ProjectState(project, config)
    state = state_mgr.load()
    interview = state["interview"]

    idea_text = _load_idea(project, config)

    prompt = INTERVIEW_ANALYSIS_PROMPT
    prompt = prompt.replace("{{ idea_text }}", idea_text)

    records_text = ""
    for rec in interview["records"]:
        records_text += f"\n### {rec['dimension_label']}（第 {rec['round']} 轮）\n"
        records_text += f"**问题**: {rec['question']}\n"
        records_text += f"**回答**: {rec['answer']}\n"
    prompt = prompt.replace(
        "{% for record in interview_records %}\n"
        "### {{ record.dimension_label }}（第 {{ record.round }} 轮）\n"
        "**问题**: {{ record.question }}\n"
        "**回答**: {{ record.answer }}\n"
        "{% endfor %}",
        records_text,
    )

    response = call_llm_with_json(prompt, config, depth=0)
    analysis = _extract_json(response)

    interview["analysis"] = analysis
    interview["round"] += 1

    if analysis and analysis.get("ready_to_proceed", False):
        state["phase"] = Phase.CONFIRMING.value
        state_mgr.save(state)
        return _generate_requirements_doc(project, config)

    if analysis and analysis.get("follow_up_questions"):
        interview["follow_up_pending"] = analysis["follow_up_questions"]
        interview["current_dimension"] = 0
        state_mgr.save(state)

        first_followup = interview["follow_up_pending"][0]
        return {
            "status": "interviewing",
            "message": (
                f"基础信息已收集完毕。完整度评分：{analysis.get('completeness_score', '?')}/100。\n\n"
                f"还有 {len(analysis['follow_up_questions'])} 个追问需要确认：\n\n"
                f"## 追问\n\n{first_followup}"
            ),
            "completeness": analysis.get("completeness_score", 0),
            "progress": f"追问 ({len(analysis['follow_up_questions'])} 个待回答)",
        }

    state["phase"] = Phase.CONFIRMING.value
    state_mgr.save(state)
    return _generate_requirements_doc(project, config)


def _generate_requirements_doc(project: str, config: Config) -> dict:
    """Generate a structured requirements document for user confirmation."""
    state_mgr = ProjectState(project, config)
    state = state_mgr.load()
    interview = state["interview"]

    idea_text = _load_idea(project, config)

    prompt = REQUIREMENTS_DOC_PROMPT
    prompt = prompt.replace("{{ idea_text }}", idea_text)

    records_text = ""
    for rec in interview["records"]:
        records_text += f"\n### {rec['dimension_label']}\n"
        records_text += f"**问题**: {rec['question']}\n"
        records_text += f"**回答**: {rec['answer']}\n"
    prompt = prompt.replace(
        "{% for record in interview_records %}\n"
        "### {{ record.dimension_label }}\n"
        "**问题**: {{ record.question }}\n"
        "**回答**: {{ record.answer }}\n"
        "{% endfor %}",
        records_text,
    )

    response = call_llm(prompt, config, depth=0, max_tokens=16384)

    req_path = config.data_dir / project / "files" / "requirements.md"
    with open(req_path, "w", encoding="utf-8") as f:
        f.write(response)

    state_mgr.save(state)
    return {
        "status": "confirming",
        "message": (
            "我已根据访谈内容生成了需求确认书。请仔细审阅：\n\n"
            "---\n\n"
            f"{response}\n\n"
            "---\n\n"
            "请确认以上内容是否准确：\n"
            "- 回复 **确认** 或 **yes** 开始自适应分解\n"
            "- 回复修改意见，我会更新后重新确认"
        ),
        "requirements_path": str(req_path),
    }


def confirm_requirements(
    project: str,
    user_response: str,
    config: Config | None = None,
) -> dict:
    """Handle user's confirmation or revision of the requirements doc."""
    config = config or load_config()
    state_mgr = ProjectState(project, config)
    state = state_mgr.load()

    if state["phase"] != Phase.CONFIRMING.value:
        return {"status": "error", "message": f"Project is in '{state['phase']}' phase, not confirming"}

    normalized = user_response.strip().lower()
    if normalized in ("确认", "yes", "ok", "确定", "可以", "没问题", "开始", "start", "lgtm"):
        return _start_decomposition(project, config)

    interview = state["interview"]
    interview["records"].append({
        "dimension_id": "revision",
        "dimension_label": "需求修订",
        "round": interview["round"],
        "question": "请确认需求确认书是否准确",
        "answer": user_response,
        "timestamp": datetime.now().isoformat(),
    })
    interview["round"] += 1
    state_mgr.save(state)

    return _generate_requirements_doc(project, config)


def _start_decomposition(project: str, config: Config) -> dict:
    """Transition from confirming to forward decomposition."""
    db = Database(config)
    state_mgr = ProjectState(project, config)
    state = state_mgr.load()

    root_id = f"{project}_root_{uuid.uuid4().hex[:6]}"
    root = Node(
        id=root_id,
        project=project,
        level=0,
        parent_id=None,
        status=NodeStatus.PENDING,
        title="Product Vision",
        detail_path=str(config.data_dir / project / "files" / "idea.md"),
    )
    db.insert_node(root)

    state["phase"] = Phase.FORWARD.value
    state["decompose_iterations"] = 0
    state_mgr.save(state)

    logger.info(f"Project '{project}' requirements confirmed, starting adaptive decomposition")
    return {
        "status": "forward",
        "message": (
            "需求已确认！开始自适应迭代分解。\n\n"
            f"项目根节点: {root_id}\n"
            "分解策略: 每个节点按内容复杂度自适应展开，分到可执行粒度为止\n"
            "深度不固定，各分支独立终止"
        ),
        "root_node": root_id,
    }


def get_project_status(project: str, config: Config | None = None) -> dict:
    config = config or load_config()
    db = Database(config)
    state_mgr = ProjectState(project, config)
    state = state_mgr.load()

    result: dict[str, Any] = {
        "project": project,
        "phase": state["phase"],
    }

    if state["phase"] in (Phase.INTERVIEWING.value, Phase.CONFIRMING.value):
        interview = state.get("interview", {})
        result["interview_records"] = len(interview.get("records", []))
        result["interview_round"] = interview.get("round", 1)
        if interview.get("analysis"):
            result["completeness_score"] = interview["analysis"].get("completeness_score", 0)
        return result

    result["total_nodes"] = db.count_nodes(project)
    result["max_depth"] = db.get_max_depth(project)
    result["decompose_iterations"] = state.get("decompose_iterations", 0)

    all_nodes = db.get_all_nodes(project)
    depth_counts: dict[int, dict[str, int]] = {}
    for n in all_nodes:
        d = n.level
        if d not in depth_counts:
            depth_counts[d] = {"total": 0, "done": 0, "pending": 0}
        depth_counts[d]["total"] += 1
        if n.status == NodeStatus.DONE:
            depth_counts[d]["done"] += 1
        elif n.status == NodeStatus.PENDING:
            depth_counts[d]["pending"] += 1
    result["depths"] = {f"depth_{d}": s for d, s in sorted(depth_counts.items())}

    leaf_nodes = db.get_leaf_nodes(project)
    pending_leaves = [n for n in leaf_nodes if n.status == NodeStatus.PENDING]
    result["pending_leaves"] = len(pending_leaves)
    result["total_leaves"] = len(leaf_nodes)

    return result


def run_decomposition_step(project: str, config: Config | None = None) -> dict:
    """Execute one step of the adaptive decomposition pipeline.

    Forward phase: pick pending leaf nodes at the shallowest depth,
    return them for decomposition. No fixed layer count — branches
    terminate independently when nodes reach executable granularity.

    Backward phase: cluster-first optimization after forward completes.
    """
    config = config or load_config()
    db = Database(config)
    state_mgr = ProjectState(project, config)
    state = state_mgr.load()
    phase = Phase(state["phase"])

    if phase in (Phase.INTERVIEWING, Phase.CONFIRMING):
        return {
            "status": "not_ready",
            "message": "需求访谈尚未完成，请先完成需求确认。",
            "phase": phase.value,
        }

    if phase == Phase.DONE:
        return {"status": "done", "message": "Project decomposition complete"}

    if phase == Phase.FORWARD:
        pending_leaves = [
            n for n in db.get_leaf_nodes(project)
            if n.status == NodeStatus.PENDING
        ]

        if not pending_leaves:
            state["phase"] = Phase.BACKWARD.value
            state_mgr.save(state)
            return {
                "status": "transition",
                "message": "前向分解完成，所有叶节点已到可执行粒度。进入反向优化阶段。",
                "next_phase": "backward",
                "total_nodes": db.count_nodes(project),
                "max_depth": db.get_max_depth(project),
            }

        shallowest = min(n.level for n in pending_leaves)
        batch = [n for n in pending_leaves if n.level == shallowest]

        state["decompose_iterations"] = state.get("decompose_iterations", 0) + 1
        state_mgr.save(state)

        return {
            "status": "forward",
            "message": (
                f"迭代 #{state['decompose_iterations']}: "
                f"{len(batch)} 个待分解节点 (depth={shallowest}), "
                f"共 {len(pending_leaves)} 个待处理叶节点"
            ),
            "pending_nodes": [n.id for n in batch],
            "batch_depth": shallowest,
            "total_pending_leaves": len(pending_leaves),
        }

    if phase == Phase.BACKWARD:
        state["phase"] = Phase.DONE.value
        state_mgr.save(state)
        return {
            "status": "done",
            "message": "反向优化完成。项目分解已结束。",
            "total_nodes": db.count_nodes(project),
            "max_depth": db.get_max_depth(project),
        }

    return {"status": "error", "message": f"Unknown phase: {phase}"}


def _load_idea(project: str, config: Config) -> str:
    idea_path = config.data_dir / project / "files" / "idea.md"
    if idea_path.exists():
        with open(idea_path, "r", encoding="utf-8") as f:
            return f.read()
    return ""


def _extract_json(text: str) -> dict | None:
    import re
    match = re.search(r"```json\s*\n(.*?)\n\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None
