"""AIOS Research Agent — literature retrieval and synthesis."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from src.agents.base_agent import BaseAgent
from src.config import AIOSConfig
from src.logging_config import get_logger
from src.memory.memory_manager import MemoryManager
from src.models import AgentType, TaskRecord

logger = get_logger("agents.research")

_FALLBACK_SYSTEM = (
    "You are a research specialist. Thoroughly address the task. "
    "Use the provided context. Structure output with clear sections. "
    "End with a 'Key Findings' summary."
)


class ResearchAgent(BaseAgent):
    """
    Research Agent: information retrieval, paper summarisation, literature review.
    """

    def __init__(
        self,
        config: Optional[AIOSConfig] = None,
        memory: Optional[MemoryManager] = None,
    ) -> None:
        super().__init__(config, memory)
        self._system = self._load_system_prompt()

    @property
    def agent_type(self) -> AgentType:
        return AgentType.RESEARCH

    @property
    def system_prompt(self) -> str:
        return self._system

    def _load_system_prompt(self) -> str:
        path = (
            Path(__file__).resolve().parents[2]
            / "configs"
            / "agent_prompts"
            / "research_agent_v1.yaml"
        )
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return data.get("system_prompt", _FALLBACK_SYSTEM)
        return _FALLBACK_SYSTEM

    def _build_prompt(self, task: TaskRecord, context: str) -> list[dict]:
        user_parts = [f"Task: {task.spec.description}"]
        if context:
            user_parts.append(f"\nContext from memory:\n{context}")
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

    def _parse_result(self, raw: str) -> dict:
        # Extract key findings section if present
        findings = []
        if "Key Findings" in raw:
            after = raw.split("Key Findings", 1)[1]
            for line in after.strip().splitlines():
                line = line.strip("- •*1234567890. \t")
                if line:
                    findings.append(line)
        return {
            "summary": raw[:500],
            "key_findings": findings[:5],
            "full_content": raw,
        }
