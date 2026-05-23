"""AIOS Collector Agent — aggregates results from all execution agents."""

from __future__ import annotations

from typing import Optional

from src.agents.base_agent import BaseAgent
from src.config import AIOSConfig
from src.logging_config import get_logger
from src.memory.memory_manager import MemoryManager
from src.models import AgentType, TaskRecord, TaskResult

logger = get_logger("agents.collector")

_SYSTEM = """You are the Collector Agent in AIOS.
Your job is to synthesize all subtask outputs into a single coherent final response.

Instructions:
1. Read all provided subtask results carefully
2. Synthesize them into a unified, well-structured output
3. Remove redundancy but preserve all important information
4. Use clear sections with markdown headings
5. Provide a concise Executive Summary at the top
6. Ensure the output directly answers the original objective
"""


class CollectorAgent(BaseAgent):
    """
    Collector Agent: aggregates results from completed subtasks into final output.
    """

    @property
    def agent_type(self) -> AgentType:
        return AgentType.COLLECTOR

    @property
    def system_prompt(self) -> str:
        return _SYSTEM

    def _build_prompt(self, task: TaskRecord, context: str) -> list[dict]:
        user = f"Original Objective: {task.spec.description}"
        if context:
            user += f"\n\nSubtask Results to Synthesize:\n{context}"
        return [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user},
        ]

    def _parse_result(self, raw: str) -> dict:
        import re
        sections = re.findall(r"^#{1,3}\s+(.+)$", raw, re.MULTILINE)
        return {"final_output": raw, "sections": sections}

    async def aggregate(
        self,
        objective: str,
        task_results: list[TaskResult],
        workflow_id: str,
    ) -> str:
        """
        Aggregate multiple task results into a single final output.
        Creates a synthetic TaskRecord to feed through the standard pipeline.
        """
        # Build context from all task results
        result_parts = []
        for r in task_results:
            result_parts.append(
                f"=== [{r.agent_type.value.upper()}] Task {r.task_id} ===\n{r.content}"
            )
        combined_context = "\n\n".join(result_parts)

        # Build synthetic task record
        from src.models import TaskSpec, TaskState
        import uuid as _uuid
        synthetic_task = TaskRecord(
            spec=TaskSpec(
                id=f"collector_{_uuid.uuid4().hex[:6]}",
                type=AgentType.COLLECTOR,
                description=objective,
                dependencies=[],
            ),
            workflow_id=workflow_id,
            state=TaskState.RUNNING,
        )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {
                "role": "user",
                "content": f"Original Objective: {objective}\n\n"
                           f"Subtask Results:\n{combined_context[:12000]}",
            },
        ]

        try:
            raw_output, _ = await self._invoke_llm(messages)
            return raw_output
        except Exception as exc:
            logger.error(f"Collector LLM call failed: {exc}")
            # Fallback: simple concatenation
            return f"# Results Summary\n\n**Objective:** {objective}\n\n" + combined_context[:4000]
