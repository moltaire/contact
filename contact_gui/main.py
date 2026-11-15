"""
contact_gui/main.py
───────────────────
NiceGUI front end for contact. Installed as the `contact-gui` command.

    contact-gui                      # start and open the browser
    contact-gui --folder ~/scans/roll_01
"""

import argparse
from pathlib import Path

from nicegui import native, run, ui

from . import files  # noqa: F401 — registers the image routes
from . import theme
from .folder import FolderView
from .review import ReviewView
from .roll_form import RollView
from .settings import SettingsDialog
from .sheet import SheetView
from .state import state
from .tagging import TaggingView

TABS = {
    "folder": "Folder",
    "roll": "Roll info",
    "tagging": "Tagging",
    "review": "Review",
    "sheet": "Contact sheet",
}


@ui.page("/")
async def index() -> None:
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
        if e.value == "review":
            # The clicked tab keeps focus and Quasar uses arrow keys to move between tabs,
            # which would steal ← → from frame navigation. No Python API for blur.
            ui.run_javascript("document.activeElement.blur()")

    def on_tagging_finished(all_ok: bool) -> None:
        refresh_all()
        if all_ok:
            go("review")

    def on_key(e) -> None:
        if panels.value == "review" and not settings.dialog.value:
            review.handle_key(e)

    folder = FolderView(on_opened=refresh_all, on_continue=lambda: go("roll"))
    roll = RollView(on_saved=lambda: (refresh_all(), go("tagging")))
    tagging = TaggingView(on_finished=on_tagging_finished)
    review = ReviewView(on_roll_changed=lambda: roll.render.refresh())
    sheet = SheetView(on_renamed=refresh_all)
    views = {"folder": folder, "roll": roll, "tagging": tagging, "review": review, "sheet": sheet}

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
    with ui.tab_panels(tabs, value=start, on_change=on_tab_change).classes("w-full") as panels:
        for name, view in views.items():
            with ui.tab_panel(name):
                view.render()

    settings = SettingsDialog(on_lists_changed=lambda: roll.render.refresh())

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
