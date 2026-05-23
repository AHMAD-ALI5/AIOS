"""
AIOS Web Search Tool (STUB)
Extension point for ResearchAgent live retrieval.

TODO: Implement using one of:
  - Tavily API: https://tavily.com
  - Bing Search API
  - arXiv API for academic tasks

Interface contract:
    async def search(query: str, max_results: int = 5) -> list[dict]:
        Returns list of {"title": str, "url": str, "snippet": str}
"""

from __future__ import annotations


async def search(query: str, max_results: int = 5) -> list[dict]:
    """
    Web search stub. Replace with real implementation.
    Currently returns empty list — ResearchAgent falls back to LLM-only mode.
    """
    raise NotImplementedError(
        "Web search tool not implemented. "
        "See src/agents/tools/web_search.py for integration instructions."
    )
