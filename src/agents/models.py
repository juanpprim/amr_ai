"""
models.py — Pydantic models for the AMR Agentic Learning Workflow

All structured I/O across agents is defined here.
Used as `result_type` in Pydantic AI agents to enforce schema compliance.
"""

from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


# ─────────────────────────────────────────────
# User Profile & Level
# ─────────────────────────────────────────────

class UserLevel(str, Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class UserProfile(BaseModel):
    """Persisted user state across sessions."""
    level: UserLevel = UserLevel.beginner
    topics_covered: list[str] = Field(default_factory=list)
    quiz_scores: list[float] = Field(default_factory=list)

    @property
    def avg_score(self) -> float | None:
        if not self.quiz_scores:
            return None
        return sum(self.quiz_scores) / len(self.quiz_scores)

    def should_promote(self) -> bool:
        """Promote if last 3 quizzes avg > 0.8."""
        recent = self.quiz_scores[-3:]
        if len(recent) < 3:
            return False
        return (sum(recent) / len(recent)) > 0.8

    def should_demote(self) -> bool:
        """Demote if last 3 quizzes avg < 0.4."""
        recent = self.quiz_scores[-3:]
        if len(recent) < 3:
            return False
        return (sum(recent) / len(recent)) < 0.4

    def adjust_level(self) -> bool:
        """Auto-adjust level based on scores. Returns True if changed."""
        if self.should_promote() and self.level != UserLevel.advanced:
            levels = list(UserLevel)
            current_idx = levels.index(self.level)
            self.level = levels[min(current_idx + 1, len(levels) - 1)]
            return True
        if self.should_demote() and self.level != UserLevel.beginner:
            levels = list(UserLevel)
            current_idx = levels.index(self.level)
            self.level = levels[max(current_idx - 1, 0)]
            return True
        return False


# ─────────────────────────────────────────────
# Router Agent — Intent Classification
# ─────────────────────────────────────────────

class UserIntent(str, Enum):
    ask_question = "ask_question"
    take_quiz = "take_quiz"
    flashcards = "flashcards"
    evaluate = "evaluate"


class RouterDecision(BaseModel):
    """Output of the Router Agent."""
    intent: UserIntent
    topic: str = Field(description="Extracted topic from the user message, e.g. 'beta-lactamases'")
    reasoning: str = Field(description="Brief explanation of why this intent was chosen")


# ─────────────────────────────────────────────
# Q&A Agent
# ─────────────────────────────────────────────

class AMRAnswer(BaseModel):
    """Structured response from the Q&A Agent."""
    answer: str = Field(description="The main answer, adapted to user level")
    key_concepts: list[str] = Field(
        default_factory=list,
        description="2-4 key concepts mentioned in the answer, used for flashcard generation",
    )
    follow_up: str = Field(
        default="",
        description="A suggested follow-up question to deepen learning",
    )


# ─────────────────────────────────────────────
# Quiz Agent
# ─────────────────────────────────────────────

class QuizQuestion(BaseModel):
    """A single multiple-choice question."""
    question: str
    options: list[str] = Field(min_length=4, max_length=4, description="Exactly 4 options")
    correct_index: int = Field(ge=0, le=3, description="Index of the correct option (0-3)")
    explanation: str = Field(description="Why the correct answer is right")


class QuizSet(BaseModel):
    """Output of the Quiz Agent — a set of questions."""
    questions: list[QuizQuestion] = Field(min_length=1, max_length=10)
    topic: str
    difficulty: UserLevel


# ─────────────────────────────────────────────
# Flashcard Agent
# ─────────────────────────────────────────────

class Flashcard(BaseModel):
    """A single flashcard for spaced repetition."""
    question: str = Field(description="The question side of the card")
    answer: str = Field(description="The answer side — concise but complete")
    topic: str
    difficulty: UserLevel


class FlashcardDeck(BaseModel):
    """Output of the Flashcard Agent."""
    cards: list[Flashcard] = Field(min_length=1, max_length=20)
    deck_title: str = Field(description="Short title for this deck, e.g. 'Beta-Lactam Resistance'")


# ─────────────────────────────────────────────
# Judge Agent — LLM-as-a-Judge Evaluation
# ─────────────────────────────────────────────

class AnswerEvaluation(BaseModel):
    """Structured rubric output from the Judge Agent."""
    score: float = Field(ge=0.0, le=1.0, description="Overall score from 0.0 to 1.0")
    feedback: str = Field(description="One-paragraph overall feedback")
    correct_parts: list[str] = Field(
        default_factory=list,
        description="Specific things the student got right",
    )
    missing_parts: list[str] = Field(
        default_factory=list,
        description="Key concepts that were missing from the answer",
    )
    suggestion: str = Field(
        default="",
        description="Actionable next step for the student",
    )
