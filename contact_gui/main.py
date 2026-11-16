"""
contact_gui/main.py
───────────────────
NiceGUI front end for contact. Installed as the `contact-gui` command.

    contact-gui                      # start and open the browser
    contact-gui --folder ~/scans/roll_01
"""

import argparse
from pathlib import Path

from nicegui import background_tasks, native, run, ui

from . import files  # noqa: F401 — registers the image routes
from . import theme
from .folder import FolderView
from .help import HelpDialog
from .library import LibraryView
from .review import ReviewView
from .roll_form import RollView
from .settings import SettingsDialog
from .sheet import SheetView
from .state import state
from .tagging import TaggingView

# Three keys are handled in the browser itself:
#   Return and "/" jump to the fact field in review. Only here can "/" be kept from
#        Firefox's quick find and Return from re-pressing a button that still has
#        focus; focusing directly is also instant.
#   Esc  leaves whatever field has the cursor (tags, description, place, …), which hands
#        the keyboard back to the shortcuts. Dialogs keep their own Esc.
_SLASH_KEY_SCRIPT = """
<script>
document.addEventListener("keydown", (event) => {
  const target = event.target;
  const typing = target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
  if (event.key === "Escape" && typing && !target.closest(".q-dialog")) {
    target.blur();
    return;
  }
  if (event.key !== "/" && event.key !== "Enter") return;
  if (event.metaKey || event.ctrlKey || event.altKey) return;
  if (typing || document.querySelector(".q-dialog")) return;
  // the entry line in review, or the search box in the library — whichever is showing
  const field = [...document.querySelectorAll(".fact-field input, .library-search input")]
    .find((el) => el.offsetParent !== null);
  if (!field) return;
  event.preventDefault();
  field.focus();
});
</script>
"""

TABS = {
    "library": "Library",
    "folder": "Folder",
    "roll": "Roll info",
    "tagging": "Tagging",
    "review": "Review",
    "sheet": "Contact sheet",
}


@ui.page("/")
async def index(tab: str = "") -> None:
    """The whole app is one page. `/?tab=review` opens it on a given step."""
    def go(tab: str) -> None:
        panels.set_value(tab)

    def refresh_all() -> None:
        title.set_text(state.title)
        ui.page_title(f"contact · {state.title}" if state.title else "contact")
        for view in views.values():
            view.render.refresh()

    def on_tab_change(e) -> None:
        review.save()  # leaving the review step must never lose an edit
        if e.value in ("review", "sheet", "tagging"):
            views[e.value].render.refresh()  # these show what is on disk right now
        if e.value == "library":
            background_tasks.create(library.reload(), name="library")  # pick up edits
        if e.value == "review":
            # The clicked tab keeps focus and Quasar uses arrow keys to move between tabs,
            # which would steal ← → from frame navigation. No Python API for blur.
            ui.run_javascript("document.activeElement.blur()")

    def open_roll(folder: Path, frame: str | None) -> None:
        """From the library: open a roll, in review at a frame if one was clicked."""
        if state.busy and folder != state.folder:
            ui.notify("A tagging run is in progress — stop it before switching rolls.",
                      type="warning")
            return
        if folder != state.folder:
            state.open_folder(folder)
        names = [img.name for img in state.tagged]
        review.index = names.index(frame) if frame in names else 0
        refresh_all()
        go("review" if state.tagged else "folder")

    def on_tagging_finished(all_ok: bool) -> None:
        refresh_all()
        if all_ok:
            go("review")

    def on_key(e) -> None:
        if settings.dialog.value:
            return
        if e.action.keydown and str(e.key.name) == "?":
            help_dialog.toggle()
        elif panels.value == "review" and not help_dialog.is_open:
            review.handle_key(e)

    folder = FolderView(on_opened=refresh_all, on_continue=lambda: go("roll"))
    roll = RollView(on_saved=lambda: (refresh_all(), go("tagging")))
    tagging = TaggingView(on_finished=on_tagging_finished)
    review = ReviewView(on_roll_changed=lambda: roll.render.refresh(),
                        on_help=lambda: help_dialog.open())
    sheet = SheetView(on_renamed=refresh_all)
    library = LibraryView(on_open=open_roll)
    views = {"library": library, "folder": folder, "roll": roll, "tagging": tagging,
             "review": review, "sheet": sheet}

    theme.apply()
    await run.io_bound(state.refresh_models)

    # px-8 lines the wordmark up with the content below (page + panel padding)
    with ui.header().classes("items-center px-8 py-2"):
        ui.label("contact").classes("text-xl wordmark")
        title = ui.label().classes("text-lg mono subtitle")
        ui.space()
        with ui.tabs().props("dense") as tabs:
            for name, label in TABS.items():
                ui.tab(name, label=label)
        ui.button(icon="settings", on_click=lambda: settings.open()) \
            .props("flat round dense color=grey-6").tooltip("Settings")

    start = "folder" if state.folder is None else ("tagging" if state.busy else "folder")
    if state.folder is None and state.library_root is not None:
        start = "library"
    if tab == "library" or (tab in TABS and state.folder is not None):
        start = tab
    with ui.tab_panels(tabs, value=start, on_change=on_tab_change).classes("w-full") as panels:
        for name, view in views.items():
            with ui.tab_panel(name):
                view.render()

    settings = SettingsDialog(on_lists_changed=lambda: roll.render.refresh())
    help_dialog = HelpDialog()
    ui.add_body_html(_SLASH_KEY_SCRIPT)

    # Buttons and tabs keep focus after a click; only real text fields should swallow arrows.
    ui.keyboard(on_key=on_key, ignore=["input", "select", "textarea"])
    title.set_text(state.title)
    ui.page_title(f"contact · {state.title}" if state.title else "contact")


def run_app() -> None:
    parser = argparse.ArgumentParser(description="contact — browser UI for tagging film scans.")
    parser.add_argument("--folder", metavar="DIR", help="Roll folder to open on start.")
    parser.add_argument("--port", type=int, default=None, help="Port to serve on (default: a free one).")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser.")
    parser.add_argument("--light", action="store_true", help="Use the light theme (default: dark).")
    args = parser.parse_args()

    if args.folder:
        path = Path(args.folder).expanduser().resolve()
        if not path.is_dir():
            parser.error(f"not a directory: {path}")
        state.open_folder(path)

    ui.run(
        host="127.0.0.1",  # local tool: never expose the scans folder to the network
        port=args.port or native.find_open_port(8080, 8999),
        title="contact",
        favicon="🎞️",
        dark=not args.light,
        show=not args.no_browser,
        reload=False,
    )


if __name__ in {"__main__", "__mp_main__"}:
    run_app()
