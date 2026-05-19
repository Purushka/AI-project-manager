"""AI PM Core - main orchestrator.

Manages the full pipeline:
1. Multi-round requirements interview (INTERVIEWING)
2. Requirements confirmation (CONFIRMING)
3. Three-phase decomposition: V1 forward -> V3 clustering -> V2 backprop
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

LEVEL_NAMES = [
    "L0_vision",
    "L1_subsystems",
    "L2_modules",
    "L3_features",
    "L4_api",
    "L5_tech",
    "L6_design",
    "L7_skeleton",
    "L8_code",
    "L9_deploy",
]

MAX_LEVEL = 9

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

这份文档将作为后续十层分解的输入，所以要尽可能具体和可操作。"""


class Phase(str, Enum):
    INIT = "init"
    INTERVIEWING = "interviewing"
    CONFIRMING = "confirming"
    DECOMPOSING = "decomposing"
    CLUSTERING = "clustering"
    COMPARING = "comparing"
    CHALLENGING = "challenging"
    BACKPROP = "backprop"
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
            "current_level": 0,
            "completed_levels": [],
            "clustering_done": [],
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
    """Initialize a project and return the first interview question.

    Does NOT jump to decomposition. Returns the first question for the user.
    """
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
        "current_level": 0,
        "completed_levels": [],
        "clustering_done": [],
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

    response = call_llm_with_json(prompt, config, level=0)
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

    response = call_llm(prompt, config, level=0, max_tokens=16384)

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
            "- 回复 **确认** 或 **yes** 开始十层分解\n"
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
    """Transition from confirming to decomposition phase."""
    db = Database(config)
    state_mgr = ProjectState(project, config)
    state = state_mgr.load()

    idea_text = _load_idea(project, config)
    req_path = config.data_dir / project / "files" / "requirements.md"
    requirements_text = ""
    if req_path.exists():
        with open(req_path, "r", encoding="utf-8") as f:
            requirements_text = f.read()

    root_id = f"{project}_L0_root"
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

    state["phase"] = Phase.DECOMPOSING.value
    state["current_level"] = 0
    state_mgr.save(state)

    logger.info(f"Project '{project}' requirements confirmed, starting decomposition")
    return {
        "status": "decomposing",
        "message": (
            "需求已确认！现在开始十层递归分解。\n\n"
            f"项目根节点: {root_id}\n"
            f"分解层级: L0 (产品愿景) -> L9 (部署方案)\n"
            f"聚类检查点: L2, L4, L6, L9"
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

    result["current_level"] = state.get("current_level", 0)
    result["total_nodes"] = db.count_nodes(project)

    level_counts = {}
    for level in range(MAX_LEVEL + 1):
        nodes = db.get_nodes_by_level(project, level)
        if nodes:
            level_counts[LEVEL_NAMES[level]] = {
                "total": len(nodes),
                "done": sum(1 for n in nodes if n.status == NodeStatus.DONE),
                "pending": sum(1 for n in nodes if n.status == NodeStatus.PENDING),
            }
    result["levels"] = level_counts
    return result


def should_cluster(level: int, config: Config) -> bool:
    return level in config.clustering_checkpoints


def run_decomposition_step(project: str, config: Config | None = None) -> dict:
    """Execute one step of the decomposition pipeline."""
    config = config or load_config()
    db = Database(config)
    state_mgr = ProjectState(project, config)
    state = state_mgr.load()
    phase = Phase(state["phase"])
    current_level = state.get("current_level", 0)

    if phase in (Phase.INTERVIEWING, Phase.CONFIRMING):
        return {
            "status": "not_ready",
            "message": "需求访谈尚未完成，请先完成需求确认。",
            "phase": phase.value,
        }

    if phase == Phase.DONE:
        return {"status": "done", "message": "Project decomposition complete"}

    if phase == Phase.DECOMPOSING:
        pending = db.get_nodes_by_status(project, NodeStatus.PENDING)
        level_pending = [n for n in pending if n.level == current_level]

        if not level_pending:
            state["completed_levels"].append(current_level)

            if should_cluster(current_level, config):
                state["phase"] = Phase.CLUSTERING.value
                state_mgr.save(state)
                return {
                    "status": "transition",
                    "message": f"Level {current_level} done, entering clustering phase",
                    "next_phase": "clustering",
                }

            if current_level >= MAX_LEVEL:
                state["phase"] = Phase.DONE.value
                state_mgr.save(state)
                return {"status": "done", "message": "All levels complete"}

            state["current_level"] = current_level + 1
            state_mgr.save(state)
            return {
                "status": "advancing",
                "message": f"Advancing to level {current_level + 1}",
            }

        return {
            "status": "decomposing",
            "message": f"Level {current_level}: {len(level_pending)} nodes pending",
            "pending_nodes": [n.id for n in level_pending],
        }

    if phase == Phase.CLUSTERING:
        state["clustering_done"].append(current_level)
        state["phase"] = Phase.COMPARING.value
        state_mgr.save(state)
        return {
            "status": "transition",
            "message": f"Clustering done for level {current_level}, entering comparison",
            "next_phase": "comparing",
        }

    if phase == Phase.COMPARING:
        state["phase"] = Phase.CHALLENGING.value
        state_mgr.save(state)
        return {
            "status": "transition",
            "message": "Comparison done, entering challenge phase",
            "next_phase": "challenging",
        }

    if phase == Phase.CHALLENGING:
        state["phase"] = Phase.BACKPROP.value
        state_mgr.save(state)
        return {
            "status": "transition",
            "message": "Challenge complete, entering backpropagation",
            "next_phase": "backprop",
        }

    if phase == Phase.BACKPROP:
        if current_level >= MAX_LEVEL:
            state["phase"] = Phase.DONE.value
        else:
            state["current_level"] = current_level + 1
            state["phase"] = Phase.DECOMPOSING.value
        state_mgr.save(state)
        return {
            "status": "transition",
            "message": f"Backprop done, advancing to level {current_level + 1}",
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
