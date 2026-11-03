"""Typed LLM provider abstraction (OpenAI default; stub when no key)."""

from nudge.llm.provider import LLMProvider, get_llm_provider

__all__ = ["LLMProvider", "get_llm_provider"]
