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

/* Review: the entry line's mode, the candidates under it, and the sheet */
.entry-mode {{
    font-family: {_MONO}; font-size: 0.72rem; letter-spacing: 0.06em; color: {ORANGE};
    padding-right: 8px; margin-right: 2px; border-right: 1px solid {EDGE}; white-space: nowrap;
}}
body.body--light .entry-mode {{ color: {ORANGE_DEEP}; border-right-color: #d5d4cf; }}
.candidate {{ margin: 0; font-size: 0.78rem; }}
.sheet-row {{ border-top: 1px solid {EDGE}; padding: 4px 2px; gap: 12px; }}
body.body--light .sheet-row {{ border-top-color: #d5d4cf; }}
.sheet-key {{
    font-family: {_MONO}; font-size: 0.72rem; letter-spacing: 0.06em; color: {ALUMINIUM};
    width: 4.5rem; flex: none; line-height: 1.5rem;
}}
body.body--light .sheet-key {{ color: #6b6a66; }}
.sheet-key.cursor-pointer:hover {{ color: {ORANGE}; }}
.sheet-value {{ font-family: {_MONO}; font-size: 0.82rem; line-height: 1.5rem; }}
.sheet-values .sheet-value:not(:last-child)::after {{ content: ","; color: {ALUMINIUM}; }}
.sheet-removable {{ cursor: pointer; }}
.sheet-removable:hover {{ text-decoration: line-through; color: {ORANGE}; }}
.sheet-inherited, .sheet-empty {{ color: {ALUMINIUM}; font-family: {_MONO}; font-size: 0.82rem; line-height: 1.5rem; }}
.sheet-select {{ font-size: 0.82rem; min-width: 9rem; }}
.sheet-select .q-field__control, .sheet-select .q-field__native {{ min-height: 1.6rem; height: 1.6rem; padding: 0; }}
.sheet-select .q-field__marginal {{ height: 1.6rem; }}

/* Library: roll cards (miniature contact sheets), frame grids, filters */
.library-year {{
    font-family: {_MONO}; font-size: 0.8rem; letter-spacing: 0.08em; color: {ALUMINIUM};
    margin: 14px 0 2px; width: 100%; border-top: 1px solid {EDGE}; padding-top: 10px;
}}
.library-grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 18px; width: 100%;
}}
.library-card {{ cursor: pointer; min-width: 0; }}
.library-sheet {{
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 3px;
    background: #050505; padding: 6px; border-radius: 3px; border: 1px solid {EDGE};
}}
.library-card:hover .library-sheet {{ border-color: {ORANGE}; }}
.library-frame {{ width: 100%; aspect-ratio: 3 / 2; object-fit: cover; display: block; background: #111; }}
.library-frame-empty {{ background: #0c0c0c; }}
.library-card-title {{ font-weight: 600; font-size: 0.9rem; margin-top: 8px; }}
.library-card-sub {{ font-family: {_MONO}; font-size: 0.72rem; color: {ALUMINIUM}; }}
.library-roll {{ border-top: 1px solid {EDGE}; padding-top: 10px; margin-top: 12px; }}
.library-frames {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
    gap: 8px; width: 100%;
}}
.library-hit {{
    width: 100%; aspect-ratio: 3 / 2; object-fit: cover; display: block; cursor: pointer;
    background: #0a0a0a; border-radius: 2px;
}}
.library-hit:hover {{ outline: 2px solid {ORANGE}; outline-offset: 2px; }}
.library-filters {{ border: 1px solid {EDGE}; border-radius: 3px; padding: 10px 12px; }}
body.body--light .library-year, body.body--light .library-roll {{ border-top-color: #d5d4cf; }}
body.body--light .library-filters {{ border-color: #d5d4cf; }}
body.body--light .library-card-sub, body.body--light .library-year {{ color: #6b6a66; }}

/* Keyboard shortcuts overlay */
.help-card {{ width: 860px; max-width: 94vw; padding: 20px 24px; gap: 16px; }}
.wordmark-plain {{ font-family: {_MONO}; font-weight: 700; letter-spacing: 0.04em; }}
.help-title {{
    font-family: {_MONO}; font-size: 0.72rem; letter-spacing: 0.08em; text-transform: uppercase;
    color: {ORANGE};
}}
body.body--light .help-title {{ color: {ORANGE_DEEP}; }}
.help-note {{ color: {ALUMINIUM}; border-top: 1px solid {EDGE}; padding-top: 12px; }}
body.body--light .help-note {{ color: #6b6a66; border-top-color: #d5d4cf; }}
.kbd {{
    font-family: {_MONO}; font-size: 0.75rem; line-height: 1; white-space: nowrap;
    padding: 4px 6px; border: 1px solid {EDGE}; border-bottom-width: 2px; border-radius: 4px;
    background: #262626;
}}
body.body--light .kbd {{ background: #f4f3f0; border-color: #c9c8c3; }}
.q-dialog__backdrop {{ background: rgba(0, 0, 0, 0.6); }}

/* Filmstrip: one row that scrolls sideways only */
.strip {{ overflow-x: auto; overflow-y: hidden; scrollbar-width: thin; }}
"""


def apply() -> None:
    """Call once per page, before building it."""
    ui.colors(primary=ORANGE, dark=BODY, dark_page=BODY)
    ui.add_css(_CSS)


ui.button.default_props("no-caps unelevated")
