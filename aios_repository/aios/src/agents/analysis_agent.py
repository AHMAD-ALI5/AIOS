"""AIOS Analysis Agent — data analysis, comparisons, structured evaluation."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from src.agents.base_agent import BaseAgent
from src.config import AIOSConfig
from src.memory.memory_manager import MemoryManager
from src.models import AgentType, TaskRecord

_FALLBACK_SYSTEM = (
    "You are a data analyst. Produce precise, structured analyses. "
    "Use tables for comparisons. State assumptions clearly. "
    "End with numbered actionable findings."
)


class AnalysisAgent(BaseAgent):
    @property
    def agent_type(self) -> AgentType:
        return AgentType.ANALYSIS

    @property
    def system_prompt(self) -> str:
        path = (
            Path(__file__).resolve().parents[2]
            / "configs" / "agent_prompts" / "analysis_agent_v1.yaml"
        )
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return data.get("system_prompt", _FALLBACK_SYSTEM)
        return _FALLBACK_SYSTEM

    def _build_prompt(self, task: TaskRecord, context: str) -> list[dict]:
        user = f"Task: {task.spec.description}"
        if context:
            user += f"\n\nData/Context:\n{context}"
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user},
        ]

    def _parse_result(self, raw: str) -> dict:
        # Extract markdown tables
        tables = re.findall(r"(\|.+\|[\s\S]*?\n\n)", raw)
        # Extract numbered findings
        findings = re.findall(r"^\d+\.\s+(.+)$", raw, re.MULTILINE)
        return {
            "analysis": raw,
            "findings": findings[:10],
            "tables": tables,
        }
