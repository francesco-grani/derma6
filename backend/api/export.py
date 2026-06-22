"""Export routes: GET /api/me/export?format=html|pdf"""

import html as html_lib

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from backend.auth import get_current_user

from backend.db.chat_history import serialise_history
from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.db.session_store import SessionStore, SessionStoreError
from backend.schemas import RoutineSchema

router = APIRouter(prefix="/api/me", tags=["export"])

# ── Step descriptions and category labels (ported from AE.2.5 frontend/export.py) ─

_STEP_DESCRIPTIONS: dict[str, str] = {
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
    "face oil": "Nourish and seal the skin barrier as a final step.",
    "benzoyl peroxide": "Antibacterial treatment to reduce acne-causing bacteria.",
    "salicylic acid": "Penetrate pores to dissolve debris and prevent breakouts.",
    "azelaic acid": "Reduce redness, even tone, and calm inflammatory acne.",
    "ceramides": "Replenish the skin barrier and prevent moisture loss.",
    "glycolic acid": "Resurface and brighten with this classic AHA exfoliant.",
    "lactic acid": "Gentle AHA that hydrates while exfoliating.",
    "zinc": "Soothe inflammation and regulate excess sebum production.",
}

_CATEGORY_LABELS: dict[str, str] = {
    "cleanser": "CLEANSE", "toner": "BALANCE", "serum": "TREATMENT",
    "moisturiser": "MOISTURE", "moisturizer": "MOISTURE",
    "spf": "PROTECT", "sunscreen": "PROTECT",
}


def _desc(ingredient: str) -> str:
    k = ingredient.strip().lower()
    if k in _STEP_DESCRIPTIONS:
        return _STEP_DESCRIPTIONS[k]
    for key, val in _STEP_DESCRIPTIONS.items():
        if key in k or k in key:
            return val
    return "Apply evenly to face and neck."


def _e(text: str) -> str:
    return html_lib.escape(str(text))


# ── HTML generation ───────────────────────────────────────────────────────────

def generate_export_html(username: str) -> str:  # noqa: C901
    from datetime import datetime, timezone

    store = ProfileStore()
    try:
        profile = store.get_profile(username)
    except ProfileStoreError:
        profile = None

    try:
        routines: list[RoutineSchema] = store.get_all_routines(username)
    except ProfileStoreError:
        routines = []

    try:
        sessions_meta = SessionStore().get_sessions(username)
    except SessionStoreError:
        sessions_meta = []
    chat_sessions = [
        (s, serialise_history(s["session_id"]))
        for s in sessions_meta
    ]
    generated_at = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")

    css = """
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { background: #3E4D3F; color: #E0E8E0;
           font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
           font-size: 15px; line-height: 1.6; }
    a { color: #7A9B7D; text-decoration: none; }
    .page { max-width: 860px; margin: 0 auto; padding: 40px 24px 80px; }
    .header { background: #2E3D2F; border-radius: 16px; padding: 32px 36px;
              margin-bottom: 40px; display: flex; align-items: center; gap: 20px; }
    .avatar { width: 56px; height: 56px; border-radius: 50%; background: #7A9B7D;
              display: flex; align-items: center; justify-content: center;
              font-size: 22px; font-weight: 700; color: #1C2520; flex-shrink: 0; }
    .header-text h1 { font-size: 24px; font-weight: 700; color: #E0E8E0; }
    .header-text p  { font-size: 13px; color: #9EAD9E; margin-top: 4px; }
    .index { background: #2E3D2F; border-radius: 12px; padding: 24px 28px; margin-bottom: 40px; }
    .index h2 { font-size: 14px; font-weight: 600; color: #9EAD9E;
                letter-spacing: .08em; text-transform: uppercase; margin-bottom: 12px; }
    .index ol { padding-left: 20px; }
    .index li { margin: 6px 0; }
    .section { margin-bottom: 56px; }
    .section-title { font-size: 20px; font-weight: 700; color: #E0E8E0;
                     padding-bottom: 10px; border-bottom: 2px solid #4B5A4C; margin-bottom: 24px; }
    .profile-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
    .profile-card { background: #2E3D2F; border-radius: 12px; padding: 18px 20px; }
    .profile-label { font-size: 11px; font-weight: 600; color: #9EAD9E;
                     letter-spacing: .08em; text-transform: uppercase; margin-bottom: 6px; }
    .profile-value { font-size: 15px; font-weight: 500; color: #E0E8E0; }
    .badge { display: inline-block; background: #4B5A4C; border-radius: 20px;
             padding: 3px 10px; font-size: 13px; margin: 3px 3px 3px 0; color: #E0E8E0; }
    .badge-medical { background: #5A3E3E; color: #F0B8B8; }
    .routine-block { margin-bottom: 36px; }
    .routine-name { font-size: 17px; font-weight: 600; color: #E0E8E0; margin-bottom: 14px; }
    .step-card { background: #fff; border-radius: 12px; padding: 16px 20px; margin: 8px 0;
                 border-left: 4px solid #C4933F; display: flex; align-items: flex-start; gap: 16px; }
    .step-num { min-width: 32px; height: 32px; border-radius: 50%; background: #2E3D2F;
                display: flex; align-items: center; justify-content: center;
                color: #fff; font-weight: 600; font-size: 14px; flex-shrink: 0; }
    .step-body { flex: 1; }
    .step-header { display: flex; justify-content: space-between; align-items: center; }
    .step-ingredient { color: #1C2520; font-weight: 600; font-size: 15px; }
    .step-category { color: #9EAD9E; font-size: 11px; letter-spacing: .08em; }
    .step-desc { color: #4A5748; font-size: 13px; margin-top: 4px; }
    .chat-list { display: flex; flex-direction: column; gap: 16px; }
    .bubble-row { display: flex; }
    .bubble-row.user { justify-content: flex-end; }
    .bubble { max-width: 72%; border-radius: 18px; padding: 12px 16px;
              font-size: 14px; line-height: 1.55; white-space: pre-wrap; word-break: break-word; }
    .bubble.user { background: #7A9B7D; color: #1C2520; border-bottom-right-radius: 4px; }
    .bubble.ai { background: #fff; color: #1C2520; border-bottom-left-radius: 4px;
                 box-shadow: 0 1px 4px rgba(0,0,0,.12); }
    .role-label { font-size: 11px; font-weight: 600; letter-spacing: .06em;
                  margin-bottom: 4px; text-transform: uppercase; }
    .role-label.user { text-align: right; color: #9EAD9E; }
    .role-label.ai   { color: #9EAD9E; }
    .footer { text-align: center; color: #9EAD9E; font-size: 12px;
              margin-top: 60px; padding-top: 24px; border-top: 1px solid #4B5A4C; }
    .session-block { margin-bottom: 40px; }
    .session-sep { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
    .session-sep-line { flex: 1; height: 1px; background: #4B5A4C; }
    .session-sep-label { font-size: 11px; font-weight: 600; color: #9EAD9E;
                         letter-spacing: .08em; text-transform: uppercase; white-space: nowrap; }
    @media print { body { background: #fff; color: #1C2520; }
                   .header, .index, .profile-card { background: #f4f6f4; } }
    """

    initials = "".join(w[0].upper() for w in username.split()[:2]) or username[0].upper()

    header = f"""<div class="header">
      <div class="avatar">{_e(initials)}</div>
      <div class="header-text"><h1>Skincare Plan — {_e(username)}</h1>
        <p>Generated {_e(generated_at)}</p></div></div>"""

    index = """<div class="index"><h2>Contents</h2><ol>
      <li><a href="#profile">Profile</a></li>
      <li><a href="#my-routines">My Routines</a></li>
      <li><a href="#my-chat">My Chat</a></li></ol></div>"""

    # Profile section
    def _field(label: str, value_html: str) -> str:
        return f'<div class="profile-card"><div class="profile-label">{_e(label)}</div><div class="profile-value">{value_html}</div></div>'

    if profile:
        skin_type_val = _e(profile.skin_type.capitalize()) if profile.skin_type else "—"
        concerns_val = "".join(f'<span class="badge">{_e(c)}</span>' for c in profile.skin_concerns) if profile.skin_concerns else "—"
        shaving_val = "Yes" if profile.has_shaving_routine is True else ("No" if profile.has_shaving_routine is False else "—")
        flags_val = "".join(f'<span class="badge badge-medical">{_e(f)}</span>' for f in profile.medical_flags) if profile.medical_flags else "None"
        onboarding_val = "✅ Complete" if profile.onboarding_complete else "⏳ In progress"
        profile_html = f'<div class="profile-grid">{_field("Skin Type", skin_type_val)}{_field("Skin Concerns", concerns_val)}{_field("Shaving Routine", shaving_val)}{_field("Medical Flags", flags_val)}{_field("Onboarding", onboarding_val)}</div>'
    else:
        profile_html = "<p>Profile not found.</p>"

    profile_section = f'<div class="section" id="profile"><div class="section-title">Profile</div>{profile_html}</div>'

    # Routines section
    if routines:
        blocks = []
        for routine in routines:
            steps_html = ""
            for i, step in enumerate(routine.steps, 1):
                ing = step.ingredient
                display = _e(ing.strip().capitalize())
                cat = _e(_CATEGORY_LABELS.get(ing.strip().lower(), "STEP"))
                desc = _e(_desc(ing))
                steps_html += f'<div class="step-card"><div class="step-num">{i}</div><div class="step-body"><div class="step-header"><span class="step-ingredient">{display}</span><span class="step-category">{cat}</span></div><div class="step-desc">{desc}</div></div></div>'
            blocks.append(f'<div class="routine-block"><div class="routine-name">{_e(routine.name)}</div>{steps_html}</div>')
        routines_html = "".join(blocks)
    else:
        routines_html = "<p>No routines saved yet.</p>"

    routines_section = f'<div class="section" id="my-routines"><div class="section-title">My Routines</div>{routines_html}</div>'

    # Chat section — one block per session
    populated = [(s, msgs) for s, msgs in chat_sessions if msgs]
    if populated:
        session_blocks = []
        for i, (s, msgs) in enumerate(populated):
            title = s.get("title") or f"Session {i + 1}"
            date_str = s.get("updated_at", "")[:10]
            sep_label = f"{_e(title)}  ·  {_e(date_str)}" if date_str else _e(title)
            sep = (f'<div class="session-sep">'
                   f'<div class="session-sep-line"></div>'
                   f'<div class="session-sep-label">{sep_label}</div>'
                   f'<div class="session-sep-line"></div></div>')
            bubbles = []
            for msg in msgs:
                role = "user" if msg["role"] == "human" else "ai"
                label = username if role == "user" else "Assistant"
                content = _e(msg.get("content", ""))
                bubbles.append(
                    f'<div><div class="role-label {role}">{_e(label)}</div>'
                    f'<div class="bubble-row {role}"><div class="bubble {role}">{content}</div></div></div>'
                )
            session_blocks.append(
                f'<div class="session-block">{sep}<div class="chat-list">{"".join(bubbles)}</div></div>'
            )
        chat_html = "".join(session_blocks)
    else:
        chat_html = "<p>No conversation yet.</p>"

    chat_section = f'<div class="section" id="my-chat"><div class="section-title">My Chat</div>{chat_html}</div>'

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Skincare Plan — {_e(username)}</title>
  <style>{css}</style>
</head>
<body>
  <div class="page">
    {header}{index}{profile_section}{routines_section}{chat_section}
    <div class="footer">Derma6 · AI-generated plan · Not medical advice</div>
  </div>
</body>
</html>"""


def generate_export_pdf(username: str) -> bytes:  # noqa: C901
    """Generate a PDF export using xhtml2pdf (pure Python, no system libs)."""
    try:
        import io
        from xhtml2pdf import pisa
    except ImportError as exc:
        raise RuntimeError("PDF export requires xhtml2pdf (pip install xhtml2pdf).") from exc

    from datetime import datetime, timezone

    store = ProfileStore()
    try:
        profile = store.get_profile(username)
    except ProfileStoreError:
        profile = None

    try:
        routines: list[RoutineSchema] = store.get_all_routines(username)
    except ProfileStoreError:
        routines = []

    try:
        sessions_meta = SessionStore().get_sessions(username)
    except SessionStoreError:
        sessions_meta = []
    chat_sessions = [(s, serialise_history(s["session_id"])) for s in sessions_meta]

    generated_at = datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC")
    initials = "".join(w[0].upper() for w in username.split()[:2]) or username[0].upper()

    css = """
    @page { size: A4; margin: 2cm; }
    body { font-family: Helvetica, Arial, sans-serif; font-size: 11pt; color: #1C2520; }
    h1 { font-size: 18pt; color: #2E3D2F; margin: 0 0 4pt 0; }
    h2 { font-size: 13pt; color: #2E3D2F; border-bottom: 1pt solid #ccc;
         padding-bottom: 4pt; margin: 20pt 0 10pt 0; }
    h3 { font-size: 11pt; color: #2E3D2F; margin: 12pt 0 6pt 0; }
    p  { margin: 0 0 8pt 0; color: #4A5748; font-size: 10pt; }
    .header-box { background-color: #2E3D2F; padding: 16pt; margin-bottom: 16pt; }
    .header-box h1 { color: #E0E8E0; }
    .header-box p  { color: #9EAD9E; margin: 0; font-size: 9pt; }
    .avatar { display: inline-block; background-color: #7A9B7D; color: #1C2520;
              font-weight: bold; font-size: 14pt; padding: 6pt 10pt; margin-right: 10pt; }
    table.profile { width: 100%; border-collapse: collapse; margin-bottom: 12pt; }
    table.profile td { width: 50%; padding: 8pt; background-color: #f4f6f4;
                       vertical-align: top; border: 2pt solid #fff; }
    .label { font-size: 8pt; font-weight: bold; color: #5A6A5A;
             text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 3pt; }
    .value { font-size: 11pt; color: #1C2520; }
    table.steps { width: 100%; border-collapse: collapse; margin: 6pt 0 12pt 0; }
    table.steps td { padding: 8pt; border-bottom: 1pt solid #eee; vertical-align: top; }
    .step-num { width: 28pt; font-weight: bold; color: #C4933F; font-size: 13pt; }
    .step-name { font-weight: bold; font-size: 11pt; color: #1C2520; }
    .step-cat  { font-size: 8pt; color: #9EAD9E; text-transform: uppercase;
                 letter-spacing: 0.06em; }
    .step-desc { font-size: 9pt; color: #4A5748; margin-top: 2pt; }
    .session-title { font-size: 10pt; font-weight: bold; color: #5A6A5A;
                     text-transform: uppercase; letter-spacing: 0.06em;
                     border-top: 1pt solid #ccc; padding-top: 8pt; margin: 16pt 0 8pt 0; }
    table.chat { width: 100%; border-collapse: collapse; margin-bottom: 8pt; }
    table.chat td { padding: 6pt 8pt; font-size: 10pt; vertical-align: top; }
    .bubble-user { background-color: #dde8dd; color: #1C2520; border-radius: 6pt; }
    .bubble-ai   { background-color: #f4f6f4; color: #1C2520; border-radius: 6pt;
                   border: 1pt solid #ddd; }
    .role-lbl { font-size: 8pt; font-weight: bold; color: #9EAD9E;
                text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 3pt; }
    .footer { font-size: 8pt; color: #9EAD9E; text-align: center;
              border-top: 1pt solid #ccc; padding-top: 8pt; margin-top: 20pt; }
    """

    # Profile section
    if profile:
        skin_type = _e(profile.skin_type.capitalize()) if profile.skin_type else "—"
        concerns = ", ".join(_e(c) for c in profile.skin_concerns) if profile.skin_concerns else "—"
        shaving = "Yes" if profile.has_shaving_routine is True else ("No" if profile.has_shaving_routine is False else "—")
        flags = ", ".join(_e(f) for f in profile.medical_flags) if profile.medical_flags else "None"
        onboarding = "Complete" if profile.onboarding_complete else "In progress"
        profile_html = f"""<table class="profile">
          <tr>
            <td><div class="label">Skin Type</div><div class="value">{skin_type}</div></td>
            <td><div class="label">Skin Concerns</div><div class="value">{concerns}</div></td>
          </tr>
          <tr>
            <td><div class="label">Shaving Routine</div><div class="value">{shaving}</div></td>
            <td><div class="label">Medical Flags</div><div class="value">{flags}</div></td>
          </tr>
          <tr>
            <td><div class="label">Onboarding</div><div class="value">{onboarding}</div></td>
            <td></td>
          </tr>
        </table>"""
    else:
        profile_html = "<p>Profile not found.</p>"

    # Routines section
    if routines:
        routine_blocks = []
        for routine in routines:
            rows = ""
            for i, step in enumerate(routine.steps, 1):
                ing = step.ingredient
                rows += (
                    f'<tr><td class="step-num">{i}</td>'
                    f'<td><div class="step-name">{_e(ing.strip().capitalize())}</div>'
                    f'<div class="step-cat">{_e(_CATEGORY_LABELS.get(ing.strip().lower(), "STEP"))}</div>'
                    f'<div class="step-desc">{_e(_desc(ing))}</div></td></tr>'
                )
            routine_blocks.append(
                f'<h3>{_e(routine.name)}</h3><table class="steps">{rows}</table>'
            )
        routines_html = "".join(routine_blocks)
    else:
        routines_html = "<p>No routines saved yet.</p>"

    # Chat section
    populated = [(s, msgs) for s, msgs in chat_sessions if msgs]
    if populated:
        chat_parts = []
        for i, (s, msgs) in enumerate(populated):
            title = s.get("title") or f"Session {i + 1}"
            date_str = s.get("updated_at", "")[:10]
            sep_label = f"{_e(title)}  ·  {_e(date_str)}" if date_str else _e(title)
            rows = ""
            for msg in msgs:
                is_user = msg["role"] == "human"
                label = _e(username) if is_user else "Assistant"
                css_cls = "bubble-user" if is_user else "bubble-ai"
                content = _e(msg.get("content", ""))
                align = "right" if is_user else "left"
                rows += (
                    f'<tr><td style="text-align:{align}">'
                    f'<div class="role-lbl">{label}</div>'
                    f'<div class="{css_cls}">{content}</div></td></tr>'
                )
            chat_parts.append(
                f'<div class="session-title">{sep_label}</div>'
                f'<table class="chat">{rows}</table>'
            )
        chat_html = "".join(chat_parts)
    else:
        chat_html = "<p>No conversation yet.</p>"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><style>{css}</style></head>
<body>
  <div class="header-box">
    <span class="avatar">{_e(initials)}</span>
    <h1>Skincare Plan — {_e(username)}</h1>
    <p>Generated {_e(generated_at)}</p>
  </div>
  <h2>Profile</h2>{profile_html}
  <h2>My Routines</h2>{routines_html}
  <h2>My Chat</h2>{chat_html}
  <div class="footer">Derma6 · AI-generated plan · Not medical advice</div>
</body></html>"""

    buf = io.BytesIO()
    result = pisa.CreatePDF(html, dest=buf)
    if result.err:
        raise RuntimeError(f"PDF generation failed (xhtml2pdf error {result.err}).")
    return buf.getvalue()


# ── FastAPI routes ────────────────────────────────────────────────────────────

@router.get("/export")
def export(format: str = Query(default="html", pattern="^(html|pdf)$"), username: str = Depends(get_current_user)):
    if format == "pdf":
        try:
            pdf_bytes = generate_export_pdf(username)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{username}_skincare_plan.pdf"'},
        )
    html_content = generate_export_html(username)
    return HTMLResponse(
        content=html_content,
        headers={"Content-Disposition": f'attachment; filename="{username}_skincare_plan.html"'},
    )
