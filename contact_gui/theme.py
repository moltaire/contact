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
    vertical-align: middle; position: relative; top: -0.04em;  /* centred on the lowercase */
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
    width: 5.5rem; flex: none; line-height: 1.5rem;
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

/* Two-way switches (View/Edit, Rolls/Frames) */
/* Pills, not boxes: a rounded orange-on-black rectangle reads as a well-known
   website's logo */
.mode-toggle {{
    border: 1px solid {EDGE}; border-radius: 999px; padding: 2px; position: relative;
    display: inline-grid; grid-auto-flow: column; grid-auto-columns: 1fr;  /* equal halves */
}}
.mode-toggle .q-btn {{
    padding: 3px 14px; min-height: 0; border-radius: 999px !important;
    position: relative; z-index: 1;
    transition: color 180ms ease;
}}
/* The pill itself slides under the labels to the chosen half */
.mode-toggle::before {{
    content: ""; position: absolute; top: 2px; bottom: 2px; left: 2px;
    width: calc(50% - 2px); border-radius: 999px; background: var(--q-primary);
    transition: transform 180ms ease;
}}
/* The chosen half is marked bg-transparent (toggle-color=transparent): the sliding
   pill is the only orange, so it keeps its size, like a physical slider */
.mode-toggle:has(> .q-btn:last-child.bg-transparent)::before {{ transform: translateX(100%); }}
.mode-toggle .q-btn:not(.bg-transparent) {{ color: {LETTERING}; }}
body.body--light .mode-toggle .q-btn:not(.bg-transparent) {{ color: {BODY}; }}
body.body--light .mode-toggle .q-btn.bg-transparent {{ color: #fff !important; }}
body.body--light .mode-toggle {{ border-color: #d5d4cf; }}

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
.library-card-info {{ margin-top: 6px; }}
.library-card-info:hover {{ color: {ORANGE} !important; }}
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

/* Library: one roll's frames */
.library-focus {{ border-bottom: 1px solid {EDGE}; padding-bottom: 8px; }}
.library-hit-box {{ position: relative; }}
.library-untagged {{ opacity: 0.45; }}

/* Roll overview: title, facts in two columns, summary, one row of actions, frames */
.overview {{ max-width: 62rem; }}
.overview-title {{ font-weight: 600; font-size: 1.5rem; }}
.overview-counts {{ font-family: {_MONO}; font-size: 0.8rem; color: {ALUMINIUM}; }}
.overview-facts {{
    display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 40px;
    margin-top: 16px; max-width: 52rem;
}}
.overview-fact-column {{ display: flex; flex-direction: column; gap: 4px; min-width: 0; }}
.overview-fact {{ display: grid; grid-template-columns: 6rem minmax(0, 1fr); font-size: 0.88rem; line-height: 1.45; }}
.overview-fact-key {{ font-family: {_MONO}; font-size: 0.75rem; letter-spacing: 0.04em; color: {ALUMINIUM}; padding-top: 1px; }}
.overview-notes {{ max-width: 46rem; line-height: 1.55; font-size: 0.92rem; margin-top: 16px; white-space: pre-line; }}
.overview-summary-block {{ margin-top: 14px; max-width: 46rem; }}
.overview-summary-toggle {{
    font-family: {_MONO}; font-size: 0.75rem; letter-spacing: 0.04em; color: {ALUMINIUM};
    cursor: pointer; user-select: none; width: fit-content; margin-left: -3px;
}}
.overview-summary-toggle:hover {{ color: {ORANGE}; }}
.overview-summary {{ line-height: 1.55; font-size: 0.88rem; color: {ALUMINIUM}; margin-top: 4px; }}
.overview-job {{ border: 1px solid {EDGE}; border-radius: 3px; padding: 8px 10px; margin-top: 20px; max-width: 30rem; }}
.overview-actions {{ margin-top: 20px; min-height: 2.25rem; }}
.overview-hint {{ font-size: 0.8rem; color: {ALUMINIUM}; margin-left: 6px; }}
.overview-footer {{ font-family: {_MONO}; font-size: 0.7rem; color: {ALUMINIUM}; margin-top: 20px; }}
body.body--light .overview-counts, body.body--light .overview-fact-key,
body.body--light .overview-summary, body.body--light .overview-hint,
body.body--light .overview-summary-toggle,
body.body--light .overview-footer {{ color: #6b6a66; }}
.overview-grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr));
    gap: 12px; width: 100%; margin-top: 24px; user-select: none; -webkit-user-select: none;
}}
.overview-frame {{ position: relative; cursor: pointer; }}
.overview-frame img {{
    width: 100%; aspect-ratio: 3 / 2; object-fit: cover; display: block;
    background: #0a0a0a; border-radius: 2px;
}}
.overview-frame:hover img {{ outline: 2px solid {ORANGE}; outline-offset: 2px; }}
.overview-name {{ font-family: {_MONO}; font-size: 0.68rem; color: {ALUMINIUM}; margin-top: 3px; }}
.overview-untagged img {{ opacity: 0.4; border: 1px dashed {ALUMINIUM}; }}
.overview-working img {{ outline: 2px solid {ORANGE}; outline-offset: 2px; opacity: 1; }}
.overview-picking .overview-frame img {{ opacity: 0.55; }}
.overview-picking .overview-frame:hover img {{ opacity: 0.8; }}
.overview-picking .overview-selected img, .overview-selected img {{
    outline: 3px solid {ORANGE}; outline-offset: 2px; opacity: 1;
}}

/* Roll info form */
.roll-form {{ max-width: 52rem; }}
.overview-form {{ margin-top: 18px; width: 52rem; max-width: 100%; }}

/* Header breadcrumb */
.crumb {{ color: {ALUMINIUM}; }}
.crumb:hover {{ color: {ORANGE}; }}
body.body--light .crumb {{ color: #6b6a66; }}

/* Frame overlay: full screen over the library or a roll's overview.
   The same skeleton in View and Edit; Edit only adds the entry line and the strip. */
.frame-overlay {{
    display: flex; flex-direction: column; width: 100vw; height: 100vh;
    background: {BODY}; color: {LETTERING};
}}
.frame-top {{ padding: 10px 24px; border-bottom: 1px solid {EDGE}; flex: none; }}
.frame-origin {{ max-width: 22rem; }}
.frame-origin .q-btn__content {{ white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex-wrap: nowrap; }}
.frame-roll {{ font-weight: 600; font-size: 0.9rem; }}

.frame-roll:hover {{ color: {ORANGE}; }}
.frame-main {{ display: flex; flex: 1; min-height: 0; gap: 32px; padding: 28px 32px 24px; }}
.frame-stage {{ flex: 1; min-width: 0; height: 100%; background: #0a0a0a; border-radius: 2px; }}
.frame-image {{ width: 100%; height: 100%; }}
.frame-image img {{ object-fit: contain; }}
.frame-side {{
    width: 400px; flex: none; height: 100%; overflow-y: auto; overflow-x: hidden;
    display: flex; flex-direction: column; gap: 12px;
}}
/* The description reads the same in View (a box) and Edit (a textarea): same text,
   same line spacing, the label and first line in the same place */
.frame-description {{ height: 8.75rem; overflow-y: auto; flex: none; padding: 4px 11px 8px; }}
.frame-description .field-box-label {{ margin: 5px 0 1px; line-height: 16px; }}
.frame-description, .frame-side .q-textarea textarea {{
    font-size: 14px; line-height: 1.5; letter-spacing: 0.00938em;
}}
/* Quasar draws the floated label as 16px text scaled to 75%, which renders differently
   from plain 12px text; make it plain 12px, in the same place */
.frame-side .q-textarea.q-field--float .q-field__label {{
    font-size: 12px; transform: translateY(-6.5px); letter-spacing: 0.13px; line-height: 13.8px;
}}
.frame-description .field-box-label {{ letter-spacing: 0.13px; }}
.frame-candidates {{ min-height: 5.25rem; flex: 0 1 auto; overflow: hidden; }}
.frame-strip {{ flex: none; padding: 6px 32px 20px; }}

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

/* Filmstrip: one row that scrolls sideways only; clicks select frames, never text */
.strip {{ overflow-x: auto; overflow-y: hidden; scrollbar-width: thin;
          user-select: none; -webkit-user-select: none; }}
.frame-starred::after {{
    content: "★"; position: absolute; top: 1px; right: 4px; font-size: 0.8rem;
    color: {ORANGE}; text-shadow: 0 0 3px #000;
}}
"""


def apply() -> None:
    """Call once per page, before building it."""
    ui.colors(primary=ORANGE, dark=BODY, dark_page=BODY)
    ui.add_css(_CSS)


ui.button.default_props("no-caps unelevated")
