"""
contact_gui/theme.py
────────────────────
Look and feel, modelled on late-70s pocket cameras (Rollei A110, Minox 35 GT):
a matte black body, white lettering, brushed-aluminium greys and a few small
signal-orange details — the shutter button, never whole surfaces.

Typography is film-edge style: monospace for anything that names a frame or
counts, the system sans for everything else. Only system fonts are used, so the
app makes no network requests for assets.
"""

from nicegui import ui

ORANGE = "#f5961d"       # shutter-button orange, leaning yellow
ORANGE_DEEP = "#b85e00"  # the same accent, dark enough to read on a light page
BODY = "#161616"         # matte black
PANEL = "#1e1e1e"        # fields and cards: a shade up from the body
EDGE = "#333333"         # borders
LETTERING = "#f1f0ec"    # engraved white
ALUMINIUM = "#a9a8a3"    # secondary text

_MONO = "ui-monospace, 'SF Mono', 'JetBrains Mono', Menlo, Consolas, monospace"
_SANS = "system-ui, -apple-system, 'Segoe UI', sans-serif"

_CSS = f"""
body {{ font-family: {_SANS}; background: #ecebe8; color: {BODY}; }}
body.body--dark {{ background: {BODY}; color: {LETTERING}; }}
/* ui.colors sets the variable inline on body, hence !important */
body.body--light {{ --q-primary: {ORANGE_DEEP} !important; }}
body.body--light .bg-primary.text-white, body.body--light .q-btn.bg-primary {{ color: #fff !important; }}

/* Film-edge lettering: frame names, counters, the wordmark */
.mono {{ font-family: {_MONO}; letter-spacing: 0.02em; }}
.wordmark {{ font-family: {_MONO}; font-weight: 700; letter-spacing: 0.08em; }}
/* The one orange button on the camera */
.wordmark::after {{
    content: ""; display: inline-block; width: 0.5em; height: 0.5em; margin-left: 0.35em;
    border-radius: 50%; background: {ORANGE};
}}

/* Header: the camera's top plate */
.q-header {{ background: #0e0e0e; border-bottom: 1px solid {EDGE}; }}
.q-tab__label {{ font-family: {_MONO}; font-size: 0.8rem; letter-spacing: 0.06em; }}
.q-tab {{ color: {ALUMINIUM}; }}
.q-tab--active {{ color: {ORANGE}; }}
.q-tab-panels {{ background: transparent; }}
.q-header .subtitle {{ color: {ALUMINIUM}; }}
body.body--light .q-header {{
    background: #f7f6f3; color: {BODY} !important; border-bottom-color: #d5d4cf;
}}
body.body--light .q-tab {{ color: #6b6a66; }}
body.body--light .q-tab--active {{ color: {ORANGE_DEEP}; }}
body.body--light .q-header .subtitle {{ color: #6b6a66; }}

/* Controls: square-ish corners, no shouting caps, no drop shadows */
.q-btn {{ border-radius: 3px; font-weight: 600; letter-spacing: 0.01em; }}
/* Orange is light, so anything filled with it carries black lettering */
.bg-primary.text-white, .q-btn.bg-primary {{ color: #141414 !important; }}
.q-field--outlined .q-field__control {{ border-radius: 3px; background: #fff; }}
.q-card {{ border-radius: 4px; box-shadow: none; border: 1px solid #d5d4cf; }}
.q-chip {{ border-radius: 3px; }}
body.body--dark .q-field--outlined .q-field__control {{ background: {PANEL}; }}
body.body--dark .q-field--outlined .q-field__control:before {{ border-color: {EDGE}; }}
body.body--dark .q-card {{ background: {PANEL}; border-color: {EDGE}; }}
body.body--dark .q-menu {{ background: {PANEL}; }}
/* Quasar's mid greys are too dim on a black page */
body.body--dark .text-grey-6, body.body--dark .text-grey-7,
body.body--dark .text-grey-8 {{ color: {ALUMINIUM} !important; }}

/* A frame, as on a contact sheet: black surround */
.frame {{ background: #0a0a0a; border-radius: 2px; }}
.frame-current {{ outline: 3px solid {ORANGE}; outline-offset: 2px; }}
/* selected alongside the current frame: the same frame, thinner and fainter */
.frame-selected {{ outline: 2px solid rgba(245, 150, 29, 0.5); outline-offset: 2px; }}
.frame-dim {{ opacity: 0.5; }}
.frame-dim:hover {{ opacity: 0.9; }}

/* A plain container dressed like the outlined fields around it */
.field-box {{
    border: 1px solid rgba(0, 0, 0, 0.24); border-radius: 3px; background: #fff;
    padding: 4px 12px 8px;
}}
body.body--dark .field-box {{ border-color: {EDGE}; background: {PANEL}; }}
.field-box-label {{ font-size: 0.75rem; color: rgba(0, 0, 0, 0.6); }}
body.body--dark .field-box-label {{ color: rgba(255, 255, 255, 0.7); }}
.field-box .q-chip {{ margin: 0; }}

/* Review: boxes with a fixed size that scroll inside instead of growing */
.box-fixed .q-field__control {{ height: var(--box-h); }}
.box-fixed .q-field__control-container {{ height: 100%; overflow-y: auto; align-content: flex-start; }}
.box-fixed textarea {{ height: 100% !important; resize: none !important; }}

/* Filmstrip: one row that scrolls sideways only */
.strip {{ overflow-x: auto; overflow-y: hidden; scrollbar-width: thin; }}
"""


def apply() -> None:
    """Call once per page, before building it."""
    ui.colors(primary=ORANGE, dark=BODY, dark_page=BODY)
    ui.add_css(_CSS)


ui.button.default_props("no-caps unelevated")
