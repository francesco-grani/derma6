"""Routine Viewer page — displays saved skincare routines as numbered step cards."""

import streamlit as st

from backend.db.profile_store import ProfileStore, ProfileStoreError

username = st.session_state.get("username", "guest")

st.title("Routine Viewer")
st.caption("Your saved skincare routines, step by step.")

CATEGORY_LABELS = {
    "cleanser": "CLEANSE",
    "toner": "BALANCE",
    "serum": "TREATMENT",
    "moisturiser": "MOISTURE",
    "moisturizer": "MOISTURE",
    "spf": "PROTECT",
    "sunscreen": "PROTECT",
}

STEP_DESCRIPTIONS = {
    "cleanser": "Remove dirt, oil, and impurities from the skin surface.",
    "toner": "Rebalance skin pH and prep for active ingredients.",
    "serum": "Concentrated treatment layer targeting specific concerns.",
    "niacinamide": "Minimise pores, even skin tone, and reduce redness.",
    "niacinamide serum": "Minimise pores, even skin tone, and reduce redness.",
    "vitamin c": "Antioxidant that brightens and protects against free radicals.",
    "vitamin c serum": "Antioxidant that brightens and protects against free radicals.",
    "retinol": "Accelerate cell turnover to reduce fine lines and improve texture.",
    "retinol serum": "Accelerate cell turnover to reduce fine lines and improve texture.",
    "hyaluronic acid": "Draw moisture into the skin and keep it hydrated.",
    "hyaluronic acid serum": "Draw moisture into the skin and keep it hydrated.",
    "moisturiser": "Lock in hydration and reinforce the skin barrier.",
    "moisturizer": "Lock in hydration and reinforce the skin barrier.",
    "spf": "Shield skin from UV damage — always the last morning step.",
    "sunscreen": "Shield skin from UV damage — always the last morning step.",
    "eye cream": "Targeted hydration and care for the delicate eye area.",
    "aha": "Chemical exfoliant to smooth skin texture and even tone.",
    "bha": "Oil-soluble exfoliant that clears pores and reduces congestion.",
    "exfoliant": "Slough away dead skin cells to reveal smoother skin.",
    "peptides": "Signal proteins that support collagen production and firmness.",
    "peptide serum": "Signal proteins that support collagen production and firmness.",
    "face oil": "Nourish and seal the skin barrier as a final step.",
    "benzoyl peroxide": "Antibacterial treatment to reduce acne-causing bacteria.",
    "salicylic acid": "Penetrate pores to dissolve debris and prevent breakouts.",
    "azelaic acid": "Reduce redness, even tone, and calm inflammatory acne.",
    "ceramides": "Replenish the skin barrier and prevent moisture loss.",
    "glycolic acid": "Resurface and brighten with this classic AHA exfoliant.",
    "lactic acid": "Gentle AHA that hydrates while exfoliating.",
    "zinc": "Soothe inflammation and regulate excess sebum production.",
}


def _get_description(ingredient: str) -> str:
    key = ingredient.strip().lower()
    if key in STEP_DESCRIPTIONS:
        return STEP_DESCRIPTIONS[key]
    for k, v in STEP_DESCRIPTIONS.items():
        if k in key or key in k:
            return v
    return "Apply evenly to face and neck."


def _routine_anchor(name: str) -> str:
    return name.lower().replace(" ", "-").replace("'", "")


# --------------------------------------------------------------------------
# Load store and routines
# --------------------------------------------------------------------------
store = ProfileStore()
try:
    routines = store.get_all_routines(username)
except ProfileStoreError:
    routines = []

if not routines:
    with st.container(horizontal_alignment="center"):
        st.space("large")
        st.markdown("### No routine saved yet")
        st.caption(
            "Ask the assistant to build a routine for you, then it will appear here."
        )
    st.stop()

# --------------------------------------------------------------------------
# Dialogs
# --------------------------------------------------------------------------
@st.dialog("Rename Routine")
def _rename_dialog(old_name: str) -> None:
    new_name = st.text_input("New name", value=old_name, max_chars=60)
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Save", type="primary", use_container_width=True):
            stripped = new_name.strip()
            if stripped and stripped != old_name:
                try:
                    store.rename_routine(username, old_name, stripped)
                except ProfileStoreError as e:
                    st.error(str(e))
                    return
            st.rerun()
    with c2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


@st.dialog("Delete Routine")
def _delete_dialog(name: str) -> None:
    st.warning(f"**'{name}'** will be permanently deleted. This cannot be undone.")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Delete", type="primary", use_container_width=True):
            try:
                store.delete_routine(username, name)
            except ProfileStoreError as e:
                st.error(str(e))
                return
            st.rerun()
    with c2:
        if st.button("Cancel", use_container_width=True):
            st.rerun()


# --------------------------------------------------------------------------
# Navigation cards
# --------------------------------------------------------------------------
CARDS_PER_ROW = 3
rows = [routines[i:i + CARDS_PER_ROW] for i in range(0, len(routines), CARDS_PER_ROW)]

for row in rows:
    cols = st.columns(CARDS_PER_ROW)
    for j, routine in enumerate(row):
        with cols[j]:
            anchor = _routine_anchor(routine.name)
            step_count = len(routine.steps)
            st.html(f"""
            <a href="#{anchor}" style="text-decoration:none;">
              <div style="background:#fff;border:1px solid #DDE5DD;border-radius:12px;
                          padding:14px 16px;cursor:pointer;transition:box-shadow .15s;">
                <div style="font-weight:600;color:#1C2520;font-size:14px;margin-bottom:4px;">
                  {routine.name}
                </div>
                <div style="color:#9EAD9E;font-size:12px;">{step_count} step{"s" if step_count != 1 else ""}</div>
              </div>
            </a>
            """)
            b1, b2 = st.columns(2)
            with b1:
                if st.button(
                    ":material/edit: Rename",
                    key=f"rename_{routine.name}",
                    use_container_width=True,
                ):
                    _rename_dialog(routine.name)
            with b2:
                if st.button(
                    ":material/delete: Delete",
                    key=f"delete_{routine.name}",
                    use_container_width=True,
                ):
                    _delete_dialog(routine.name)

st.divider()

# --------------------------------------------------------------------------
# Routine detail sections
# --------------------------------------------------------------------------
for routine in routines:
    if not routine.steps:
        continue

    st.subheader(routine.name)

    for i, step in enumerate(routine.steps, 1):
        ingredient = step.ingredient if hasattr(step, "ingredient") else str(step)
        product = step.product_name if hasattr(step, "product_name") else None
        display_name = ingredient.strip().capitalize()
        category = CATEGORY_LABELS.get(ingredient.strip().lower(), "STEP")
        description = _get_description(ingredient)

        product_html = (
            f'<div style="color:#7A9B7D;font-size:12px;margin-top:2px;">{product}</div>'
            if product
            else ""
        )
        st.html(f"""
        <div style="background:#fff;border-radius:12px;padding:16px 20px;margin:8px 0;
                    border-left:4px solid #C4933F;display:flex;align-items:flex-start;gap:16px;">
          <div style="min-width:32px;height:32px;border-radius:50%;background:#2E3D2F;
                      display:flex;align-items:center;justify-content:center;
                      color:white;font-weight:600;font-size:14px;flex-shrink:0;">{i}</div>
          <div style="flex:1;">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <span style="color:#1C2520;font-weight:600;font-size:15px;">{display_name}</span>
              <span style="color:#9EAD9E;font-size:11px;letter-spacing:0.08em;">{category}</span>
            </div>
            <div style="color:#4A5748;font-size:13px;margin-top:4px;">{description}</div>
            {product_html}
          </div>
        </div>
        """)

    if st.button(
        ":material/auto_fix_high: Enhance this routine",
        key=f"enhance_{routine.name}",
    ):
        steps_str = " → ".join(
            s.ingredient.strip().capitalize() for s in routine.steps
        )
        st.session_state["_pending_prompt"] = (
            f"I want to enhance my '{routine.name}'. "
            f"Current steps: {steps_str}. "
            f"Ask me one question at a time about what I'd like to improve — "
            f"for example adding actives, adjusting steps, or filling gaps. "
            f"Once we agree on the final version, save it with the name '{routine.name}' "
            f"using save_routine_tool so it replaces the current one."
        )
        st.switch_page("app_pages/chat.py")

    st.markdown("")
