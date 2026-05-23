"""
AIOS Planner Agent
Converts a natural language objective into a typed, dependency-ordered DAG of subtasks.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

import yaml

from src.config import AIOSConfig, get_config
from src.logging_config import get_logger
from src.models import AgentType, DAG, TaskDomain, TaskSpec

logger = get_logger("planner")


# ---------------------------------------------------------------------------
# DAG Validation
# ---------------------------------------------------------------------------

def _is_acyclic(tasks: list[TaskSpec]) -> bool:
    """
    Verify the task list forms a DAG (no cycles).
    Uses Kahn's topological sort algorithm.
    """
    task_ids = {t.id for t in tasks}
    in_degree: dict[str, int] = {t.id: 0 for t in tasks}
    adjacency: dict[str, list[str]] = {t.id: [] for t in tasks}

    for task in tasks:
        for dep in task.dependencies:
            if dep not in task_ids:
                raise ValueError(f"Task '{task.id}' has unknown dependency '{dep}'")
            adjacency[dep].append(task.id)
            in_degree[task.id] += 1

    queue = [tid for tid, deg in in_degree.items() if deg == 0]
    visited = 0
    while queue:
        node = queue.pop(0)
        visited += 1
        for neighbor in adjacency[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    return visited == len(tasks)


def _validate_dag_schema(raw: dict) -> list[TaskSpec]:
    """Parse and validate a raw dict into a list of TaskSpec objects."""
    if "tasks" not in raw:
        raise ValueError("DAG JSON must contain a 'tasks' key")
    if not isinstance(raw["tasks"], list):
        raise ValueError("'tasks' must be a list")
    if not raw["tasks"]:
        raise ValueError("'tasks' list cannot be empty")

    task_specs = []
    seen_ids: set[str] = set()
    for item in raw["tasks"]:
        if item["id"] in seen_ids:
            raise ValueError(f"Duplicate task id: {item['id']}")
        seen_ids.add(item["id"])
        # Normalize agent type
        agent_type_str = item.get("type", "research").lower()
        try:
            agent_type = AgentType(agent_type_str)
        except ValueError:
            logger.warning(f"Unknown agent type '{agent_type_str}', defaulting to 'research'")
            agent_type = AgentType.RESEARCH
        task_specs.append(
            TaskSpec(
                id=item["id"],
                type=agent_type,
                description=item["description"],
                dependencies=item.get("dependencies", []),
                estimated_cost=float(item.get("estimated_cost", 30.0)),
            )
        )
    return task_specs


# ---------------------------------------------------------------------------
# LLM Client (thin wrapper)
# ---------------------------------------------------------------------------

def _build_planner_messages(
    objective: str,
    capability_matrix: str,
    system_prompt: str,
    few_shot_examples: list[dict],
    error_feedback: Optional[str] = None,
) -> list[dict]:
    """Build the messages list for the planner LLM call."""
    messages = []

    # Build system with injected capability matrix
    sys_content = system_prompt.replace("{capability_matrix}", capability_matrix)
    messages.append({"role": "system", "content": sys_content})

    # Few-shot examples
    for ex in few_shot_examples[:2]:  # Limit to 2 examples to manage token budget
        messages.append({"role": "user", "content": f"Objective: {ex['objective']}"})
        messages.append({"role": "assistant", "content": ex["response"].strip()})

    # Actual request
    user_content = f"Objective: {objective}"
    if error_feedback:
        user_content += f"\n\nPrevious attempt failed with error: {error_feedback}\nPlease fix and try again."
    messages.append({"role": "user", "content": user_content})
    return messages


# ---------------------------------------------------------------------------
# Planner Agent
# ---------------------------------------------------------------------------

class PlannerAgent:
    """
    The Planner Agent decomposes a high-level objective into a DAG of typed subtasks.

    It uses an LLM to produce a JSON-encoded task graph, validates it for
    correctness (schema + acyclicity), and assigns estimated execution costs.
    """

    def __init__(self, config: Optional[AIOSConfig] = None) -> None:
        self.config = config or get_config()
        self._prompts = self._load_prompts()
        self._capability_matrix = self._load_capability_matrix()
        self._llm_client = self._build_llm_client()

    def _load_prompts(self) -> dict:
        prompt_path = (
            Path(__file__).resolve().parents[2]
            / "configs"
            / "agent_prompts"
            / "planner_v1.yaml"
        )
        if not prompt_path.exists():
            logger.warning(f"Planner prompt file not found: {prompt_path}")
            return {}
        with open(prompt_path) as f:
            return yaml.safe_load(f) or {}

    def _load_capability_matrix(self) -> str:
        matrix_path = (
            Path(__file__).resolve().parents[2] / "configs" / "capability_matrix.yaml"
        )
        if not matrix_path.exists():
            return "research, code, writer, analysis, collector"
        with open(matrix_path) as f:
            raw = yaml.safe_load(f) or {}
        lines = []
        for agent, info in raw.get("agents", {}).items():
            lines.append(f"- {agent}: {info['description']}")
        return "\n".join(lines)

    def _build_llm_client(self):
        """Build the OpenAI client. Falls back gracefully if key is missing."""
        try:
            from openai import AsyncOpenAI
            api_key = self.config.openai_api_key
            if not api_key:
                logger.warning("OPENAI_API_KEY not set — LLM calls will fail at runtime")
                return None
            return AsyncOpenAI(api_key=api_key, timeout=self.config.llm.request_timeout)
        except ImportError:
            logger.error("openai package not installed")
            return None

    async def _call_llm(self, messages: list[dict]) -> str:
        """Make an async LLM call and return the response text."""
        if self._llm_client is None:
            raise RuntimeError("LLM client not initialised — check OPENAI_API_KEY")
        response = await self._llm_client.chat.completions.create(
            model=self.config.llm.planner_model,
            messages=messages,
            temperature=self.config.llm.temperature,
            max_tokens=2048,
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content.strip()

    async def plan(self, objective: str, domain: TaskDomain = TaskDomain.GENERAL) -> DAG:
        """
        Decompose a natural language objective into a validated DAG.

        Args:
            objective: The high-level task objective.
            domain: Optional domain hint (RS, SD, ADS, GENERAL).

        Returns:
            A validated DAG object ready for the Scheduler.

        Raises:
            ValueError: If the DAG cannot be produced after max retries.
        """
        logger.info(f"Planning objective (domain={domain.value}): {objective[:100]}...")

        system_prompt = self._prompts.get("system_prompt", "")
        few_shot_examples = self._prompts.get("few_shot_examples", [])
        max_retries = self.config.llm.max_plan_retries
        error_feedback: Optional[str] = None

        for attempt in range(1, max_retries + 1):
            logger.debug(f"Planner attempt {attempt}/{max_retries}")
            try:
                messages = _build_planner_messages(
                    objective=objective,
                    capability_matrix=self._capability_matrix,
                    system_prompt=system_prompt,
                    few_shot_examples=few_shot_examples,
                    error_feedback=error_feedback,
                )
                raw_text = await self._call_llm(messages)
                raw_dict = json.loads(raw_text)
                tasks = _validate_dag_schema(raw_dict)
                if not _is_acyclic(tasks):
                    raise ValueError("DAG contains a cycle")
                dag = DAG(objective=objective, tasks=tasks, domain=domain)
                logger.info(
                    f"Planning succeeded: {len(tasks)} tasks, "
                    f"workflow_id={dag.workflow_id}"
                )
                return dag
            except Exception as exc:
                error_feedback = str(exc)
                logger.warning(f"Planner attempt {attempt} failed: {exc}")

        raise ValueError(
            f"Planner failed to produce a valid DAG after {max_retries} attempts. "
            f"Last error: {error_feedback}"
        )

    def plan_sync(self, objective: str, domain: TaskDomain = TaskDomain.GENERAL) -> DAG:
        """Synchronous wrapper around plan() for use outside async contexts."""
        import asyncio
        return asyncio.get_event_loop().run_until_complete(self.plan(objective, domain))
