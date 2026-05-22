"""AIOS Code Agent — software development, code generation, testing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from src.agents.base_agent import BaseAgent
from src.config import AIOSConfig
from src.logging_config import get_logger
from src.memory.memory_manager import MemoryManager
from src.models import AgentType, TaskRecord

logger = get_logger("agents.code")

_FALLBACK_SYSTEM = (
    "You are a senior software engineer. Write clean, well-documented, "
    "type-hinted Python code. Always wrap code in ```python ... ``` blocks."
)


class CodeAgent(BaseAgent):
    """
    Code Agent: code generation, debugging, testing, documentation.
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
        return AgentType.CODE

    @property
    def system_prompt(self) -> str:
        return self._system

    def _load_system_prompt(self) -> str:
        path = (
            Path(__file__).resolve().parents[2]
            / "configs"
            / "agent_prompts"
            / "code_agent_v1.yaml"
        )
        if path.exists():
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return data.get("system_prompt", _FALLBACK_SYSTEM)
        return _FALLBACK_SYSTEM

    def _build_prompt(self, task: TaskRecord, context: str) -> list[dict]:
        user_parts = [f"Task: {task.spec.description}"]
        if context:
            user_parts.append(f"\nContext:\n{context}")
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": "\n".join(user_parts)},
        ]

    def _parse_result(self, raw: str) -> dict:
        # Extract code blocks
        code_blocks = re.findall(r"```(?:python)?\n(.*?)```", raw, re.DOTALL)
        code = "\n\n".join(code_blocks) if code_blocks else ""
        # Extract pip dependencies mentioned
        deps = re.findall(r"pip install ([\w\-]+)", raw)
        return {
            "code": code,
            "full_content": raw,
            "code_blocks": len(code_blocks),
            "dependencies": list(set(deps)),
        }

    async def _execute_tools(self, task: TaskRecord, raw_output: str) -> str:
        """
        Code validation: check syntax of extracted Python code blocks.
        Does NOT execute code (security boundary).
        """
        import ast
        code_blocks = re.findall(r"```(?:python)?\n(.*?)```", raw_output, re.DOTALL)
        for i, block in enumerate(code_blocks):
            try:
                ast.parse(block)
                logger.debug(f"Code block {i+1}: syntax OK")
            except SyntaxError as e:
                logger.warning(f"Code block {i+1}: syntax error: {e}")
                # Append warning to output
                raw_output += f"\n\n> ⚠️ Syntax warning in block {i+1}: {e}"
        return raw_output
