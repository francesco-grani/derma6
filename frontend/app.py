"""Entry point for the Derma6 Streamlit app.

Handles:
- Page config (must be the very first Streamlit call)
- CSS injection
- Auth gate (username prompt before any navigation)
- st.navigation() routing once the user is authenticated
- Sidebar header and Download Plan PDF button
"""

import base64
import logging
import os
import sys
from pathlib import Path

from PIL import Image as _Image

# Ensure project root is on sys.path so frontend.* and backend.* are importable
# regardless of which directory Streamlit adds when executing this file.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st

from backend.logging_config import init_langsmith, log_new_session, setup_logging
from frontend.utils import inject_css, render_sidebar_header, render_sidebar_logo

setup_logging()
init_langsmith()
logger = logging.getLogger(__name__)

_favicon = _Image.open(Path(__file__).parent / "assets" / "Derma6_favicon.png")
st.set_page_config(
    page_title="Derma6",
    page_icon=_favicon,
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_css()

# --------------------------------------------------------------------------
# Auth gate — block navigation until username is set
# --------------------------------------------------------------------------
if "username" not in st.session_state:
    st.html("""<style>
        [data-testid='stSidebar'] { display: none; }
        [data-testid='InputInstructions'] { display: none !important; }
        [data-testid='stTextInputRootElement'],
        [data-testid='stWidgetLabel'] {
            width: 250px !important;
            max-width: 250px !important;
            margin: 0 auto !important;
        }
        [data-testid='stVerticalBlock'] { align-items: center; }
    </style>""")
    st.space("large")
    _logo_path = Path(__file__).parent / "assets" / "Derma6_logo.png"
    if _logo_path.exists():
        _logo_b64 = base64.b64encode(_logo_path.read_bytes()).decode()
        st.html(
            f'<img src="data:image/png;base64,{_logo_b64}"'
            ' style="width:300px;display:block;margin:0 auto 8px auto;" />'
        )
    else:
        st.title("Derma6")
    st.space("small")
    with st.form("login_form", border=False):
        username = st.text_input(
            "Enter your name to get started",
            placeholder="e.g. John",
            max_chars=50,
            label_visibility="visible",
        )
        submitted = st.form_submit_button("Start →", type="primary")
    if submitted and username.strip():
        from backend.db.profile_store import ProfileStore

        store = ProfileStore()
        store.get_or_create_user(username.strip())
        st.session_state["username"] = username.strip()
        st.session_state["messages"] = []
        log_new_session(username.strip())
        st.rerun()
    st.stop()

# --------------------------------------------------------------------------
# Authenticated — set up sidebar and navigation
# --------------------------------------------------------------------------
username = st.session_state["username"]

# 1. Logo
render_sidebar_logo()

# 2. Small buffer
st.sidebar.write("")

# 3. Navigation links (position="hidden" lets us control placement)
pages = [
    st.Page("app_pages/chat.py", title="Assistant Chat", icon=":material/chat:"),
    st.Page("app_pages/profile.py", title="My Profile", icon=":material/person:"),
    st.Page("app_pages/routine_viewer.py", title="Routine Viewer", icon=":material/list:"),
]
if username == "admin":
    pages.append(st.Page("app_pages/admin.py", title="Admin", icon=":material/admin_panel_settings:"))

page = st.navigation(pages, position="hidden")

with st.sidebar:
    for p in pages:
        st.page_link(p)

# 4. Push profile + download to bottom
st.sidebar.divider()

# 5. Profile row (avatar + username, no Beginner Track)
render_sidebar_header(username)

# 6. Download Plan button
from backend.db.chat_history import serialise_history
from frontend.export import generate_export_html

history_data = serialise_history(username)
if history_data:
    st.sidebar.download_button(
        "⬇ Download Plan",
        data=generate_export_html(username),
        file_name=f"{username}_skincare_plan.html",
        mime="text/html",
    )
else:
    st.sidebar.download_button(
        "⬇ Download Plan",
        data="",
        file_name=f"{username}_skincare_plan.html",
        mime="text/html",
        disabled=True,
    )

page.run()
