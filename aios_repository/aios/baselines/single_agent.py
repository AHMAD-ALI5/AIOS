"""
AIOS Baseline: Single Agent
One LLM call per objective, no decomposition, no memory, no retry.
"""

from __future__ import annotations

import asyncio
import time
from typing import Optional

from openai import AsyncOpenAI

_SYSTEM = (
    "You are an expert AI assistant. Address the following objective thoroughly "
    "and completely. Structure your response clearly."
)


class SingleAgentBaseline:
    """
    Single-call LLM baseline.
    Equivalent to a naive chatbot with no multi-agent orchestration.
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-2024-05-13", temperature: float = 0.0):
        self.model = model
        self.temperature = temperature
        self.client = AsyncOpenAI(api_key=api_key)

    async def execute(self, objective: str, timeout_seconds: int = 120) -> dict:
        """Single LLM call. Returns result dict compatible with AIOS eval format."""
        t0 = time.time()
        try:
            resp = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": objective},
                    ],
                    temperature=self.temperature,
                    max_tokens=4096,
                ),
                timeout=timeout_seconds,
            )
            content = resp.choices[0].message.content.strip()
            completed = True
        except Exception as exc:
            content = f"[ERROR: {exc}]"
            completed = False

        elapsed = time.time() - t0
        return {
            "objective": objective,
            "completed": completed,
            "output": content,
            "execution_time_seconds": elapsed,
            "token_usage": {
                "total_tokens": resp.usage.total_tokens if completed else 0
            } if completed else {},
            "n_tasks": 1,   # Single-agent = 1 "task"
        }
