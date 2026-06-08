"""Configuration management for ai-pm-skills.

Reads config from ~/.openclaw/workspace/ai-pm-data/config.json.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_WORKSPACE = Path.home() / ".openclaw" / "workspace" / "ai-pm-data"

DEFAULT_CONFIG: dict[str, Any] = {
    "llm_provider": "openai",
    "openai_base_url": "http://localhost:8080/v1",
    "openai_api_key": "sk-placeholder",
    "embedding_provider": "ollama",
    "default_model": "gpt-5.5",
    "model_overrides": {},
    "workspace_path": str(DEFAULT_WORKSPACE),
    "max_context_tokens": 150000,
    "context_budget": {
        "global_summary": 10000,
        "ancestor_chain": 20000,
        "shared_interfaces": 30000,
        "current_task": 60000,
    },
    "ollama_base_url": "http://localhost:11434",
    "ollama_model": "nomic-embed-text",
    "openai_embedding_model": "text-embedding-3-small",
}


@dataclass
class Config:
    llm_provider: str = "openai"
    openai_base_url: str = "http://localhost:8080/v1"
    openai_api_key: str = "sk-placeholder"
    openai_custom_headers: dict[str, str] = field(default_factory=dict)
    embedding_provider: str = "ollama"
    default_model: str = "gpt-5.5"
    model_overrides: dict[str, str] = field(default_factory=dict)
    workspace_path: str = str(DEFAULT_WORKSPACE)
    max_context_tokens: int = 150000
    context_budget: dict[str, int] = field(default_factory=lambda: {
        "global_summary": 10000,
        "ancestor_chain": 20000,
        "shared_interfaces": 30000,
        "current_task": 60000,
    })
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "nomic-embed-text"
    openai_embedding_model: str = "text-embedding-3-small"
    dashscope_base_url: str = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
    dashscope_api_key: str = ""
    dashscope_workspace: str = ""
    dashscope_embedding_model: str = "text-embedding-v3"

    @property
    def data_dir(self) -> Path:
        return Path(self.workspace_path)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "ai_pm.db"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def vector_dir(self) -> Path:
        return self.data_dir / "vector_store"

    def get_model_for_depth(self, depth: int) -> str:
        depth_key = f"depth_{depth}"
        return self.model_overrides.get(depth_key, self.default_model)


def load_config(config_path: Path | None = None) -> Config:
    if config_path is None:
        config_path = DEFAULT_WORKSPACE / "config.json"

    if not config_path.exists():
        return Config()

    with open(config_path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    merged = {**DEFAULT_CONFIG, **raw}
    return Config(
        llm_provider=merged.get("llm_provider", "openai"),
        openai_base_url=merged.get("openai_base_url", DEFAULT_CONFIG["openai_base_url"]),
        openai_api_key=merged.get("openai_api_key", DEFAULT_CONFIG["openai_api_key"]),
        openai_custom_headers=merged.get("openai_custom_headers", {}),
        embedding_provider=merged.get("embedding_provider", "ollama"),
        default_model=merged["default_model"],
        model_overrides=merged.get("model_overrides", {}),
        workspace_path=merged["workspace_path"],
        max_context_tokens=merged["max_context_tokens"],
        context_budget=merged.get("context_budget", DEFAULT_CONFIG["context_budget"]),
        ollama_base_url=merged.get("ollama_base_url", DEFAULT_CONFIG["ollama_base_url"]),
        ollama_model=merged.get("ollama_model", DEFAULT_CONFIG["ollama_model"]),
        openai_embedding_model=merged.get("openai_embedding_model", DEFAULT_CONFIG["openai_embedding_model"]),
        dashscope_base_url=merged.get("dashscope_base_url", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"),
        dashscope_api_key=merged.get("dashscope_api_key", ""),
        dashscope_workspace=merged.get("dashscope_workspace", ""),
        dashscope_embedding_model=merged.get("dashscope_embedding_model", "text-embedding-v3"),
    )


def save_default_config(config_path: Path | None = None) -> Path:
    if config_path is None:
        config_path = DEFAULT_WORKSPACE / "config.json"

    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, indent=2, ensure_ascii=False)

    return config_path
