"""Shared UI helpers for the Derma6 frontend."""

from pathlib import Path

import streamlit as st

_ASSETS_DIR = Path(__file__).parent / "assets"


def inject_css():
    """Inject custom CSS for chat bubbles, verdict badges, step cards.

    Only injects once per session — subsequent calls are no-ops.
    """
    if st.session_state.get("_css_injected"):
        return
    st.session_state["_css_injected"] = True
    st.html("""<style>
    /* Narrow the sidebar — belt-and-suspenders with !important */
    [data-testid="stSidebar"] {
        min-width: 210px !important;
        max-width: 210px !important;
        width: 210px !important;
    }
    [data-testid="stSidebar"] > div:first-child {
        min-width: 210px !important;
        width: 210px !important;
    }
    [data-testid="stSidebarResizeHandle"] { display: none !important; }
    /* Push sidebar profile+download to the very bottom */
    section[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
        display: flex !important;
        flex-direction: column !important;
        min-height: 100vh;
    }
    section[data-testid="stSidebar"] :has(> hr) {
        margin-top: auto !important;
    }
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


def render_sidebar_logo():
    """Render the Derma6 logo at the top of the sidebar (base64, no Streamlit chrome)."""
    import base64
    logo_path = _ASSETS_DIR / "Derma6_logo.png"
    if logo_path.exists():
        logo_b64 = base64.b64encode(logo_path.read_bytes()).decode()
        st.sidebar.html(
            f'<img src="data:image/png;base64,{logo_b64}"'
            ' style="width:160px;display:block;margin:0 0 4px 0;" />'
        )


def render_sidebar_header(username: str):
    """Render avatar circle + username in the sidebar."""
    initials = get_username_initials(username)
    st.sidebar.html(f"""
    <div style="display:flex;align-items:center;gap:10px;padding:4px 0 8px 0;">
      <div style="width:36px;height:36px;border-radius:50%;background:#5A6E5C;
                  display:flex;align-items:center;justify-content:center;
                  color:white;font-weight:600;font-size:13px;flex-shrink:0;">{initials}</div>
      <div style="color:#E0E8E0;font-weight:500;font-size:14px;">{username}</div>
    </div>
    """)
