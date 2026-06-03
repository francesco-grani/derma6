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

# chromadb imports opentelemetry's gRPC exporter at startup; that exporter contains
# old-style protobuf descriptors incompatible with protobuf 5+ (used by streamlit).
# Pre-populate sys.modules with mocks so the import short-circuits before any proto
# code runs.  No telemetry is sent — that's fine for Streamlit Cloud deployment.
from unittest.mock import MagicMock as _Mock
for _m in [
    "opentelemetry.exporter.otlp.proto.grpc",
    "opentelemetry.exporter.otlp.proto.grpc.exporter",
    "opentelemetry.exporter.otlp.proto.grpc.trace_exporter",
]:
    sys.modules.setdefault(_m, _Mock())
del _m, _Mock

# Ensure project root is on sys.path so frontend.* and backend.* are importable
# regardless of which directory Streamlit adds when executing this file.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import streamlit as st

# Bridge Streamlit secrets → os.environ before any backend import.
# pydantic-settings reads os.environ at import time, so this must run first.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, str):
            os.environ.setdefault(_k.upper(), _v)
except Exception:
    pass  # running locally with .env file

from backend.logging_config import init_langsmith, log_new_session, setup_logging
from frontend.utils import inject_css, render_sidebar_header, render_sidebar_logo

setup_logging()
init_langsmith()
logger = logging.getLogger(__name__)


@st.cache_resource(show_spinner="Indexing knowledge base…")
def _ensure_kb_indexed() -> None:
    """Index the KB into ChromaDB if the collection is empty.

    Runs once per server process via cache_resource. On Streamlit Cloud
    the filesystem is ephemeral, so the collection is always empty on cold start.
    """
    import chromadb
    from backend.config import settings

    client = chromadb.PersistentClient(path=settings.chroma_persist_dir)
    try:
        if client.get_collection("skincare_kb").count() > 0:
            return
    except Exception:
        pass
    from scripts.index_kb import main as _index
    _index()


_ensure_kb_indexed()

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
            ' style="width:300px;display:block;margin:0 auto 4px auto;" />'
            '<p style="text-align:center;color:#aaa;font-size:1.1rem;margin:0;">'
            "Skincare advice built for guys who are ready to get it right."
            "</p>"
        )
    else:
        st.title("Derma6")
        st.html(
            '<p style="text-align:center;color:#aaa;font-size:1.1rem;margin:0;">'
            "Skincare advice built for guys who are ready to get it right."
            "</p>"
        )
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

# 6. Download Plan button → dialog offering HTML or PDF
from backend.db.chat_history import serialise_history
from frontend.export import generate_export_html, generate_export_pdf

history_data = serialise_history(username)


@st.dialog("Download Skincare Plan")
def _download_dialog() -> None:
    fmt = st.radio("Format", ["HTML", "PDF"], horizontal=True)
    if st.button("Generate", type="primary"):
        if fmt == "HTML":
            data = generate_export_html(username)
            st.download_button(
                "⬇ Save as HTML",
                data=data,
                file_name=f"{username}_skincare_plan.html",
                mime="text/html",
            )
        else:
            try:
                with st.spinner("Generating PDF…"):
                    data = generate_export_pdf(username)
                st.download_button(
                    "⬇ Save as PDF",
                    data=data,
                    file_name=f"{username}_skincare_plan.pdf",
                    mime="application/pdf",
                )
            except RuntimeError as e:
                st.error(str(e))


if history_data:
    if st.sidebar.button("⬇ Download Plan"):
        _download_dialog()
else:
    st.sidebar.button("⬇ Download Plan", disabled=True)

page.run()
