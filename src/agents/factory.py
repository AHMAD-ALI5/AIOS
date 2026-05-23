"""AIOS Agent Factory — creates agent instances by type."""

from __future__ import annotations

from typing import Optional

from src.agents.analysis_agent import AnalysisAgent
from src.agents.base_agent import BaseAgent
from src.agents.code_agent import CodeAgent
from src.agents.collector_agent import CollectorAgent
from src.agents.research_agent import ResearchAgent
from src.agents.writer_agent import WriterAgent
from src.config import AIOSConfig
from src.memory.memory_manager import MemoryManager
from src.models import AgentType

_AGENT_CLASSES = {
    AgentType.RESEARCH: ResearchAgent,
    AgentType.CODE: CodeAgent,
    AgentType.WRITER: WriterAgent,
    AgentType.ANALYSIS: AnalysisAgent,
    AgentType.COLLECTOR: CollectorAgent,
}


def create_agent(
    agent_type: AgentType,
    config: Optional[AIOSConfig] = None,
    memory: Optional[MemoryManager] = None,
) -> BaseAgent:
    """Instantiate an agent by type."""
    cls = _AGENT_CLASSES.get(agent_type)
    if cls is None:
        raise ValueError(f"Unknown agent type: {agent_type}")
    return cls(config=config, memory=memory)
