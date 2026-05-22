"""Admin dashboard — only accessible when username == 'admin'."""

import json

import streamlit as st
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.models import IntroductionPlan, Routine, User

st.title("Admin Dashboard")

engine = create_engine(settings.sqlite_url)


def _json_list(val) -> list:
    if not val:
        return []
    try:
        return json.loads(val)
    except Exception:
        return []


def _md_table(rows: list[dict]) -> str:
    if not rows:
        return "_No rows._"
    headers = list(rows[0].keys())
    sep = " | ".join("---" for _ in headers)
    header_row = " | ".join(f"**{h}**" for h in headers)
    data_rows = [" | ".join(str(r.get(h, "")) for h in headers) for r in rows]
    return "\n".join([header_row, sep] + data_rows)


with Session(engine) as session:
    users = session.query(User).order_by(User.id).all()

    rows = []
    for u in users:
        routines = session.query(Routine).filter_by(user_id=u.id).all()
        plan = session.query(IntroductionPlan).filter_by(user_id=u.id).first()
        plan_actives = _json_list(plan.actives_list) if plan else []

        rows.append(
            {
                "ID": u.id,
                "Username": u.username,
                "Skin Type": u.skin_type or "—",
                "Concerns": ", ".join(_json_list(u.skin_concerns)) or "—",
                "Shaving": (
                    "yes" if u.has_shaving_routine is True
                    else ("no" if u.has_shaving_routine is False else "—")
                ),
                "Medical Flags": ", ".join(_json_list(u.medical_flags)) or "—",
                "Onboarding": "✅" if u.onboarding_complete else "⏳",
                "Routines": ", ".join(r.name for r in routines) or "—",
                "Intro Plan": (
                    f"{plan.status} ({', '.join(plan_actives)})" if plan else "—"
                ),
            }
        )

st.subheader("Users")
st.markdown(_md_table(rows))

st.divider()
st.subheader("Raw SQL")
query = st.text_area("Query", value="SELECT * FROM users LIMIT 20", height=80)
if st.button("Run"):
    try:
        with engine.connect() as conn:
            result = conn.execute(text(query))
            cols = list(result.keys())
            data = [dict(zip(cols, row)) for row in result.fetchall()]
        st.markdown(_md_table(data))
    except Exception as exc:
        st.error(str(exc))
