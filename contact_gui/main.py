"""
contact_gui/main.py
───────────────────
NiceGUI front end for contact. Installed as the `contact-ui` command.

    contact-ui                      # start and open the browser
    contact-ui --folder ~/scans/roll_01

The library is home: browse every roll and frame there. Opening a roll — the button on
its card, R on a frame, or "New roll" — shows its pages under a breadcrumb back to the
library: Overview (tag, contact sheet, rename, move) and Info. A frame, from anywhere,
opens in the frame overlay (frames.py) for viewing and editing. The browser's back and
forward buttons move between all of these.
"""

import argparse
import json
from pathlib import Path
from urllib.parse import quote

from nicegui import background_tasks, native, run, ui

from . import files  # noqa: F401 — registers the image routes
from . import theme
from .folder import pick_folder
from .help import HelpDialog
from .library import LibraryView
from processor.library import scan_roll

from .frames import FrameOverlay
from .library import _roll_hits
from .overview import OverviewView
from .settings import SettingsDialog
from .state import display_path, state

# Keys handled in the browser itself, before NiceGUI sees them:
#   Return and "/" jump to the entry line (frame overlay, Edit) or the library's search.
#        Only here can "/" be kept from Firefox's quick find and Return from re-pressing
#        a button that still has focus; focusing directly is also instant.
#   Esc  leaves whatever field has the cursor, which hands the keyboard back to the
#        shortcuts. Other dialogs keep their own Esc.
# And the browser's back/forward buttons, reported to Python as "contact_nav".
_BROWSER_SCRIPT = """
<script>
document.addEventListener("keydown", (event) => {
  const target = event.target;
  const typing = target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
  const inOverlay = !!target.closest(".frame-overlay");
  if (event.key === "Escape" && typing && (inOverlay || !target.closest(".q-dialog"))) {
    target.blur();
    // ui.keyboard checks the focus, which is gone now: keep this Esc from also
    // reaching it and closing the frame view
    event.stopImmediatePropagation();
    return;
  }
  if (event.key !== "/" && event.key !== "Enter") return;
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (typing) return;
  const dialog = document.querySelector(".q-dialog");
  if (dialog && !dialog.querySelector(".frame-overlay")) return;
  const field = [...document.querySelectorAll(".fact-field input, .library-search input")]
    .find((el) => el.offsetParent !== null);
  if (!field) return;
  event.preventDefault();
  field.focus();
});
window.addEventListener("popstate", (event) => emitEvent("contact_nav", event.state || {}));
</script>
"""

PAGES = ("library", "overview")

# the wordmark's orange dot, alone
FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 16 16">'
           f'<circle cx="8" cy="8" r="6" fill="{theme.ORANGE}"/></svg>')


async def _refresh_models() -> None:
    await run.io_bound(state.refresh_models)


@ui.page("/")
async def index(tab: str = "") -> None:
    """The whole app is one page. `?tab=overview` (or `library`) opens it on that place;
    `?tab=roll` (the old Info page) opens the overview with the roll's facts as a form."""

    # ── Where we are ──────────────────────────────────────────────────────────

    def place() -> dict:
        """The current place, as stored in the browser's history."""
        where = {"v": panels.value}
        if panels.value != "library" and state.folder is not None:
            where["folder"] = str(state.folder)
        if panels.value == "library" and library.focus is not None:
            where["roll"] = str(library.focus)
        if overlay.is_open:
            where = {"v": "frames", "under": panels.value, "focus": where.get("roll"),
                     "folder": where.get("folder"), **overlay.place()}
        return where

    def url(where: dict) -> str:
        if where["v"] == "library":
            return "/?roll=" + quote(Path(where["roll"]).name) if where.get("roll") else "/"
        if where["v"] == "frames":
            return f"/?tab={quote(where['under'])}&frame={quote(where.get('frame', ''))}"
        return f"/?tab={quote(where['v'])}"

    def remember(replace: bool = False) -> None:
        """Record the current place in the browser history (so back/forward work)."""
        if restoring["now"]:
            return
        where = place()
        method = "replaceState" if replace else "pushState"
        ui.run_javascript(f"history.{method}({json.dumps(where)}, '', {json.dumps(url(where))})")

    restoring = {"now": False}

    def show(step: str) -> None:
        """Switch to the library or the roll page and update the header to match."""
        if step == "roll":  # the old Info page: now the form on the roll page
            step = "overview"
            if not overview.editing_info:
                overview.open_info()
        in_roll = step != "library" and state.folder is not None
        if not in_roll:
            step = "library"
        crumb_roll.set_visibility(in_roll)
        crumb_sep.set_visibility(in_roll)
        new_roll_button.set_visibility(not in_roll)
        crumb_roll.set_text(state.title)
        ui.page_title(f"contact · {state.title}" if in_roll else "contact")
        if panels.value != step:
            panels.set_value(step)  # triggers on_panel_change

    def go(step: str) -> None:
        show(step)
        remember()

    def refresh_all() -> None:
        crumb_roll.set_text(state.title)
        for view in views.values():
            view.render.refresh()

    def on_panel_change(e) -> None:
        if e.value == "overview":
            overview.render.refresh()  # it shows what is on disk right now
        if e.value == "library":
            overview.editing_info = False  # an unsaved form is dropped, as with Cancel
            background_tasks.create(library.reload(), name="library")  # pick up edits
        # A clicked button keeps focus, and Return would press it again. No Python API
        # for blur.
        ui.run_javascript("document.activeElement.blur()")

    def open_roll(folder: Path, tab: str | None = None, record: bool = True) -> bool:
        """Open a roll on its overview, or on the page `tab`."""
        if state.busy and folder != state.folder:
            ui.notify("A tagging run is in progress — wait for it before switching rolls.",
                      type="warning")
            return False
        if folder != state.folder:
            state.open_folder(folder)
            overview.selection.clear()
            overview.picking = False
            overview.editing_info = False
        refresh_all()
        if tab is None:
            # a brand-new roll starts with its facts as a form
            fresh = not state.tagged and not (folder / "roll.yaml").exists()
            tab = "roll" if fresh else "overview"
        show(tab)
        if record:
            remember()
        return True

    def home() -> None:
        overlay.close(record=False)
        library.set_focus(None)
        go("library")

    async def new_roll() -> None:
        with ui.dialog() as dialog, ui.card().classes("w-[640px] max-w-full"):
            ui.label("Open a folder of scans").classes("text-lg")
            ui.label("A new roll, or any roll outside the library. contact reads the folder "
                     "and writes its metadata next to the scans.").classes("text-sm text-grey-6")
            with ui.row().classes("w-full items-center no-wrap"):
                ui.button("Choose folder…", icon="folder_open",
                          on_click=lambda: dialog.submit("browse")).props("outline")
                field = ui.input(placeholder="/path/to/scans/roll_01") \
                    .props("outlined dense autofocus").classes("grow")
                field.on("keydown.enter", lambda: dialog.submit(field.value))
                ui.button("Open", on_click=lambda: dialog.submit(field.value)).props("flat")
        choice = await dialog
        if choice == "browse":
            choice = await run.io_bound(pick_folder, "Select roll folder")
        if not choice or not str(choice).strip():
            return
        path = Path(str(choice).strip()).expanduser().resolve()
        if not path.is_dir():
            ui.notify(f"Folder not found: {display_path(path)}", type="negative")
            return
        open_roll(path)

    def on_browser_nav(e) -> None:
        """Back or forward in the browser: go to the place stored in that history entry."""
        where = e.args if isinstance(e.args, dict) else {}
        restoring["now"] = True
        try:
            view = where.get("v", "library")
            if view == "frames":
                restore_frames(where)
                return
            overlay.close(record=False)
            if view == "library":
                library.set_focus(Path(where["roll"]) if where.get("roll") else None)
            if view != "library" and where.get("folder"):
                folder = Path(where["folder"])
                if folder != state.folder:
                    if not folder.is_dir() or not open_roll(folder, tab=view, record=False):
                        show("library")
                        return
            show(view)
        finally:
            restoring["now"] = False

    def restore_frames(where: dict) -> None:
        """Back or forward onto an open frame overlay: the view underneath first."""
        under = where.get("under", "library")
        if under == "library":
            library.set_focus(Path(where["focus"]) if where.get("focus") else None)
            show("library")
            items, label = library.items_for(where)
        else:
            folder = Path(where.get("folder", ""))
            if folder != state.folder and (not folder.is_dir() or
                                           not open_roll(folder, tab=under, record=False)):
                show("library")
                return
            show(under)
            items, label = roll_items(), state.title
        keys = [(str(h.roll.folder), h.frame.image.name) for h in items]
        key = (where.get("frame_roll"), where.get("frame"))
        origin = {k: where[k] for k in ("from", "scope", "q", "roll") if k in where}
        overlay.restore(items, keys.index(key) if key in keys else 0, origin, label)

    def roll_items():
        roll = scan_roll(state.folder) if state.folder else None
        return _roll_hits(roll) if roll else []

    def edit(frame: str | None) -> None:
        """From the overview: the frame overlay on this roll, in Edit, at a frame or the
        first tagged one."""
        items = roll_items()
        names = [h.frame.image.name for h in items]
        if frame in names:
            index = names.index(frame)
        else:
            index = next((n for n, h in enumerate(items) if h.frame.meta), 0)
        overlay.open(items, index, {"from": "overview"}, state.title,
                     edit=True if frame is None else None)

    def on_overlay_closed() -> None:
        if panels.value == "overview":
            overview.render.refresh()
        elif panels.value == "library":
            library.render.refresh()

    def on_key(e) -> None:
        if settings.dialog.value:
            return
        if e.action.keydown and str(e.key.name) == "?":
            help_dialog.toggle()
        elif help_dialog.is_open:
            return
        elif overlay.is_open:
            overlay.handle_key(e)
        elif (e.action.keydown and panels.value == "library" and str(e.key.name) in ("v", "V")
              and not (e.modifiers.meta or e.modifiers.ctrl or e.modifiers.alt)):
            library.toggle_view()
        elif e.action.keydown and e.key.escape and panels.value == "overview":
            # one level at a time: picking, then the form, then out to the library
            if overview.picking:
                overview.stop_picking()
            elif overview.editing_info:
                overview.close_info()
            else:
                home()

    # ── Views ─────────────────────────────────────────────────────────────────

    def moved() -> None:
        refresh_all()
        show(panels.value)
        remember(replace=True)  # the history entry points at the folder's new place

    def open_roll_from_frame(folder: Path) -> bool:
        return open_roll(folder)

    overlay = FrameOverlay(on_open_roll=open_roll_from_frame,
                           on_change=lambda replace: remember(replace),
                           on_closed=on_overlay_closed, on_help=lambda: help_dialog.open())
    overview = OverviewView(on_edit=edit, on_info_saved=lambda: (refresh_all(), show("overview")),
                            on_moved=moved)
    library = LibraryView(on_open=open_roll, on_nav_change=lambda replace: remember(replace),
                          overlay=overlay)
    views = {"library": library, "overview": overview}

    theme.apply()
    # Asking Ollama what is installed must not hold up the page: while it is busy
    # tagging, the answer can take longer than a page is allowed to build.
    background_tasks.create(_refresh_models(), name="models")

    # px-8 lines the wordmark up with the content below (page + panel padding)
    with ui.header().classes("items-center px-8 py-2 gap-2 no-wrap"):
        ui.label("contact").classes("text-xl wordmark cursor-pointer").on("click", home)
        ui.label("library").classes("text-lg mono crumb cursor-pointer").on("click", home)
        crumb_sep = ui.label("›").classes("text-lg mono subtitle")
        crumb_roll = ui.label().classes("text-lg mono subtitle truncate")
        ui.space()
        new_roll_button = ui.button("New roll", icon="add", on_click=new_roll) \
            .props("flat dense no-caps color=grey-5").tooltip("Open a folder of scans")
        ui.button(icon="settings", on_click=lambda: settings.open()) \
            .props("flat round dense color=grey-6").tooltip("Settings")

    start = "library" if state.folder is None else "overview"
    if tab == "library" or (tab in ("overview", "roll") and state.folder is not None):
        start = tab
    elif (start == "overview" and not state.tagged
          and not (state.folder / "roll.yaml").exists()):
        start = "roll"  # a brand-new roll starts with its facts as a form
    with ui.tab_panels(value="overview" if start == "roll" else start,
                       on_change=on_panel_change).props("animated=false") \
            .classes("w-full") as panels:
        for name, view in views.items():
            with ui.tab_panel(name):
                view.render()

    settings = SettingsDialog(
        on_lists_changed=lambda: overview.render.refresh() if overview.editing_info else None)
    help_dialog = HelpDialog()
    ui.add_body_html(_BROWSER_SCRIPT)
    ui.on("contact_nav", on_browser_nav)

    # Buttons and tabs keep focus after a click; only real text fields should swallow arrows.
    ui.keyboard(on_key=on_key, ignore=["input", "select", "textarea"])
    show(start)
    remember(replace=True)


def run_app() -> None:
    parser = argparse.ArgumentParser(description="contact — browser UI for tagging film scans.")
    parser.add_argument("--folder", metavar="DIR", help="Roll folder to open on start.")
    parser.add_argument("--library", metavar="DIR",
                        help="Folder of rolls to show as the library, for this run only "
                             "(the saved library stays as it is).")
    parser.add_argument("--port", type=int, default=None, help="Port to serve on (default: a free one).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser.")
    parser.add_argument("--light", action="store_true", help="Use the light theme (default: dark).")
    args = parser.parse_args()

    if args.library:
        root = Path(args.library).expanduser().resolve()
        if not root.is_dir():
            parser.error(f"not a directory: {root}")
        state.library_root = root  # not saved: set_library would remember it
        state.library = None
    if args.folder:
        path = Path(args.folder).expanduser().resolve()
        if not path.is_dir():
            parser.error(f"not a directory: {path}")
        state.open_folder(path)

    ui.run(
        host="127.0.0.1",  # local tool: never expose the scans folder to the network
        port=args.port or native.find_open_port(8080, 8999),
        title="contact",
        favicon=FAVICON,
        dark=not args.light,
        show=not args.no_browser,
        reload=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    run_app()
