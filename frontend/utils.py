"""Shared UI helpers for the Skincare Routine Builder frontend."""

import streamlit as st


def inject_css():
    """Inject custom CSS for chat bubbles, verdict badges, step cards.

    Only injects once per session — subsequent calls are no-ops.
    """
    if st.session_state.get("_css_injected"):
        return
    st.session_state["_css_injected"] = True
    st.html("""<style>
    /* User chat bubble — right aligned, dark green */
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
        flex-direction: row-reverse;
    }
    [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) [data-testid="stChatMessageContent"] {
        background-color: #2E3D2F;
        border-radius: 18px 18px 4px 18px;
        padding: 12px 16px;
        color: #E0E8E0;
    }
    /* Step card amber left border */
    .step-card {
        border-left: 4px solid #C4933F;
        padding-left: 12px;
    }
    </style>""")


def get_username_initials(username: str) -> str:
    """Return up-to-two uppercase initials from a username.

    For a multi-word name (e.g. "John Bravo") returns "JB".
    For a single word (e.g. "John") returns the first two characters "JO".
    """
    parts = username.strip().split()
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return username[:2].upper() if username else "??"


def render_sidebar_header(username: str):
    """Render avatar circle + username + BEGINNER TRACK label in the sidebar."""
    initials = get_username_initials(username)
    st.sidebar.html(f"""
    <div style="display:flex;align-items:center;gap:12px;padding:4px 0 16px 0;">
      <div style="width:40px;height:40px;border-radius:50%;background:#5A6E5C;
                  display:flex;align-items:center;justify-content:center;
                  color:white;font-weight:600;font-size:14px;flex-shrink:0;">{initials}</div>
      <div>
        <div style="color:#E0E8E0;font-weight:500;font-size:14px;">{username}</div>
        <div style="color:#9EAD9E;font-size:11px;letter-spacing:0.08em;text-transform:uppercase;">Beginner Track</div>
      </div>
    </div>
    """)
