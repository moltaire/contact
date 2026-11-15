"""
contact_gui/sheet.py
────────────────────
Step 5: the contact sheet — rebuilt from the sidecars, previewed inline,
with the option to rename the folder to the standard pattern.
"""

import time
import webbrowser
from collections.abc import Callable

from nicegui import run, ui

from processor.pipeline import rebuild_contact_sheet, refresh_roll_summary
from processor.roll import build_folder_name
from processor.tagger import ensure_ollama

from .files import roll_file_url
from .state import display_path, state


class SheetView:
    def __init__(self, on_renamed: Callable[[], None]) -> None:
        self.on_renamed = on_renamed
        self._updating = False
        self._attempted: float | None = None  # newest sidecar time at the last attempt

    @ui.refreshable_method
    def render(self) -> None:
        if state.folder is None:
            ui.label("Select a folder first.").classes("text-grey-7")
            return
        # Rebuilt on every visit so that edits from the review step always show up.
        index = rebuild_contact_sheet(state.folder, state.roll)
        if index is None:
            ui.label("No tagged frames yet. Tag some in the Tagging step first.") \
                .classes("text-grey-7")
            return

        with ui.row().classes("w-full items-center"):
            ui.label(display_path(index)).classes("text-grey-7 text-sm break-all mono")
            ui.space()
            new_name = build_folder_name(state.roll)
            if new_name and new_name != state.folder.name:
                ui.button(f"Rename folder to {new_name}", icon="drive_file_rename_outline",
                          on_click=lambda: self._rename(new_name)).props("outline")
            ui.button("Open in browser", icon="open_in_new",
                      on_click=lambda: webbrowser.open(index.as_uri()))

        # Opening this step is the "finish review" moment: if frames were edited since the
        # roll summary was written, it is rewritten once, in the background.
        newest = max(img.with_suffix(".xmp").stat().st_mtime for img in state.tagged)
        stale = state.summary_is_stale() and not state.busy and newest != self._attempted
        if self._updating or stale:
            with ui.row().classes("items-center gap-2"):
                ui.spinner(size="sm")
                ui.label("Frames changed since the roll summary was written — updating it…") \
                    .classes("text-sm text-grey-6")
            if not self._updating:
                self._updating = True
                self._attempted = newest  # one attempt per set of edits, even if it fails
                ui.timer(0.1, self._update_summary, once=True)

        ui.element("iframe") \
            .props(f'src="{roll_file_url("index.html")}?v={int(time.time())}"') \
            .classes("w-full h-[75vh] border-0")

    async def _update_summary(self) -> None:
        try:
            await run.io_bound(ensure_ollama)
            await run.io_bound(refresh_roll_summary, state.folder, dict(state.roll),
                               state.vision_model, state.text_model)
            state.reload_folder()
        except Exception as e:
            ui.notify(f"Could not update the roll summary: {e}", type="negative")
        finally:
            # Cleared even on failure, so a broken model does not retry on every visit
            state.edited_since_summary = False
            self._updating = False
        self.render.refresh()

    def _rename(self, new_name: str) -> None:
        if state.busy:
            ui.notify("A tagging run is in progress — wait for it to finish.", type="warning")
            return
        target = state.folder.parent / new_name
        if target.exists():
            ui.notify(f"Cannot rename: '{new_name}' already exists.", type="negative")
            return
        state.folder.rename(target)
        selected = state.selected
        state.open_folder(target)
        state.selected = selected
        ui.notify(f"Folder renamed to {new_name}", type="positive")
        self.on_renamed()
