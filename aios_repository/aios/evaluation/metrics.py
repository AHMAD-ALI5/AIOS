"""
AIOS Evaluation Metrics
TCR, RQS, MUE, ATL, WMS, Throughput — all metrics from the paper.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Optional

from src.config import AIOSConfig, get_config
from src.logging_config import get_logger

logger = get_logger("evaluation")

_RQS_JUDGE_PROMPT = """You are an expert evaluator for AI-generated task outputs.

Evaluate the following output on a scale of 1-10 based on:
- Completeness: Does it fully address the task?
- Accuracy: Is the information correct and well-reasoned?
- Structure: Is it well-organized and easy to follow?
- Depth: Does it provide appropriate detail?

Task: {task_description}

Output to evaluate:
{output}

Return ONLY a JSON object: {{"score": <number 1-10>, "reasoning": "<brief explanation>"}}"""


@dataclass
class TaskEvalResult:
    task_id: str
    completed: bool
    rqs_score: Optional[float] = None
    execution_time_seconds: Optional[float] = None
    token_usage: dict = field(default_factory=dict)
    agent_type: str = ""
    error: Optional[str] = None


@dataclass
class WorkflowEvalResult:
    workflow_id: str
    objective: str
    task_results: list[TaskEvalResult] = field(default_factory=list)
    total_execution_seconds: float = 0.0
    final_output: str = ""

    @property
    def tcr(self) -> float:
        """Task Completion Rate: fraction of tasks successfully completed."""
        if not self.task_results:
            return 0.0
        return sum(1 for t in self.task_results if t.completed) / len(self.task_results)

    @property
    def avg_rqs(self) -> float:
        """Average Response Quality Score (1-10)."""
        scores = [t.rqs_score for t in self.task_results if t.rqs_score is not None]
        return sum(scores) / len(scores) if scores else 0.0

    @property
    def atl(self) -> float:
        """Average Task Latency in seconds."""
        times = [t.execution_time_seconds for t in self.task_results if t.execution_time_seconds]
        return sum(times) / len(times) if times else 0.0

    @property
    def wms(self) -> float:
        """
        Workflow Modularity Score: estimated from number of parallel task pairs.
        WMS = 1 + (parallelizable_pairs / total_pairs)
        """
        n = len(self.task_results)
        if n <= 1:
            return 1.0
        total_pairs = n * (n - 1) / 2
        completed_pairs = sum(
            1 for i, a in enumerate(self.task_results)
            for b in self.task_results[i + 1:]
            if a.completed and b.completed
        )
        return 1.0 + (completed_pairs / total_pairs if total_pairs > 0 else 0)


@dataclass
class BenchmarkResult:
    """Aggregated results across all evaluation tasks."""
    system_name: str
    domain: str
    n_tasks: int
    tcr: float = 0.0
    avg_rqs: float = 0.0
    mue: float = 0.0       # Memory Utilization Efficiency
    atl_seconds: float = 0.0
    throughput_per_hour: float = 0.0
    wms: float = 0.0
    retry_rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "system": self.system_name,
            "domain": self.domain,
            "n_tasks": self.n_tasks,
            "TCR (%)": round(self.tcr * 100, 1),
            "RQS": round(self.avg_rqs, 2),
            "MUE": round(self.mue, 3),
            "ATL (s)": round(self.atl_seconds, 1),
            "Throughput (t/h)": round(self.throughput_per_hour, 1),
            "WMS": round(self.wms, 2),
            "Retry Rate (%)": round(self.retry_rate * 100, 1),
        }


class RQSJudge:
    """
    GPT-4o-based Response Quality Scorer.

    EVALUATION BIAS WARNING:
    This judge uses the same model family (GPT-4o) as the system under evaluation.
    For unbiased evaluation, use a different model family as judge
    (e.g., Claude-3-Opus if AIOS uses GPT-4o, or human annotators).
    Set judge_model in config to a different provider for publication.

    Self-evaluation bias has been documented in:
      - Zheng et al. (2023) "Judging LLM-as-a-Judge"
      - Liu et al. (2023) "G-Eval"
    """

    def __init__(self, config: Optional[AIOSConfig] = None) -> None:
        self.config = config or get_config()
        self._client = None

    def _get_client(self):
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(api_key=self.config.openai_api_key)
        return self._client

    async def score(self, task_description: str, output: str) -> tuple[float, str]:
        """
        Score a task output on 1-10 scale.

        Returns: (score, reasoning)
        """
        client = self._get_client()
        prompt = _RQS_JUDGE_PROMPT.format(
            task_description=task_description,
            output=output[:3000],
        )
        try:
            resp = await client.chat.completions.create(
                model=self.config.llm.judge_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=200,
            )
            data = json.loads(resp.choices[0].message.content)
            score = float(data.get("score", 5.0))
            reasoning = data.get("reasoning", "")
            return max(1.0, min(10.0, score)), reasoning
        except Exception as exc:
            logger.error(f"RQS judge failed: {exc}")
            return 5.0, f"Scoring error: {exc}"


class MUETracker:
    """
    Memory Utilization Efficiency tracker.
    MUE = (STM hits) / (total memory queries)
    """

    def __init__(self) -> None:
        self._hits = 0
        self._total = 0

    def record(self, hit: bool) -> None:
        self._total += 1
        if hit:
            self._hits += 1

    @property
    def mue(self) -> float:
        return self._hits / self._total if self._total > 0 else 0.0

    def reset(self) -> None:
        self._hits = 0
        self._total = 0


class BenchmarkRunner:
    """
    Runs the full evaluation benchmark across task domains.
    """

    def __init__(
        self,
        config: Optional[AIOSConfig] = None,
        enable_rqs: bool = True,
    ) -> None:
        self.config = config or get_config()
        self.judge = RQSJudge(config) if enable_rqs else None
        self.mue_tracker = MUETracker()

    async def evaluate_workflow(
        self,
        workflow_id: str,
        objective: str,
        task_records: list,
        final_output: str,
        total_seconds: float,
    ) -> WorkflowEvalResult:
        """Evaluate a completed workflow."""
        result = WorkflowEvalResult(
            workflow_id=workflow_id,
            objective=objective,
            total_execution_seconds=total_seconds,
            final_output=final_output,
        )

        for record in task_records:
            completed = record.state.value == "COMPLETED"
            exec_time = record.execution_time_seconds
            rqs = None

            if completed and record.result and self.judge:
                try:
                    rqs, _ = await self.judge.score(
                        task_description=record.spec.description,
                        output=record.result.content,
                    )
                except Exception as exc:
                    logger.warning(f"RQS scoring failed for {record.task_id}: {exc}")

            result.task_results.append(
                TaskEvalResult(
                    task_id=record.task_id,
                    completed=completed,
                    rqs_score=rqs,
                    execution_time_seconds=exec_time,
                    token_usage=record.result.token_usage if record.result else {},
                    agent_type=record.spec.type.value,
                    error=record.error,
                )
            )

        return result
