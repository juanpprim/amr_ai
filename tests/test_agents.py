"""Tests for AMR agents.

LLM calls are replaced with :class:`~pydantic_ai.models.function.FunctionModel`
per https://ai.pydantic.dev/testing/#unit-testing-with-functionmodel
Search tools are stubbed via :meth:`~pydantic_ai.agent.Agent.override` ``tools=``
so unit tests do not hit ChromaDB or DuckDuckGo.
"""

from __future__ import annotations

import pytest
from pydantic_ai import RunContext, models
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from src.agents.agents import (
    AgentDeps,
    AMROrchestrator,
    UserProfile,
    evaluate_answer,
    generate_flashcards,
    generate_quiz,
)

pytestmark = pytest.mark.anyio
models.ALLOW_MODEL_REQUESTS = True

# Matches the shape of ``_format_retrieved_context`` in ``src/agents/agents.py``.
_STUB_KB_SOURCE_ID = "amr_test_source.txt"


def search_knowledge_base(ctx: RunContext[AgentDeps], query: str) -> str:
    """Test double; name must match the tool the :class:`FunctionModel` invokes."""
    body = """AMR stands for Antimicrobial Resistance. It refers to the ability of
microorganisms like bacteria, viruses, fungi, and parasites to
resist the effects of the drugs, such as antibiotics, antivirals,
and antifungals, that were previously effective in treating infections
caused by them. This resistance means that standard treatments become
ineffective, infections persist, and the risk of spreading to others
increases."""
    return (
        f"[Source: {_STUB_KB_SOURCE_ID}, Score: 0.95]\n"
        f"(1) {body}\n\n"
        f"---\n"
        f"Sources: {_STUB_KB_SOURCE_ID}\n"
        f"Sufficient context: Yes"
    )


async def search_web(ctx: RunContext[AgentDeps], query: str) -> str:
    """Test double; name must match registered tool name ``search_web``."""
    return (
        "[Web 1] Test result\n"
        "URL: https://example.com\n"
        "Snippet: Stub web hit for tests.\n\n"
        "---\n"
        "Sources: web-search\n"
        "Sufficient context: Yes"
    )


def _kb_then_summarize(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
    """Simulate the model calling ``search_knowledge_base`` once, then answering."""
    if len(messages) == 1:
        return ModelResponse(
            parts=[ToolCallPart("search_knowledge_base", {"query": "What is AMR?"})]
        )
    msg = messages[-1].parts[0]
    assert msg.part_kind == "tool-return"
    return ModelResponse(parts=[TextPart(f"Based on sources: {msg.content}")])


def test_amr_orchestrator_uses_kb_stub():
    orchestrator = AMROrchestrator(collection=None, settings=None)
    with orchestrator._agent.override(
        # model=FunctionModel(_kb_then_summarize),
        tools=[
            generate_quiz,
            generate_flashcards,
            evaluate_answer,
            search_knowledge_base,
            search_web,
        ],
    ):
        result = orchestrator.handle_message("What is AMR?", UserProfile())

    assert _STUB_KB_SOURCE_ID in result["response"]


## Check context sharing in the flashcard / quiz / evaluation


## Test the streaming functionality


## Mock is called tools working properly
