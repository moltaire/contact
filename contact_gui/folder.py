"""
contact_gui/folder.py
─────────────────────
Step 1: choose the roll folder and see what is in it.
"""

import platform
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from nicegui import run, ui

from processor.pipeline import is_tagged

from .files import thumb_url
from .state import display_path, state


def _pick_folder_dialog() -> str:
    """Open the system folder picker. Blocking; returns '' if cancelled."""
    try:
        if platform.system() == "Darwin":
            cmd = ["osascript", "-e", 'POSIX path of (choose folder with prompt "Select roll folder")']
        else:
            cmd = [
                sys.executable, "-c",
                "import tkinter; from tkinter import filedialog; "
                "root = tkinter.Tk(); root.withdraw(); "
                "root.wm_attributes('-topmost', True); "
                "print(filedialog.askdirectory(), end=''); root.destroy()",
            ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


class FolderView:
    def __init__(self, on_opened: Callable[[], None], on_continue: Callable[[], None]) -> None:
        self.on_opened = on_opened
        self.on_continue = on_continue

    @ui.refreshable_method
    def render(self) -> None:
        with ui.row().classes("w-full items-center no-wrap"):
            ui.button("Choose folder…", icon="folder_open", on_click=self._browse).props("outline")
            self.path_input = ui.input(
                placeholder="/path/to/scans/roll_01",
                value=display_path(state.folder) if state.folder else "",
            ).props("outlined dense").classes("grow")
            self.path_input.on("keydown.enter", lambda: self._open(self.path_input.value))
            ui.button("Open", on_click=lambda: self._open(self.path_input.value)).props("flat")
            ui.button("Continue to roll info", on_click=self.on_continue) \
                .set_enabled(state.folder is not None)

        if state.folder is None:
            ui.label("Choose a folder containing your scanned film images.").classes("text-grey-7")
            return

        n, n_tagged = len(state.images), len(state.tagged)
        parts = [f"{n} image{'s' if n != 1 else ''}"]
        if n_tagged:
            parts.append(f"{n_tagged} tagged")
        parts.append("roll.yaml found" if state.roll else "no roll.yaml")
        ui.label(" · ".join(parts)).classes("text-grey-7")

        with ui.grid(columns=6).classes("w-full gap-3"):
            for img in state.images:
                with ui.column().classes("gap-1"):
                    ui.image(thumb_url(img)).props("fit=contain").classes("w-full h-40 frame")
                    ui.label(("✓ " if is_tagged(img) else "") + img.name) \
                        .classes("text-xs text-grey-7 break-all mono")

    async def _browse(self) -> None:
        picked = await run.io_bound(_pick_folder_dialog)
        if picked:
            self._open(picked)

    def _open(self, value: str) -> None:
        if not value or not value.strip():
            return
        if state.busy:
            ui.notify("A tagging run is in progress — stop it before switching folders.",
                      type="warning")
            return
        path = Path(value.strip()).expanduser().resolve()
        if not path.is_dir():
            ui.notify(f"Folder not found: {path}", type="negative")
            return
        state.open_folder(path)
        self.on_opened()
