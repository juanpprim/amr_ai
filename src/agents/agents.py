"""
agents.py — Single Agent + Streaming + Conversation Memory (v3)

Changes from v2:
  - Streaming: Q&A responses stream token-by-token via run_stream_sync()
  - Clean tool output: tools write to deps.tool_output instead of embedding
    data markers in text — streamed text stays clean
  - StreamResult container captures history + panel data after stream ends
"""

from __future__ import annotations

import logging
import inspect
from dataclasses import dataclass, field
from queue import Queue
from threading import Thread
from typing import Callable, Generator, Literal

import logfire
import chromadb
from exa_py import Exa
from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage
from pydantic_ai.common_tools.duckduckgo import duckduckgo_search_tool

from src.agents.models import (
    AnswerEvaluation,
    FlashcardDeck,
    QuizSet,
    UserProfile,
)
from src.config import Settings
from src.models import RetrievedContext
from src.rag.retriever import retrieve


settings = Settings()
logger = logging.getLogger(__name__)
logfire_token = settings.logfire_api_key.strip() or None
logfire.configure(token=logfire_token)
logfire.instrument_pydantic_ai()

# ─────────────────────────────────────────────
# Dependencies — tools write structured output here
# ─────────────────────────────────────────────

@dataclass
class ToolOutput:
    """Populated by tools during execution. Checked after the run."""
    panel_type: str | None = None   # "quiz" | "flashcards" | "evaluation"
    data: object | None = None      # QuizSet | FlashcardDeck | AnswerEvaluation


@dataclass
class ToolEvent:
    """Simple tool lifecycle event for UI status messages."""
    tool_name: str
    status: str  # "start" | "complete"
    message: str


@dataclass
class StreamChunk:
    """Single stream item sent to the UI."""
    kind: Literal["text", "tool_event"]
    text: str = ""
    tool_event: ToolEvent | None = None


@dataclass
class AgentDeps:
    """Injected into the agent at runtime."""
    user_profile: UserProfile
    tool_output: ToolOutput = field(default_factory=ToolOutput)
    tool_events: list[ToolEvent] = field(default_factory=list)
    stream_event_sink: Callable[[ToolEvent], None] | None = None
    collection: chromadb.Collection | None = None
    settings: Settings | None = None


# ─────────────────────────────────────────────
# Stream result container
# ─────────────────────────────────────────────

class StreamResult:
    """
    Populated AFTER the stream generator is fully consumed.
    Pass alongside the generator to app.py so it can read
    panel data and history after st.write_stream() finishes.
    """
    def __init__(self):
        self.message_history: list[ModelMessage] = []
        self.panel: str | None = None
        self.data: object | None = None
        self.full_text: str = ""
        self.tool_events: list[ToolEvent] = []


def _tool_display_name(tool_name: str) -> str:
    """Map internal tool function names to user-facing labels."""
    labels = {
        "generate_quiz": "quiz",
        "generate_flashcards": "flashcards",
        "evaluate_answer": "answer evaluation",
        "search_knowledge_base": "knowledge base search",
        "search_web": "web search",
    }
    return labels.get(tool_name, tool_name.replace("_", " "))


_TOOL_STATUS_MESSAGES: dict[str, dict[str, str]] = {
    "generate_quiz": {
        "start": "Building your quiz...",
        "complete": "Quiz ready. Let's test your knowledge!",
    },
    "generate_flashcards": {
        "start": "Creating your flashcards...",
        "complete": "Flashcards ready for review.",
    },
    "evaluate_answer": {
        "start": "Reviewing your answer...",
        "complete": "Evaluation complete. Feedback is ready.",
    },
    "search_knowledge_base": {
        "start": "Searching knowledge base...",
        "complete": "Found relevant context.",
    },
    "search_web": {
        "start": "Searching the web...",
        "complete": "Web results ready.",
    },
}


def _tool_status_message(tool_name: str, status: str) -> str:
    """Return custom wording for tool lifecycle messages."""
    custom = _TOOL_STATUS_MESSAGES.get(tool_name, {}).get(status)
    if custom:
        return custom

    display_name = _tool_display_name(tool_name)
    if status == "start":
        return f"Using {display_name} tool..."
    return f"{display_name.capitalize()} complete."


def format_agent_activity_steps(
    tool_events: list[ToolEvent],
    *,
    panel_type: str | None = None,
) -> tuple[list[str], bool]:
    """
    Build markdown lines for the Agent activity expander.

    Returns (lines, expand_by_default). When tools ran, expand defaults to True
    so the log is visible without an extra click.
    """
    if not tool_events:
        if panel_type:
            label = {
                "quiz": "Quiz panel",
                "flashcards": "Flashcards panel",
                "evaluation": "Evaluation panel",
            }.get(panel_type, "Side panel")
            return ([f"✅ **Done** — {label} is ready."], False)
        return (["✅ **Response** — Answered directly (no tools)."], False)

    lines: list[str] = []
    for ev in tool_events:
        icon = "▶️" if ev.status == "start" else "✅"
        label = _tool_display_name(ev.tool_name).replace("_", " ").title()
        lines.append(f"{icon} **{label}** — {ev.message}")
    return (lines, True)


def _record_tool_start(ctx: RunContext[AgentDeps], tool_name: str) -> None:
    """Record a user-facing tool start event."""
    event = ToolEvent(
        tool_name=tool_name,
        status="start",
        message=_tool_status_message(tool_name, "start"),
    )
    ctx.deps.tool_events.append(event)
    if ctx.deps.stream_event_sink:
        ctx.deps.stream_event_sink(event)


def _record_tool_complete(ctx: RunContext[AgentDeps], tool_name: str) -> None:
    """Record a user-facing tool completion event."""
    event = ToolEvent(
        tool_name=tool_name,
        status="complete",
        message=_tool_status_message(tool_name, "complete"),
    )
    ctx.deps.tool_events.append(event)
    if ctx.deps.stream_event_sink:
        ctx.deps.stream_event_sink(event)


# ─────────────────────────────────────────────
# AMR agent system prompt + tools (registered on Agent via tools=[...])
# ─────────────────────────────────────────────

_AMR_SYSTEM_INSTRUCTIONS = """
You are an expert Antimicrobial Resistance (AMR) learning assistant.

You can do six things:
1. SEARCH THE KNOWLEDGE BASE using `search_knowledge_base` for grounded answers
2. SEARCH THE WEB using `search_web` for recent or supplementary information
3. ANSWER QUESTIONS about AMR using retrieved context
4. GENERATE QUIZZES using the `generate_quiz` tool
5. CREATE FLASHCARDS using the `generate_flashcards` tool
6. EVALUATE ANSWERS using the `evaluate_answer` tool

DECISION RULES:
- If the user asks a factual question → call search_knowledge_base FIRST,
  then synthesize an answer from the retrieved context.
  Always cite sources (e.g. [Source: who-amr-factsheet]).
- If the knowledge base returns "Sufficient context: No" → call search_web
  as a follow-up to supplement the answer.
- If the user asks about *recent*, *latest*, or *new* research → call
  search_web directly (optionally also search_knowledge_base).
- If the user wants a quiz or test → call generate_quiz
- If the user wants flashcards or study cards → call generate_flashcards
- If the user wants their answer graded → call evaluate_answer
- For simple greetings or clarifications → respond directly, no tools needed

When answering questions with retrieved context:
- Synthesize information from the chunks into a coherent answer
- Cite sources using the source IDs provided
- Adapt complexity to the user's level
- Be thorough but concise
- End with a follow-up question to deepen learning
- If both knowledge base and web results were used, integrate both seamlessly

After calling a tool that produces a panel (quiz, flashcards, evaluation),
write a SHORT friendly message (1-2 sentences) telling the user what was
created. Do NOT repeat the tool's raw data.

You have full conversation history — reference prior topics naturally.
""".strip()


# ─────────────────────────────────────────────
# Tool: Generate Quiz
# ─────────────────────────────────────────────

def generate_quiz(
    ctx: RunContext[AgentDeps], topic: str, num_questions: int = 5
) -> str:
    """Build a multiple-choice quiz and show it in the quiz panel.

    Use when the user asks for a quiz, practice questions, a test, MCQs, or
    wants to check knowledge on a **specific** AMR theme. Do **not** use for
    open-ended factual questions—answer those in normal text without this tool.

    Difficulty follows the user's profile level. Full question data is stored
    for the UI; the return value is only a short confirmation for the model.

    Args:
        topic: One coherent AMR subject for every question (e.g. beta-lactamases,
            ESKAPE pathogens, antibiotic stewardship). Avoid mixing unrelated
            themes in a single quiz.
        num_questions: How many MCQs to generate. Prefer 3–7; default 5.

    Returns:
        Brief confirmation with question count, topic, and level.
    """
    _record_tool_start(ctx, "generate_quiz")
    level = ctx.deps.user_profile.level.value

    quiz_gen = Agent(
        "openai:gpt-4o",
        output_type=QuizSet,
        instructions=f"""
            Generate exactly {num_questions} MCQs about '{topic}' at '{level}'
            difficulty.

            Each question: exactly 4 options, one correct.
            Difficulty:
            - beginner: Definitions, basic facts
            - intermediate: Mechanisms, clinical scenarios
            - advanced: Molecular details, guideline-based decisions
            Make distractors plausible. Explanations should teach.
            """.strip(),
    )

    result = quiz_gen.run_sync(f"Quiz about: {topic}")
    quiz = result.output

    if topic not in ctx.deps.user_profile.topics_covered:
        ctx.deps.user_profile.topics_covered.append(topic)

    # Write to shared deps — app.py reads this after the stream
    ctx.deps.tool_output.panel_type = "quiz"
    ctx.deps.tool_output.data = quiz

    n = len(quiz.questions)
    _record_tool_complete(ctx, "generate_quiz")
    return f"Quiz created: {n} questions about {topic} at {level} level."


# ─────────────────────────────────────────────
# Tool: Generate Flashcards
# ─────────────────────────────────────────────

def generate_flashcards(
    ctx: RunContext[AgentDeps], topic: str, num_cards: int = 6
) -> str:
    """Create a flashcard deck and show it in the flashcards panel.

    Use when the user wants flashcards, study cards, or quick recall items on
    an AMR topic. Do **not** use for multiple-choice quizzes (use
    ``generate_quiz``) or for grading a free-text answer the user just wrote
    (use ``evaluate_answer`` with their text and the expected answer).

    Card difficulty follows the user's profile level. The deck payload is
    stored for the UI; the return value is a short confirmation.

    Args:
        topic: AMR theme for the deck (e.g. efflux pumps, MRSA, stewardship).
        num_cards: How many cards to generate. Prefer 4–10; default 6.

    Returns:
        Short confirmation with card count and deck title.
    """
    _record_tool_start(ctx, "generate_flashcards")
    level = ctx.deps.user_profile.level.value

    fc_gen = Agent(
        "openai:gpt-4o",
        output_type=FlashcardDeck,
        instructions=f"""
            Create {num_cards} flashcards about '{topic}' at '{level}' level.

            Each card: one concept, 1-3 sentence answer.
            Mix types: definition, mechanism, comparison, application.
            Order from fundamental to advanced.
            """.strip(),
    )

    result = fc_gen.run_sync(f"Flashcards about: {topic}")
    deck = result.output

    if topic not in ctx.deps.user_profile.topics_covered:
        ctx.deps.user_profile.topics_covered.append(topic)

    ctx.deps.tool_output.panel_type = "flashcards"
    ctx.deps.tool_output.data = deck

    _record_tool_complete(ctx, "generate_flashcards")
    return f"Created {len(deck.cards)} flashcards: '{deck.deck_title}'."


# ─────────────────────────────────────────────
# Tool: Evaluate Answer (LLM-as-Judge)
# ─────────────────────────────────────────────

def evaluate_answer(
    ctx: RunContext[AgentDeps],
    student_answer: str,
    reference_answer: str,
) -> str:
    """Judge a learner's free-text answer against a reference answer.

    Use when you have **both** the user's submitted answer and the correct or
    model answer to compare (e.g. after a flashcard reveal, short-answer item,
    or explicit "evaluate my answer" with quoted text). Do **not** use for
    general AMR questions with no specific answer to score.

    Structured feedback (score, strengths, gaps) is stored for the evaluation
    panel; the return value is a one-line score summary.

    Args:
        student_answer: The learner's response, as they wrote it.
        reference_answer: The expected or gold-standard answer to judge against.

    Returns:
        Brief line including the percentage score; detailed feedback is in panel
        data, not in this string.
    """
    _record_tool_start(ctx, "evaluate_answer")
    level = ctx.deps.user_profile.level.value

    judge = Agent(
        "openai:gpt-4o",
        output_type=AnswerEvaluation,
        instructions=f"""
                You are an AMR expert evaluator.
                Scoring rubric (0.0–1.0):
                - 0.9-1.0: Complete, accurate
                - 0.7-0.8: Mostly correct, minor gaps
                - 0.5-0.6: Partial understanding
                - 0.3-0.4: Significant gaps
                - 0.0-0.2: Incorrect or irrelevant

                Evaluate at '{level}' standard. Be encouraging but honest.
                """.strip(),
    )

    result = judge.run_sync(
        f"Reference: {reference_answer}\n\nStudent: {student_answer}\n\nEvaluate."
    )
    evaluation = result.output

    ctx.deps.tool_output.panel_type = "evaluation"
    ctx.deps.tool_output.data = evaluation

    _record_tool_complete(ctx, "evaluate_answer")
    return f"Evaluation complete: {evaluation.score:.0%} score."


# ─────────────────────────────────────────────
# Tool: Search Knowledge Base (RAG)
# ─────────────────────────────────────────────


def _format_retrieved_context(ctx_result: RetrievedContext) -> str:
    """Format RetrievedContext into a string the agent can synthesize."""
    if not ctx_result.chunks:
        return (
            "No relevant context found in the knowledge base.\n"
            f"Query: {ctx_result.query}\n"
            "Sufficient context: No"
        )

    parts: list[str] = []
    for i, chunk in enumerate(ctx_result.chunks, 1):
        parts.append(
            f"[Source: {chunk.source_id}, Score: {chunk.score:.2f}]\n({i}) {chunk.text}"
        )

    sources_line = ", ".join(ctx_result.sources_cited)
    sufficient = "Yes" if ctx_result.has_sufficient_context else "No"
    parts.append(f"---\nSources: {sources_line}\nSufficient context: {sufficient}")
    return "\n\n".join(parts)


def _format_web_results(results: list[dict[str, str]], query: str) -> str:
    """Format DuckDuckGo results into a citation-friendly context string."""
    if not results:
        return f"No relevant web results found.\nQuery: {query}\nSufficient context: No"

    parts: list[str] = []
    for i, item in enumerate(results, 1):
        title = item.get("title", "Untitled result")
        href = item.get("href", "")
        body = item.get("body", "")
        parts.append(f"[Web {i}] {title}\nURL: {href}\nSnippet: {body}")

    parts.append("---\nSources: web-search\nSufficient context: Yes")
    return "\n\n".join(parts)


def search_knowledge_base(
    ctx: RunContext[AgentDeps],
    query: str,
) -> str:
    """Search the local AMR knowledge base for relevant context.

    Use when the user asks a factual question about AMR and you want
    grounded, source-backed information to base your answer on.
    Prefer this over answering purely from your training data.

    Do NOT use for quiz generation, flashcard creation, or answer
    evaluation — those have dedicated tools.

    Args:
        query: A focused search query derived from the user's question.
            Rephrase the user's question into a clear retrieval query
            (e.g. "mechanisms of carbapenem resistance" rather than
            "how do bacteria become resistant to carbapenems?").

    Returns:
        Formatted context chunks with source IDs and relevance scores.
        If 'Sufficient context: No', consider calling search_web
        for additional information.
    """
    _record_tool_start(ctx, "search_knowledge_base")

    collection = ctx.deps.collection
    if collection is None:
        _record_tool_complete(ctx, "search_knowledge_base")
        return "Knowledge base unavailable: no ChromaDB collection configured."

    top_k = 5
    if ctx.deps.settings:
        top_k = ctx.deps.settings.rag_top_k

    # expertise_level = ctx.deps.user_profile.level.value

    result = retrieve(
        query=query,
        collection=collection,
        top_k=top_k,
        expertise_level=None, # TODO: no expertise level save in chromadb yet
    )

    formatted = _format_retrieved_context(result)
    _record_tool_complete(ctx, "search_knowledge_base")
    return formatted


async def search_web(
    ctx: RunContext[AgentDeps],
    query: str,
) -> str:
    """Perform a web search using the provided query string.

    This tool logs the search execution in the run context and retrieves
    relevant results via the DuckDuckGo search backend.

    Args:
        ctx: Execution context containing agent state and logging utilities.
        query: The search query string.

    Returns:
        A string containing the aggregated search results.
    """
    _record_tool_start(ctx, "search_web")
    ddg_tool = duckduckgo_search_tool()
    result_or_awaitable = ddg_tool.function(query)
    result = (
        await result_or_awaitable
        if inspect.isawaitable(result_or_awaitable)
        else result_or_awaitable
    )
    formatted = _format_web_results(result, query)
    _record_tool_complete(ctx, "search_web")
    return formatted


# ─────────────────────────────────────────────
# Orchestrator with Streaming
# ─────────────────────────────────────────────

class AMROrchestrator:
    """
    v3: Streaming Q&A + single-call tools + conversation memory.

    Two entry points:
      handle_message_streaming() → (generator, StreamResult) for st.write_stream()
      handle_message()           → dict (non-streaming fallback)
    """

    def __init__(
        self,
        collection: chromadb.Collection | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._collection = collection
        self._settings = settings
        self._agent = Agent(
            "openai:gpt-4o",
            deps_type=AgentDeps,
            instructions=_AMR_SYSTEM_INSTRUCTIONS,
            tools=[
                generate_quiz,
                generate_flashcards,
                evaluate_answer,
                search_knowledge_base,
                search_web,
            ],
        )

        @self._agent.instructions
        def dynamic_context(ctx: RunContext[AgentDeps]) -> str:
            profile = ctx.deps.user_profile
            level = profile.level.value
            topics = profile.topics_covered[-8:]
            avg = profile.avg_score

            lines = [
                f"\nUser level: {level}",
                f"Topics covered: {', '.join(topics) if topics else 'none yet'}",
            ]
            if avg is not None:
                lines.append(f"Average quiz score: {avg:.0%}")

            lines.append(
                """\nLevel-adaptation guide:
        - beginner: Simple language, analogies, no jargon
        - intermediate: Proper terminology with brief explanations
        - advanced: Technical depthorch., cite mechanisms and guidelines
        """.strip()
            )
            return "\n".join(lines)

    # ── Streaming entry point ──

    def handle_message_streaming(
        self,
        message: str,
        profile: UserProfile,
        message_history: list[ModelMessage] | None = None,
    ) -> tuple[Generator[StreamChunk, None, None], StreamResult]:
        """
        Returns (text_generator, stream_result).

        Usage in Streamlit:
            gen, meta = orch.handle_message_streaming(msg, profile, history)
            full_text = st.write_stream(gen)   # streams to chat UI
            # meta is now populated:
            st.session_state.agent_history = meta.message_history
            if meta.panel: open_panel(meta.panel, meta.data)
        """
        # Verify that message is about AMR as a guardrail
        
        check_amr = Agent(
            "openai:gpt-4o",
            output_type=bool,
            instructions="Make sure that the message is about AMR. If it is not, return False. If it is, return True."
        )
        stream_result = StreamResult()
        result = check_amr.run_sync(f"Is the following message about AMR? {message}")
        if not result.output:
            stream_result.full_text = "The message is not about AMR. Please ask me about AMR."
            stream_result.message_history = message_history or []

            def non_amr_generator() -> Generator[StreamChunk, None, None]:
                yield StreamChunk(kind="text", text=stream_result.full_text)

            return non_amr_generator(), stream_result

        stream_queue: Queue[StreamChunk | None] = Queue()

        deps = AgentDeps(
            user_profile=profile,
            collection=self._collection,
            settings=self._settings,
            stream_event_sink=lambda event: stream_queue.put(
                StreamChunk(kind="tool_event", tool_event=event)
            ),
        )

        def worker() -> None:
            try:
                result = self._agent.run_stream_sync(
                    message,
                    deps=deps,
                    message_history=message_history,
                )
                text_parts: list[str] = []

                # Request real delta streaming with no debouncing.
                for delta in result.stream_text(delta=True, debounce_by=None):
                    if delta:
                        text_parts.append(delta)
                        stream_queue.put(StreamChunk(kind="text", text=delta))

                stream_result.full_text = "".join(text_parts)
                stream_result.message_history = result.all_messages()
                if deps.tool_output.panel_type:
                    stream_result.panel = deps.tool_output.panel_type
                    stream_result.data = deps.tool_output.data
                stream_result.tool_events = list(deps.tool_events)
            except Exception:
                fallback = self._run_sync(message, profile, deps, message_history)
                stream_result.full_text = fallback["response"]
                stream_result.message_history = fallback["message_history"]
                stream_result.panel = fallback.get("panel")
                stream_result.data = fallback.get("data")
                stream_result.tool_events = fallback.get("tool_events", [])
                if stream_result.full_text:
                    stream_queue.put(StreamChunk(kind="text", text=stream_result.full_text))
            finally:
                stream_queue.put(None)

        Thread(target=worker, daemon=True).start()

        def chunk_generator() -> Generator[StreamChunk, None, None]:
            while True:
                item = stream_queue.get()
                if item is None:
                    break
                yield item

        return chunk_generator(), stream_result

    # ── Non-streaming entry point ──

    def handle_message(
        self,
        message: str,
        profile: UserProfile,
        message_history: list[ModelMessage] | None = None,
    ) -> dict:
        """Non-streaming. Returns dict with response, panel, data, message_history."""
        deps = AgentDeps(
            user_profile=profile,
            collection=self._collection,
            settings=self._settings,
        )
        return self._run_sync(message, profile, deps, message_history)

    def _run_sync(
        self,
        message: str,
        profile: UserProfile,
        deps: AgentDeps,
        message_history: list[ModelMessage] | None,
    ) -> dict:
        try:
            result = self._agent.run_sync(
                message,
                deps=deps,
                message_history=message_history,
            )
            return {
                "response": result.output,
                "panel": deps.tool_output.panel_type,
                "data": deps.tool_output.data,
                "message_history": result.all_messages(),
                "tool_events": list(deps.tool_events),
            }
        except Exception as e:
            return {
                "response": f"⚠️ Something went wrong: {e}\n\nPlease try rephrasing.",
                "panel": None,
                "data": None,
                "message_history": message_history or [],
                "tool_events": [],
            }

    # ── Convenience: evaluate flashcard ──

    def evaluate_flashcard(
        self,
        user_answer: str,
        expected_answer: str,
        profile: UserProfile,
        message_history: list[ModelMessage] | None = None,
    ) -> dict:
        """Direct evaluation (non-streaming, updates history)."""
        return self.handle_message(
            f"Evaluate my flashcard answer.\n\n"
            f"My answer: {user_answer}\n\n"
            f"Expected answer: {expected_answer}",
            profile,
            message_history,
        )


# ─────────────────────────────────────────────
# Smoke test
# ─────────────────────────────────────────────

if __name__ == "__main__":
    from src.rag.ingestor import get_or_create_collection

    _settings = Settings()
    try:
        _collection = get_or_create_collection(_settings)
    except Exception:
        _collection = None

    orch = AMROrchestrator(collection=_collection, settings=_settings)
    profile = UserProfile()

    # Test 1: Streaming Q&A
    print("=" * 60)
    print("TEST 1: Streaming Q&A")
    print("=" * 60)
    gen, meta = orch.handle_message_streaming("What are main risks of AMR?", profile)
    print("Stream: ", end="", flush=True)
    for chunk in gen:
        print(chunk, end="", flush=True)
    print(f"\n\nPanel: {meta.panel} | History: {len(meta.message_history)} msgs")

    # Test 2: Follow-up with memory
    print("\n" + "=" * 60)
    print("TEST 2: Follow-up (memory test)")
    print("=" * 60)
    gen2, meta2 = orch.handle_message_streaming(
        "Which one is hardest to treat?", profile,
        message_history=meta.message_history,
    )
    print("Stream: ", end="", flush=True)
    for chunk in gen2:
        print(chunk, end="", flush=True)
    print(f"\n\nHistory: {len(meta2.message_history)} msgs")

    # Test 3: Tool call (quiz)
    print("\n" + "=" * 60)
    print("TEST 3: Quiz (tool + stream)")
    print("=" * 60)
    gen3, meta3 = orch.handle_message_streaming(
        "Quiz me on what we discussed", profile,
        message_history=meta2.message_history,
    )
    print("Stream: ", end="", flush=True)
    for chunk in gen3:
        print(chunk, end="", flush=True)
    print(f"\n\nPanel: {meta3.panel}")
    if meta3.data and hasattr(meta3.data, "questions"):
        print(f"Questions: {len(meta3.data.questions)}")
    print(f"Topics: {profile.topics_covered}")
