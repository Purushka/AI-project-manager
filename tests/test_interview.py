"""Tests for the interview-first flow in ai-pm-core."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.config import Config
from shared.db import Database

CORE_DIR = Path(__file__).resolve().parents[1] / "skills" / "ai-pm-core"
sys.path.insert(0, str(CORE_DIR / "scripts"))

from main import (
    INTERVIEW_DIMENSIONS,
    Phase,
    ProjectState,
    confirm_requirements,
    init_project,
    get_project_status,
    run_decomposition_step,
    submit_interview_answer,
)


@pytest.fixture
def tmp_config():
    tmp = tempfile.mkdtemp()
    return Config(workspace_path=tmp)


class TestInitProject:
    def test_returns_first_question(self, tmp_config):
        result = init_project("一个外卖平台", "test_proj", config=tmp_config)
        assert result["status"] == "interviewing"
        assert "目标用户" in result["message"]
        assert result["current_dimension"] == "target_users"
        assert result["project"] == "test_proj"

    def test_creates_idea_file(self, tmp_config):
        init_project("测试idea", "proj2", config=tmp_config)
        idea_path = Path(tmp_config.workspace_path) / "proj2" / "files" / "idea.md"
        assert idea_path.exists()
        assert idea_path.read_text(encoding="utf-8") == "测试idea"

    def test_state_is_interviewing(self, tmp_config):
        init_project("测试", "proj3", config=tmp_config)
        state_mgr = ProjectState("proj3", tmp_config)
        state = state_mgr.load()
        assert state["phase"] == Phase.INTERVIEWING.value
        assert state["interview"]["current_dimension"] == 0

    def test_does_not_create_db_node(self, tmp_config):
        init_project("测试", "proj4", config=tmp_config)
        db = Database(tmp_config)
        assert db.count_nodes("proj4") == 0


class TestInterviewFlow:
    def test_advances_through_dimensions(self, tmp_config):
        init_project("外卖平台", "proj", config=tmp_config)

        for i in range(len(INTERVIEW_DIMENSIONS) - 1):
            result = submit_interview_answer("proj", f"第{i}个回答", config=tmp_config)
            assert result["status"] == "interviewing"

    def test_records_answers(self, tmp_config):
        init_project("外卖平台", "proj", config=tmp_config)
        submit_interview_answer("proj", "目标用户是年轻人", config=tmp_config)

        state_mgr = ProjectState("proj", tmp_config)
        state = state_mgr.load()
        records = state["interview"]["records"]
        assert len(records) == 1
        assert records[0]["answer"] == "目标用户是年轻人"
        assert records[0]["dimension_label"] == "目标用户"

    def test_wrong_phase_returns_error(self, tmp_config):
        init_project("外卖平台", "proj", config=tmp_config)
        state_mgr = ProjectState("proj", tmp_config)
        state = state_mgr.load()
        state["phase"] = Phase.FORWARD.value
        state_mgr.save(state)

        result = submit_interview_answer("proj", "回答", config=tmp_config)
        assert result["status"] == "error"


class TestDecompositionBlockedDuringInterview:
    def test_decomposition_blocked_during_interview(self, tmp_config):
        init_project("外卖平台", "proj", config=tmp_config)
        result = run_decomposition_step("proj", config=tmp_config)
        assert result["status"] == "not_ready"
        assert "访谈" in result["message"]

    def test_decomposition_blocked_during_confirming(self, tmp_config):
        init_project("外卖平台", "proj", config=tmp_config)
        state_mgr = ProjectState("proj", tmp_config)
        state = state_mgr.load()
        state["phase"] = Phase.CONFIRMING.value
        state_mgr.save(state)

        result = run_decomposition_step("proj", config=tmp_config)
        assert result["status"] == "not_ready"


class TestConfirmRequirements:
    def test_wrong_phase_returns_error(self, tmp_config):
        init_project("外卖平台", "proj", config=tmp_config)
        result = confirm_requirements("proj", "确认", config=tmp_config)
        assert result["status"] == "error"

    def test_confirmation_starts_decomposition(self, tmp_config):
        init_project("外卖平台", "proj", config=tmp_config)
        state_mgr = ProjectState("proj", tmp_config)
        state = state_mgr.load()
        state["phase"] = Phase.CONFIRMING.value
        state_mgr.save(state)

        result = confirm_requirements("proj", "确认", config=tmp_config)
        assert result["status"] == "forward"

        db = Database(tmp_config)
        assert db.count_nodes("proj") == 1

    def test_various_confirmation_words(self, tmp_config):
        for word in ["yes", "ok", "确定", "可以", "没问题", "开始", "lgtm"]:
            proj_name = f"proj_{word}"
            init_project("外卖平台", proj_name, config=tmp_config)
            state_mgr = ProjectState(proj_name, tmp_config)
            state = state_mgr.load()
            state["phase"] = Phase.CONFIRMING.value
            state_mgr.save(state)

            result = confirm_requirements(proj_name, word, config=tmp_config)
            assert result["status"] == "forward", f"Failed for word: {word}"


class TestProjectStatus:
    def test_status_during_interview(self, tmp_config):
        init_project("外卖平台", "proj", config=tmp_config)
        submit_interview_answer("proj", "年轻人", config=tmp_config)

        status = get_project_status("proj", config=tmp_config)
        assert status["phase"] == Phase.INTERVIEWING.value
        assert status["interview_records"] == 1
        assert status["interview_round"] == 1
