"""Chat page — main conversational interface for Derma6.

Features:
- Empty state with suggestion pills
- Chat history rendering (user right-aligned, assistant white cards)
- Citations in expander
- Tool results in expander
- Spinner during backend call
- Error handling
"""

import os
import sys

import streamlit as st

sys.path.insert(0, os.path.abspath("."))

from backend.agent import BackendService
from backend.schemas import BackendRequest

SUGGESTIONS = [
    "Analyze my ingredients",
    "Build me a routine",
    "What is skin cycling?",
]

# --------------------------------------------------------------------------
# Initialise messages from session state (populated by app.py on first login)
# --------------------------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state["messages"] = []

username = st.session_state.get("username", "guest")

# --------------------------------------------------------------------------
# Empty state
# --------------------------------------------------------------------------
if not st.session_state["messages"] and "_pending_prompt" not in st.session_state:
    st.space("large")
    st.markdown("## How can I help you today?")
    st.caption(
        "Ask me about specific ingredients, building a personalised routine, "
        "or understanding skincare concepts."
    )
    st.space("small")
    selected = st.pills(
        "Suggestions",
        SUGGESTIONS,
        label_visibility="collapsed",
        selection_mode="single",
    )
    if selected:
        st.session_state["_pending_prompt"] = selected
        st.rerun()

# --------------------------------------------------------------------------
# RAG visualisation helper
# --------------------------------------------------------------------------
def _render_rag_expander(rag_context: list) -> None:
    with st.expander("🔍 RAG Retrieval"):
        for item in rag_context:
            source = item.get("source", "Unknown")
            score = item.get("score", 0.0)
            snippet = item.get("snippet", "")
            col_name, col_score = st.columns([3, 1])
            with col_name:
                st.markdown(f"**{source}**")
            with col_score:
                st.markdown(f"`{score:.0%}`")
            st.progress(min(max(score, 0.0), 1.0))
            if snippet:
                st.caption(snippet + ("…" if len(item.get("snippet", "")) >= 150 else ""))
            st.divider()


# --------------------------------------------------------------------------
# Render existing chat history
# --------------------------------------------------------------------------
for msg in st.session_state["messages"]:
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.write(msg["content"])
    else:
        with st.chat_message("assistant"):
            st.write(msg.get("content", ""))
            if msg.get("rag_context"):
                _render_rag_expander(msg["rag_context"])
            if msg.get("citations"):
                with st.expander("📚 Knowledge Base Sources"):
                    for c in msg["citations"]:
                        st.caption(f"• {c}")
            if msg.get("tool_results"):
                with st.expander("🔧 Ingredient Analysis Tools"):
                    for t in msg["tool_results"]:
                        st.caption(str(t))

# --------------------------------------------------------------------------
# Backend call helper
# --------------------------------------------------------------------------
def _call_backend(prompt: str) -> None:
    """Render user bubble, stream BackendService response, render citations."""
    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.write(prompt)

    with st.chat_message("assistant"):
        result: dict = {}
        try:
            svc = BackendService()
            req = BackendRequest(username=username, message=prompt)
            answer = st.write_stream(svc.build_stream(req, result))
        except Exception as e:
            st.error(f"⚠️ {e}")
            return

        citations = result.get("citations", [])
        rag_context = result.get("rag_context", [])
        tool_results = result.get("tool_results", [])

        if rag_context:
            _render_rag_expander(rag_context)
        if citations:
            with st.expander("📚 Knowledge Base Sources"):
                for c in citations:
                    st.caption(f"• {c}")
        if tool_results:
            with st.expander("🔧 Ingredient Analysis Tools"):
                for t in tool_results:
                    st.caption(str(t))

        st.session_state["messages"].append({
            "role": "assistant",
            "content": answer or result.get("message", ""),
            "citations": citations,
            "rag_context": rag_context,
            "tool_results": tool_results,
        })


# --------------------------------------------------------------------------
# Chat input — always rendered so it persists after pill selection
# --------------------------------------------------------------------------
# st.chat_input must be called every run; putting it in an elif branch
# means it never registers when a pending prompt is being handled.
prompt_typed = st.chat_input("Ask about ingredients, routines, or your skin type...")
pending = st.session_state.pop("_pending_prompt", None)

if pending:
    _call_backend(pending)
elif prompt_typed:
    _call_backend(prompt_typed)
