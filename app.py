"""
AMR Agentic Learning Workflow — Streamlit MVP (v3)

v3 improvements:
  - Streaming Q&A: tokens appear as they're generated via st.write_stream()
  - Tool calls (quiz/flashcards): brief wait during tool execution,
    then the chat response streams normally
  - Conversation memory persists across all turns
  - HTML-escaped flashcard content
"""

import streamlit as st

from src.agents.agents import AMROrchestrator, StreamChunk, format_agent_activity_steps
from src.agents.models import UserLevel, UserProfile

# ─────────────────────────────────────────────
# Page config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="AMR Learning Agent",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────
st.markdown("""
<style>
    .block-container { padding-top: 1.5rem; }

    .flip-card {
        perspective: 800px;
        width: 100%;
        height: 180px;
        margin-bottom: 12px;
        cursor: pointer;
    }
    .flip-card-inner {
        position: relative;
        width: 100%;
        height: 100%;
        transition: transform 0.5s ease;
        transform-style: preserve-3d;
    }
    .flip-card:hover .flip-card-inner {
        transform: rotateY(180deg);
    }
    .flip-card-front, .flip-card-back {
        position: absolute;
        width: 100%;
        height: 100%;
        backface-visibility: hidden;
        border-radius: 12px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        align-items: center;
        padding: 20px;
        box-sizing: border-box;
        text-align: center;
    }
    .flip-card-front {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        font-size: 15px;
        font-weight: 500;
        line-height: 1.5;
    }
    .flip-card-back {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        color: white;
        transform: rotateY(180deg);
        font-size: 14px;
        line-height: 1.5;
    }
    .flip-hint {
        font-size: 11px;
        opacity: 0.7;
        margin-top: 8px;
    }
    .card-label {
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        opacity: 0.8;
        margin-bottom: 8px;
    }
    .panel-header {
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        color: #888;
        font-weight: 600;
        margin-bottom: 12px;
        padding-bottom: 8px;
        border-bottom: 2px solid #f0f0f0;
    }
    /* Agent activity expander */
    div[data-testid="stExpander"] details summary {
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────

@st.cache_resource
def get_orchestrator(version: str = "v3-rag-exa") -> AMROrchestrator:
    """Create orchestrator with ChromaDB collection and settings."""
    _ = version
    from src.config import Settings
    from src.rag.ingestor import get_or_create_collection

    settings = Settings()
    try:
        collection = get_or_create_collection(settings)
    except Exception:
        collection = None
    return AMROrchestrator(collection=collection, settings=settings)

orch = get_orchestrator()


# ─────────────────────────────────────────────
# Session state
# ─────────────────────────────────────────────

def init_state():
    defaults = {
        # Display messages (what the user sees)
        "messages": [
            {
                "role": "assistant",
                "content": (
                    "👋 Hi! I'm your AMR learning assistant. "
                    "Ask me anything about antimicrobial resistance, or try:\n\n"
                    "• *\"Quiz me on AMR basics\"*\n"
                    "• *\"Make flashcards about beta-lactamases\"*\n"
                    "• *\"What are ESKAPE pathogens?\"*"
                ),
            }
        ],

        # Agent memory (list[ModelMessage] — includes tool calls, full context)
        "agent_history": None,

        # Right panel
        "right_panel": None,

        # Flashcards
        "flashcard_deck": [],
        "flashcard_deck_title": "",
        "flashcard_index": 0,

        # Quiz
        "quiz_questions": [],
        "quiz_topic": "",
        "quiz_index": 0,
        "quiz_answers": [],
        "quiz_scored": False,

        # Evaluation
        "evaluation": None,

        # Profile
        "user_profile": UserProfile(),

        # Streaming flag — True while a response is being streamed
        "is_streaming": False,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

init_state()


def get_profile() -> UserProfile:
    return st.session_state.user_profile

def sync_profile(profile: UserProfile):
    st.session_state.user_profile = profile


# ─────────────────────────────────────────────
# HTML helper
# ─────────────────────────────────────────────

def html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
        .replace("\n", "<br>")
    )


# ─────────────────────────────────────────────
# Panel renderers
# ─────────────────────────────────────────────

def render_flashcards():
    deck = st.session_state.flashcard_deck
    if not deck:
        return

    st.markdown('<div class="panel-header">🃏 Flashcards</div>', unsafe_allow_html=True)

    if st.session_state.flashcard_deck_title:
        st.markdown(f"**{st.session_state.flashcard_deck_title}**")

    idx = st.session_state.flashcard_index
    card = deck[idx]

    st.caption(
        f"Card {idx + 1} of {len(deck)}  ·  "
        f"{card['topic']}  ·  _{card['difficulty']}_"
    )

    q_esc = html_escape(card["question"])
    a_esc = html_escape(card["answer"])
    st.markdown(f"""
    <div class="flip-card">
        <div class="flip-card-inner">
            <div class="flip-card-front">
                <div class="card-label">Question</div>
                {q_esc}
                <div class="flip-hint">hover to reveal answer</div>
            </div>
            <div class="flip-card-back">
                <div class="card-label">Answer</div>
                {a_esc}
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    nav = st.columns([1, 1, 1])
    with nav[0]:
        if st.button("⬅ Prev", disabled=(idx == 0), use_container_width=True):
            st.session_state.flashcard_index -= 1
            st.rerun()
    with nav[1]:
        st.button(f"{idx + 1}/{len(deck)}", disabled=True, use_container_width=True)
    with nav[2]:
        if st.button("Next ➡", disabled=(idx >= len(deck) - 1), use_container_width=True):
            st.session_state.flashcard_index += 1
            st.rerun()

    # Judge evaluation
    st.divider()
    st.caption("📝 Type your answer to get AI feedback:")
    user_answer = st.text_area("Answer", key=f"fc_ans_{idx}", height=80, label_visibility="collapsed")
    if st.button("Evaluate", key=f"fc_eval_{idx}", type="primary", use_container_width=True):
        if user_answer.strip():
            with st.spinner("🤖 Evaluating..."):
                try:
                    profile = get_profile()
                    result = orch.evaluate_flashcard(
                        user_answer=user_answer,
                        expected_answer=card["answer"],
                        profile=profile,
                        message_history=st.session_state.agent_history,
                    )
                    st.session_state.agent_history = result["message_history"]
                    if result["data"]:
                        st.session_state.evaluation = result["data"].model_dump()
                    st.session_state.right_panel = "evaluation"
                    st.session_state.messages.append(
                        {"role": "assistant", "content": result["response"]}
                    )
                    st.rerun()
                except Exception as e:
                    st.error(f"Evaluation failed: {e}")

    st.divider()
    if st.button("✕ Close flashcards", use_container_width=True):
        st.session_state.right_panel = None
        st.rerun()


def render_quiz():
    questions = st.session_state.quiz_questions
    if not questions:
        return

    st.markdown('<div class="panel-header">📝 Quiz</div>', unsafe_allow_html=True)
    if st.session_state.quiz_topic:
        st.caption(f"Topic: **{st.session_state.quiz_topic}**")

    idx = st.session_state.quiz_index
    q = questions[idx]
    st.caption(f"Question {idx + 1} of {len(questions)}")
    st.markdown(f"**{q['question']}**")

    answered = idx < len(st.session_state.quiz_answers)

    if answered:
        chosen = st.session_state.quiz_answers[idx]
        for i, opt in enumerate(q["options"]):
            if i == q["correct_index"]:
                st.success(f"✅ {opt}")
            elif i == chosen:
                st.error(f"❌ {opt}")
            else:
                st.markdown(f"　{opt}")
        st.info(f"💡 {q['explanation']}")

        if idx < len(questions) - 1:
            if st.button("Next question →", type="primary", use_container_width=True):
                st.session_state.quiz_index += 1
                st.rerun()
        else:
            if not st.session_state.quiz_scored:
                correct = sum(
                    1 for i, a in enumerate(st.session_state.quiz_answers)
                    if a == questions[i]["correct_index"]
                )
                score = correct / len(questions)
                profile = get_profile()
                profile.quiz_scores.append(score)
                level_changed = profile.adjust_level()
                sync_profile(profile)
                st.session_state.quiz_scored = True
                st.session_state._qscore = score
                st.session_state._qcorrect = correct
                st.session_state._qlevel_changed = level_changed

            score = st.session_state._qscore
            correct = st.session_state._qcorrect

            st.divider()
            if score >= 0.8:
                st.success(f"🎉 Score: {correct}/{len(questions)} — Excellent!")
            elif score >= 0.5:
                st.warning(f"📊 Score: {correct}/{len(questions)} — Good, keep practicing!")
            else:
                st.error(f"📊 Score: {correct}/{len(questions)} — Let's review this topic.")

            if st.session_state.get("_qlevel_changed"):
                st.info(f"📈 Level adjusted to **{get_profile().level.value.title()}**!")

            if st.button("✕ Close quiz", use_container_width=True):
                st.session_state.right_panel = None
                st.rerun()
    else:
        for i, opt in enumerate(q["options"]):
            if st.button(opt, key=f"qopt_{idx}_{i}", use_container_width=True):
                st.session_state.quiz_answers.append(i)
                st.rerun()

    st.divider()
    if st.button("✕ Close quiz", key="close_q_btm", use_container_width=True):
        st.session_state.right_panel = None
        st.rerun()


def render_evaluation():
    ev = st.session_state.evaluation
    if not ev:
        return

    st.markdown('<div class="panel-header">⚖️ Answer Evaluation</div>', unsafe_allow_html=True)

    score = ev["score"]
    color = "#28a745" if score >= 0.7 else "#ffc107" if score >= 0.4 else "#dc3545"
    st.markdown(f"""
    <div style="background:#f0f0f0;border-radius:10px;height:24px;margin-bottom:12px;">
        <div style="background:{color};width:{score*100}%;height:100%;
                    border-radius:10px;display:flex;align-items:center;
                    justify-content:center;color:white;font-weight:600;font-size:13px;">
            {score*100:.0f}%
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"**Feedback:** {ev['feedback']}")
    if ev.get("correct_parts"):
        st.markdown("**✅ What you got right:**")
        for p in ev["correct_parts"]:
            st.markdown(f"- {p}")
    if ev.get("missing_parts"):
        st.markdown("**🔍 What was missing:**")
        for p in ev["missing_parts"]:
            st.markdown(f"- {p}")
    if ev.get("suggestion"):
        st.info(f"💡 **Suggestion:** {ev['suggestion']}")

    if st.button("← Back to flashcards", use_container_width=True):
        st.session_state.right_panel = "flashcards"
        st.session_state.evaluation = None
        st.rerun()


# ─────────────────────────────────────────────
# Main layout
# ─────────────────────────────────────────────

profile = get_profile()
hdr = st.columns([4, 1])
with hdr[0]:
    st.markdown("### 🧬 AMR Learning Agent")
with hdr[1]:
    lvl_map = {
        UserLevel.beginner: "🟢 Beginner",
        UserLevel.intermediate: "🟡 Intermediate",
        UserLevel.advanced: "🔴 Advanced",
    }
    st.caption(f"Level: {lvl_map.get(profile.level, profile.level.value)}")

st.divider()

has_panel = st.session_state.right_panel is not None
if has_panel:
    col_chat, col_panel = st.columns([3, 2], gap="large")
else:
    col_chat = st.container()
    col_panel = None

# ── Chat column ──
with col_chat:
    chat_box = st.container(height=500)
    with chat_box:
        # Render all past messages
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
                act = msg.get("activity")
                if act and act.get("steps"):
                    with st.expander(
                        "⚙️ Agent activity — Done ✓",
                        expanded=act.get("expanded", False),
                    ):
                        if act.get("panel"):
                            st.caption(
                                f"Side panel: **{act['panel']}**"
                            )
                        st.markdown("\n\n".join(act["steps"]))

    # ── Chat input + streaming response ──
    if prompt := st.chat_input("Ask about AMR, request a quiz, or create flashcards..."):
        # Show user message immediately
        st.session_state.messages.append({"role": "user", "content": prompt})

        # Get streaming generator + metadata container
        profile = get_profile()
        
        generator, stream_meta = orch.handle_message_streaming(
            message=prompt,
            profile=profile,
            message_history=st.session_state.agent_history,
        )

        # Stream the response into the chat
        with chat_box:
            with st.chat_message("user"):
                st.markdown(prompt)
            with st.chat_message("assistant"):
                activity_placeholder = st.empty()
                live_tool_events = []

                def text_stream():
                    for item in generator:
                        # Backward-compatible handling:
                        # some cached orchestrator instances can still yield plain strings.
                        if isinstance(item, str):
                            if item:
                                yield item
                            continue

                        chunk: StreamChunk = item
                        if chunk.kind == "tool_event" and chunk.tool_event:
                            live_tool_events.append(chunk.tool_event)
                            running_steps, _ = format_agent_activity_steps(
                                live_tool_events,
                                panel_type=None,
                            )
                            with activity_placeholder.container():
                                with st.expander(
                                    "⚙️ Agent activity — Running...",
                                    expanded=True,
                                ):
                                    st.markdown("\n\n".join(running_steps))
                            continue

                        if chunk.kind == "text" and chunk.text:
                            yield chunk.text

                response_text = st.write_stream(text_stream())

        # ── After stream completes: update all state ──

        activity_steps, activity_expanded = format_agent_activity_steps(
            stream_meta.tool_events,
            panel_type=stream_meta.panel,
        )

        # Save assistant turn + collapsible activity log (shown after completion)
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": response_text,
                "activity": {
                    "steps": activity_steps,
                    "expanded": activity_expanded,
                    "panel": stream_meta.panel,
                },
            }
        )

        # Update agent memory
        st.session_state.agent_history = stream_meta.message_history

        # Sync profile (may have new topics)
        sync_profile(profile)

        # Open panel if a tool generated data
        if stream_meta.panel == "quiz" and stream_meta.data:
            quiz_set = stream_meta.data
            st.session_state.quiz_questions = [q.model_dump() for q in quiz_set.questions]
            st.session_state.quiz_topic = quiz_set.topic
            st.session_state.quiz_index = 0
            st.session_state.quiz_answers = []
            st.session_state.quiz_scored = False
            st.session_state.right_panel = "quiz"

        elif stream_meta.panel == "flashcards" and stream_meta.data:
            deck = stream_meta.data
            st.session_state.flashcard_deck = [c.model_dump() for c in deck.cards]
            st.session_state.flashcard_deck_title = deck.deck_title
            st.session_state.flashcard_index = 0
            st.session_state.right_panel = "flashcards"

        elif stream_meta.panel == "evaluation" and stream_meta.data:
            st.session_state.evaluation = stream_meta.data.model_dump()
            st.session_state.right_panel = "evaluation"

        st.rerun()

# ── Right panel ──
if has_panel and col_panel is not None:
    with col_panel:
        p = st.session_state.right_panel
        if p == "flashcards":
            render_flashcards()
        elif p == "quiz":
            render_quiz()
        elif p == "evaluation":
            render_evaluation()


# ─────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────
with st.sidebar:
    profile = get_profile()

    st.markdown("### 👤 User Profile")
    st.markdown(f"**Level:** {profile.level.value.title()}")

    if profile.quiz_scores:
        avg = profile.avg_score
        st.metric("Avg Quiz Score", f"{avg * 100:.0f}%")
        st.caption(f"Quizzes taken: {len(profile.quiz_scores)}")

    if profile.topics_covered:
        st.markdown("**Topics covered:**")
        for t in profile.topics_covered[-10:]:
            st.markdown(f"- {t}")

    history = st.session_state.agent_history
    if history:
        st.divider()
        st.caption(f"🧠 Agent memory: {len(history)} messages in context")

    st.divider()
    st.markdown("### ⚙️ Settings")

    lvl_opts = [l.value for l in UserLevel]
    cur_idx = lvl_opts.index(profile.level.value)
    new_lvl = st.selectbox("Override level", lvl_opts, index=cur_idx, format_func=str.title)
    if new_lvl != profile.level.value:
        profile.level = UserLevel(new_lvl)
        sync_profile(profile)
        st.rerun()

    st.divider()
    if st.button("🗑️ Reset conversation"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()

    st.divider()
    st.caption("Powered by Pydantic AI + OpenAI GPT-4o")
