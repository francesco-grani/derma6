"""Profile page — displays the user's skin profile and introduction plan."""

import streamlit as st

from backend.db.profile_store import ProfileStore, ProfileStoreError

username = st.session_state.get("username", "guest")

st.title("My Profile")
st.caption("Your skin profile and introduction plan.")

try:
    store = ProfileStore()
    profile = store.get_profile(username)
except ProfileStoreError:
    st.info("No profile found yet. Start a conversation to build your profile.")
    st.stop()

# --------------------------------------------------------------------------
# Profile card
# --------------------------------------------------------------------------
with st.container(border=True):
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Skin Type", profile.skin_type or "Not assessed")
        shaving = "Yes" if profile.has_shaving_routine else "No"
        st.metric("Has Shaving Routine", shaving)
    with col2:
        st.markdown("**Skin Concerns**")
        if profile.skin_concerns:
            st.write(" ".join([f"`{c}`" for c in profile.skin_concerns]))
        else:
            st.caption("None recorded yet.")
        st.markdown("**Onboarding**")
        st.write("Complete" if profile.onboarding_complete else "In progress")

# --------------------------------------------------------------------------
# Medical flags
# --------------------------------------------------------------------------
if profile.medical_flags:
    st.warning(
        f"Medical flags: {', '.join(profile.medical_flags)}. "
        "Consult a dermatologist before introducing new actives."
    )

# --------------------------------------------------------------------------
# Introduction Plan
# --------------------------------------------------------------------------
st.divider()
st.subheader("Introduction Plan")
try:
    plan = store.get_introduction_plan(username)
    if plan and plan.weeks:
        for week in plan.weeks:
            week_label = getattr(week, "week", "?")
            active = getattr(week, "active", "")
            notes = getattr(week, "notes", "")
            icon = "🟡" if plan.status == "active" else "✅"
            with st.container(border=True):
                st.markdown(f"{icon} **Week {week_label}** — {active}")
                if notes:
                    st.caption(notes)
    else:
        st.info("No introduction plan yet. Ask the assistant to create one for you.")
except Exception:
    st.info("No introduction plan yet.")
