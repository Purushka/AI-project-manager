"""AI PM Decomposer - forward decomposition engine.

Takes a single node and decomposes it into children using the
level-appropriate prompt template. Generates hyperspace vector tags
for each child node.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from shared.config import Config, load_config
from shared.db import Database
from shared.llm import call_llm, estimate_tokens
from shared.models import HyperspaceVector, Node, NodeStatus

logger = logging.getLogger(__name__)

REFERENCES_DIR = Path(__file__).resolve().parent.parent / "references"

LEVEL_TEMPLATE_MAP = {
    0: "prompt_L0_vision.md",
    1: "prompt_L1_subsystems.md",
    2: "prompt_L2_modules.md",
    3: "prompt_L3_features.md",
    4: "prompt_L4_api.md",
    5: "prompt_L5_tech.md",
    6: "prompt_L6_design.md",
    7: "prompt_L7_skeleton.md",
    8: "prompt_L8_code.md",
    9: "prompt_L9_deploy.md",
}


def load_prompt_template(level: int) -> str:
    filename = LEVEL_TEMPLATE_MAP.get(level)
    if filename is None:
        raise ValueError(f"No template for level {level}")
    template_path = REFERENCES_DIR / filename
    if not template_path.exists():
        raise FileNotFoundError(f"Template not found: {template_path}")
    return template_path.read_text(encoding="utf-8")


def render_prompt(template: str, variables: dict[str, str]) -> str:
    result = template
    for key, value in variables.items():
        result = result.replace("{{ " + key + " }}", value)
        result = result.replace("{{" + key + "}}", value)
    return result


def parse_children_from_response(response: str) -> list[dict]:
    json_blocks = re.findall(r"```json\s*([\s\S]*?)```", response)
    if not json_blocks:
        try:
            data = json.loads(response)
            if isinstance(data, list):
                return data
            if "children" in data:
                return data["children"]
        except json.JSONDecodeError:
            pass
        return []

    for block in json_blocks:
        try:
            data = json.loads(block.strip())
            if isinstance(data, list):
                return data
            if "children" in data:
                return data["children"]
        except json.JSONDecodeError:
            continue

    return []


def extract_vector_from_child(child: dict) -> HyperspaceVector:
    vec_data = child.get("vector", child.get("hyperspace_vector", {}))
    return HyperspaceVector.from_dict(vec_data)


def decompose_node(
    node_id: str,
    project: str,
    config: Config | None = None,
) -> list[str]:
    config = config or load_config()
    db = Database(config)
    node = db.get_node(node_id)
    if node is None:
        raise ValueError(f"Node not found: {node_id}")

    child_level = node.level + 1
    if child_level > 9:
        logger.info(f"Node {node_id} is at max level, nothing to decompose")
        return []

    template = load_prompt_template(child_level)

    ancestor_chain = db.get_ancestor_chain(node_id)
    ancestor_summaries = []
    for anc in ancestor_chain:
        if anc.summary_path and Path(anc.summary_path).exists():
            ancestor_summaries.append(Path(anc.summary_path).read_text(encoding="utf-8"))
        else:
            ancestor_summaries.append(f"[{anc.title}] (level {anc.level})")

    current_detail = ""
    if node.detail_path and Path(node.detail_path).exists():
        current_detail = Path(node.detail_path).read_text(encoding="utf-8")

    global_summary_path = config.data_dir / project / "files" / "global_summary.md"
    global_summary = ""
    if global_summary_path.exists():
        global_summary = global_summary_path.read_text(encoding="utf-8")

    variables = {
        "global_summary": global_summary or "(No global summary yet)",
        "ancestor_chain": "\n---\n".join(ancestor_summaries) or "(Root node)",
        "current_task": current_detail or node.title,
        "current_level": str(child_level),
        "parent_title": node.title,
    }

    prompt = render_prompt(template, variables)
    token_est = estimate_tokens(prompt)
    logger.info(f"Decomposing {node_id} -> L{child_level}, est. {token_est} tokens")

    response = call_llm(prompt, config, level=child_level)

    children_data = parse_children_from_response(response)
    if not children_data:
        logger.warning(f"No children parsed from LLM response for {node_id}")
        return []

    project_dir = config.data_dir / project / "files"
    created_ids: list[str] = []

    for i, child_data in enumerate(children_data):
        child_id = f"{project}_L{child_level}_{uuid.uuid4().hex[:8]}"
        child_title = child_data.get("title", f"Child {i}")

        child_dir = project_dir / child_id
        child_dir.mkdir(parents=True, exist_ok=True)

        detail_content = child_data.get("detail", child_data.get("description", ""))
        detail_path = child_dir / "detail.md"
        detail_path.write_text(f"# {child_title}\n\n{detail_content}", encoding="utf-8")

        summary_content = child_data.get("summary", child_title)
        summary_path = child_dir / "summary.md"
        summary_path.write_text(summary_content, encoding="utf-8")

        vector = extract_vector_from_child(child_data)
        vector_path = child_dir / "vector.json"
        vector_path.write_text(
            json.dumps(vector.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        child_node = Node(
            id=child_id,
            project=project,
            level=child_level,
            parent_id=node_id,
            status=NodeStatus.PENDING,
            title=child_title,
            detail_path=str(detail_path),
            summary_path=str(summary_path),
            vector_path=str(vector_path),
        )
        db.insert_node(child_node)
        db.set_tags(child_id, vector.flat_tags())

        created_ids.append(child_id)

    db.update_node_status(node_id, NodeStatus.DONE)
    logger.info(f"Decomposed {node_id} into {len(created_ids)} children")
    return created_ids
