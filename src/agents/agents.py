"""
agents.py — Single Agent + Streaming + Conversation Memory (v3)

Changes from v2:
  - Streaming: Q&A responses stream token-by-token via run_stream_sync()
  - Clean tool output: tools write to deps.tool_output instead of embedding
    data markers in text — streamed text stays clean
  - StreamResult container captures history + panel data after stream ends
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generator

from pydantic_ai import Agent, RunContext
from pydantic_ai.messages import ModelMessage

from src.agents.models import (
    AnswerEvaluation,
    FlashcardDeck,
    QuizSet,
    UserProfile,
)

# ─────────────────────────────────────────────
# Dependencies — tools write structured output here
# ─────────────────────────────────────────────

@dataclass
class ToolOutput:
    """Populated by tools during execution. Checked after the run."""
    panel_type: str | None = None   # "quiz" | "flashcards" | "evaluation"
    data: object | None = None      # QuizSet | FlashcardDeck | AnswerEvaluation


@dataclass
class AgentDeps:
    """Injected into the agent at runtime."""
    user_profile: UserProfile
    tool_output: ToolOutput = field(default_factory=ToolOutput)


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


# ─────────────────────────────────────────────
# AMR agent system prompt + tools (registered on Agent via tools=[...])
# ─────────────────────────────────────────────

_AMR_SYSTEM_INSTRUCTIONS = """
        You are an expert Antimicrobial Resistance (AMR) learning assistant.

        You can do four things:
        1. ANSWER QUESTIONS about AMR directly (no tool needed)
        2. GENERATE QUIZZES using the `generate_quiz` tool
        3. CREATE FLASHCARDS using the `generate_flashcards` tool
        4. EVALUATE ANSWERS using the `evaluate_answer` tool

        DECISION RULES:
        - If the user asks a factual question → answer directly in your response
        - If the user wants a quiz or test → call generate_quiz
        - If the user wants flashcards or study evaluation → call evaluate_answer

        When answering questions directly:
        - Adapt complexity to the user's level
        - Be thorough but concise
        - End with a follow-up question to deepen learning

        After calling a tool, write a SHORT friendly message (1-2 sentences)
        telling the user what was created. Do NOT repeat the tool's raw data.

        You have full conversation history — reference prior topics naturally.
        """.strip()


# ─────────────────────────────────────────────
# Tool: Generate Quiz
# ─────────────────────────────────────────────

def generate_quiz(
    ctx: RunContext[AgentDeps], topic: str, num_questions: int = 5
) -> str:
    """
    Generate a multiple-choice quiz on an AMR topic.

    Args:
        topic: The AMR topic to quiz on (e.g. 'beta-lactamases', 'ESKAPE pathogens')
        num_questions: Number of questions (3-7, default 5)
    """
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
    return f"Quiz created: {n} questions about {topic} at {level} level."


# ─────────────────────────────────────────────
# Tool: Generate Flashcards
# ─────────────────────────────────────────────

def generate_flashcards(
    ctx: RunContext[AgentDeps], topic: str, num_cards: int = 6
) -> str:
    """
    Create flashcards on an AMR topic for spaced repetition study.

    Args:
        topic: The AMR topic (e.g. 'efflux pumps', 'antibiotic stewardship')
        num_cards: Number of cards (4-10, default 6)
    """
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

    return f"Created {len(deck.cards)} flashcards: '{deck.deck_title}'."


# ─────────────────────────────────────────────
# Tool: Evaluate Answer (LLM-as-Judge)
# ─────────────────────────────────────────────

def evaluate_answer(
    ctx: RunContext[AgentDeps],
    student_answer: str,
    reference_answer: str,
) -> str:
    """
    Evaluate a student's free-text answer against a reference answer.

    Args:
        student_answer: What the student wrote
        reference_answer: The expected correct answer
    """
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

    return f"Evaluation complete: {evaluation.score:.0%} score."


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

    def __init__(self) -> None:
        self._agent = Agent(
            "openai:gpt-4o",
            deps_type=AgentDeps,
            instructions=_AMR_SYSTEM_INSTRUCTIONS,
            tools=[
                generate_quiz,
                generate_flashcards,
                evaluate_answer,
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
        - advanced: Technical depth, cite mechanisms and guidelines
        """.strip()
            )
            return "\n".join(lines)

    # ── Streaming entry point ──

    def handle_message_streaming(
        self,
        message: str,
        profile: UserProfile,
        message_history: list[ModelMessage] | None = None,
    ) -> tuple[Generator[str, None, None], StreamResult]:
        """
        Returns (text_generator, stream_result).

        Usage in Streamlit:
            gen, meta = orch.handle_message_streaming(msg, profile, history)
            full_text = st.write_stream(gen)   # streams to chat UI
            # meta is now populated:
            st.session_state.agent_history = meta.message_history
            if meta.panel: open_panel(meta.panel, meta.data)
        """
        stream_result = StreamResult()
        deps = AgentDeps(user_profile=profile)

        def text_generator() -> Generator[str, None, None]:
            try:
                with self._agent.run_stream_sync(
                    message,
                    deps=deps,
                    message_history=message_history,
                ) as result:
                    # stream_text() yields CUMULATIVE text.
                    # Convert to deltas for st.write_stream().
                    previous = ""
                    for chunk in result.stream_text():
                        delta = chunk[len(previous):]
                        previous = chunk
                        if delta:
                            yield delta

                    # Stream done — capture metadata
                    stream_result.full_text = previous
                    stream_result.message_history = result.all_messages()

                    # Check if a tool wrote panel data
                    if deps.tool_output.panel_type:
                        stream_result.panel = deps.tool_output.panel_type
                        stream_result.data = deps.tool_output.data

            except Exception:
                # Fallback to sync if streaming fails
                fallback = self._run_sync(message, profile, deps, message_history)
                stream_result.full_text = fallback["response"]
                stream_result.message_history = fallback["message_history"]
                stream_result.panel = fallback.get("panel")
                stream_result.data = fallback.get("data")
                yield stream_result.full_text

        return text_generator(), stream_result

    # ── Non-streaming entry point ──

    def handle_message(
        self,
        message: str,
        profile: UserProfile,
        message_history: list[ModelMessage] | None = None,
    ) -> dict:
        """Non-streaming. Returns dict with response, panel, data, message_history."""
        deps = AgentDeps(user_profile=profile)
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
            }
        except Exception as e:
            return {
                "response": f"⚠️ Something went wrong: {e}\n\nPlease try rephrasing.",
                "panel": None,
                "data": None,
                "message_history": message_history or [],
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
    orch = AMROrchestrator()
    profile = UserProfile()

    # Test 1: Streaming Q&A
    print("=" * 60)
    print("TEST 1: Streaming Q&A")
    print("=" * 60)
    gen, meta = orch.handle_message_streaming("What are ESKAPE pathogens?", profile)
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
