"""AIOS Writer Agent — structured writing, reports, content generation."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from src.agents.base_agent import BaseAgent
from src.config import AIOSConfig
from src.memory.memory_manager import MemoryManager
from src.models import AgentType, TaskRecord

_FALLBACK_SYSTEM = (
    "You are a professional technical writer. Produce well-structured, "
    "clear prose. Use markdown formatting. Be thorough but concise."
)


class WriterAgent(BaseAgent):
    @property
    def agent_type(self) -> AgentType:
        return AgentType.WRITER

    @property
    def system_prompt(self) -> str:
        path = (
            Path(__file__).resolve().parents[2]
            / "configs" / "agent_prompts" / "writer_agent_v1.yaml"
        )
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return data.get("system_prompt", _FALLBACK_SYSTEM)
        return _FALLBACK_SYSTEM

    def _build_prompt(self, task: TaskRecord, context: str) -> list[dict]:
        user = f"Task: {task.spec.description}"
        if context:
            user += f"\n\nContext:\n{context}"
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user},
        ]

    def _parse_result(self, raw: str) -> dict:
        word_count = len(raw.split())
        # Extract markdown headings as section list
        import re
        sections = re.findall(r"^#{1,3}\s+(.+)$", raw, re.MULTILINE)
        return {
            "content": raw,
            "word_count": word_count,
            "sections": sections,
        }
