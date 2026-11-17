"""
contact_gui/overview.py
───────────────────────
A roll's home page: what the roll is, every frame in a grid, and what to do next —
tag new frames, edit, open the contact sheet, rename the folder, move it into the
library.

Tagging runs in the background (`state.job`), not in this page, so it keeps going
when the browser tab is switched, reloaded or closed. Frames fill in as they finish.
"""

import shutil
import webbrowser
from collections.abc import Callable
from pathlib import Path

from nicegui import background_tasks, run, ui

from processor.pipeline import is_tagged, rebuild_contact_sheet, tag_images
from processor.roll import _split_list_field, build_folder_name
from processor.sidecar import _read_xmp_meta
from processor.tagger import ensure_ollama

from .files import thumb_url
from .roll_form import RollForm
from .state import Job, display_path, state


async def _run_job(job: Job, images: list[Path], vision_model: str, text_model: str,
                   roll: dict) -> None:
    try:
        await run.io_bound(
            tag_images, job.folder, images, vision_model, text_model, roll,
            on_event=job.on_event, should_stop=lambda: job.stop_requested,
        )
    except Exception as e:  # anything unexpected still has to release the UI
        job.error = str(e)
    finally:
        job.running = False


class OverviewView:
    def __init__(self, on_edit: Callable[[str | None], None],
                 on_info_saved: Callable[[], None], on_moved: Callable[[], None]) -> None:
        self.on_edit = on_edit              # open the frame overlay, at a frame (or in Edit if None)
        self.on_info_saved = on_info_saved  # the roll's facts changed
        self.on_moved = on_moved            # the folder was renamed or moved
        self.editing_info = False           # the facts shown as a form, in place
        self.form = RollForm(on_saved=self._info_saved, on_cancel=self.close_info)
        self.selection: set[str] = set()
        self.picking = False  # clicks pick frames (to tag, re-tag or un-tag) instead of opening them
        self._seen_results = -1

    # ── Page ──────────────────────────────────────────────────────────────────

    @ui.refreshable_method
    def render(self) -> None:
        if state.folder is None:
            return
        self.selection &= {img.name for img in state.images}
        if not self.selection and not state.images:
            self.picking = False
        with ui.column().classes("overview gap-0"):
            if self.editing_info:
                self._title()
                with ui.element("div").classes("overview-form"):
                    self.form.build()
            else:
                self._about()
                self._actions()
        self._grid()
        ui.label(f"{display_path(state.folder)} · {state.vision_model}") \
            .classes("overview-footer break-all")
        self._seen_results = -1
        ui.timer(0.5, self._sync)

    def _title(self) -> None:
        roll = state.roll
        tagged = len(state.tagged)
        starred = sum(1 for img in state.tagged
                      if _read_xmp_meta(img.with_suffix(".xmp")).get("starred"))
        counts = [roll.get("date", ""), f"{len(state.images)} frames"]
        if tagged < len(state.images):
            counts.append(f"{tagged} tagged")
        if starred:
            counts.append(f"{starred} favourite{'s' if starred != 1 else ''}")
        with ui.row().classes("items-baseline gap-3"):
            ui.label(state.title).classes("overview-title")
            ui.label(" · ".join(c for c in counts if c)).classes("overview-counts")

    def _about(self) -> None:
        roll = state.roll
        self._title()

        def listed(key: str) -> str:
            return ", ".join(_split_list_field(roll.get(key, "")))

        # two columns: the gear on the left, where and who on the right
        left = [("film", roll.get("film", "")), ("camera", roll.get("camera", "")),
                ("lenses", listed("lens")), ("lab", roll.get("lab", "")),
                ("lab notes", roll.get("lab_notes", ""))]
        right = [("location", listed("location")), ("people", listed("subjects")),
                 ("landmarks", listed("landmarks"))]
        left, right = [r for r in left if r[1]], [r for r in right if r[1]]
        if left or right:
            with ui.element("div").classes("overview-facts"):
                for column in (left, right):
                    with ui.element("div").classes("overview-fact-column"):
                        for key, value in column:
                            with ui.element("div").classes("overview-fact"):
                                ui.label(key).classes("overview-fact-key")
                                ui.label(value)

        # the photographer's own notes, in full; the generated summary below, foldable
        notes = roll.get("notes", "").strip()
        if notes:
            ui.label(notes).classes("overview-notes")
        if roll.get("summary", ""):
            self._summary()

    @ui.refreshable_method
    def _summary(self) -> None:
        open_ = state.summary_open
        with ui.element("div").classes("overview-summary-block"):
            with ui.row().classes("items-center gap-1 overview-summary-toggle no-wrap") \
                    .on("click", self._toggle_summary):
                ui.icon("expand_more" if open_ else "chevron_right", size="xs")
                ui.label("summary")
            if open_:
                ui.label(state.roll.get("summary", "")).classes("overview-summary")

    def _toggle_summary(self) -> None:
        state.set_summary_open(not state.summary_open)
        self._summary.refresh()

    @ui.refreshable_method
    def _actions(self) -> None:
        job = state.job if state.job and state.job.folder == state.folder else None
        untagged = [img for img in state.images if not is_tagged(img)]
        picked = [img for img in state.images if img.name in self.selection]
        busy = state.busy

        if job is not None:
            with ui.column().classes("gap-1 overview-job"):
                with ui.row().classes("w-full items-center no-wrap"):
                    self.stage = ui.label(job.stage).classes("text-sm grow")
                    if job.running:
                        ui.button(icon="stop", on_click=self._stop) \
                            .props("flat round dense size=sm color=negative").tooltip("Stop")
                    else:
                        ui.button(icon="close", on_click=self._dismiss) \
                            .props("flat round dense size=sm color=quiet").tooltip("Dismiss")
                self.bar = ui.linear_progress(job.progress, show_value=False)
                for result in job.failed:
                    ui.label(f"✗ {result.image.name}: {result.error}") \
                        .classes("text-negative text-xs")

        with ui.row().classes("overview-actions items-center gap-2"):
            if self.picking:
                if picked and not busy:
                    verb = "Tag" if all(not is_tagged(img) for img in picked) else "Re-tag"
                    ui.button(f"{verb} {len(picked)} frame{'s' if len(picked) != 1 else ''}",
                              on_click=lambda: self._start(picked))
                    tagged_picked = [img for img in picked if is_tagged(img)]
                    if tagged_picked:
                        ui.button(f"Un-tag {len(tagged_picked)}",
                                  on_click=lambda: self._confirm_untag(tagged_picked)) \
                            .props("outline color=quiet-strong")
                ui.button("Cancel", on_click=self.stop_picking).props("outline color=quiet-strong")
                ui.label("click frames to pick them").classes("overview-hint")
                return

            if untagged and not busy:
                ui.button(f"Tag {len(untagged)} new frame{'s' if len(untagged) != 1 else ''}",
                          on_click=lambda: self._start(untagged))
            if state.tagged:
                edit = ui.button("Edit frames", on_click=lambda: self.on_edit(None))
                if untagged and not busy:
                    edit.props("outline color=quiet-strong")
                if not busy:
                    ui.button("Re-tag frames…", on_click=self._start_picking) \
                        .props("outline color=quiet-strong")
            index = state.folder / "index.html"
            if index.exists():
                ui.button("Contact sheet", on_click=lambda: webbrowser.open(index.as_uri())) \
                    .props("outline color=quiet-strong")
            new_name = build_folder_name(state.roll)
            described = (state.folder / "roll.yaml").exists()  # else the name is just today
            if described and new_name and new_name != state.folder.name and not busy:
                ui.button(f"Rename to {new_name}", on_click=lambda: self._rename(new_name)) \
                    .props("outline color=quiet-strong")
            root = state.library_root
            if root is not None and state.folder.parent.resolve() != root.resolve() and not busy:
                ui.button("Move into library", on_click=self._confirm_move) \
                    .props("outline color=quiet-strong")
            ui.button("Edit info", on_click=self.open_info).props("outline color=quiet-strong")

    @ui.refreshable_method
    def _grid(self) -> None:
        job = state.job if state.job and state.job.folder == state.folder else None
        working = job.current if job and job.running else ""
        grid = ui.element("div").classes("overview-grid" + (" overview-picking" if self.picking else ""))
        with grid:
            for n, img in enumerate(state.images):
                tagged = is_tagged(img)
                starred = tagged and _read_xmp_meta(img.with_suffix(".xmp")).get("starred")
                classes = ["overview-frame"]
                if not tagged:
                    classes.append("overview-untagged")
                if img.name == working:
                    classes.append("overview-working")
                if img.name in self.selection:
                    classes.append("overview-selected")
                if starred:
                    classes.append("frame-starred")
                with ui.element("div").classes(" ".join(classes)) \
                        .on("click", lambda e, n=n: self._click(n, e.args),
                            ["shiftKey", "metaKey", "ctrlKey"]) \
                        .on("mousedown", js_handler="(e) => { if (e.shiftKey) e.preventDefault(); }"):
                    ui.element("img").props(f'src="{thumb_url(img, 320)}" loading="lazy" '
                                            'draggable="false"')
                    ui.label(img.name).classes("overview-name")

    # ── The roll's facts ──────────────────────────────────────────────────────

    def open_info(self) -> None:
        self.editing_info = True
        self.render.refresh()

    def close_info(self) -> None:
        self.editing_info = False
        self.render.refresh()

    def _info_saved(self) -> None:
        self.editing_info = False
        self.on_info_saved()

    # ── Frames and picking ────────────────────────────────────────────────────

    def _click(self, n: int, args: dict) -> None:
        """A click opens a tagged frame. While picking (Re-tag frames…, an untagged
        frame clicked, or ⌘/Ctrl/Shift held) it picks frames instead."""
        img = state.images[n]
        if args.get("shiftKey"):
            names = [i.name for i in state.images]
            anchor = max((names.index(s) for s in self.selection), default=n)
            lo, hi = sorted((anchor, n))
            self.selection |= set(names[lo:hi + 1])
        elif self.picking or args.get("metaKey") or args.get("ctrlKey") or not is_tagged(img):
            self.selection ^= {img.name}
        else:
            self.on_edit(img.name)
            return
        self.picking = True
        self._refresh_picking()

    def _start_picking(self) -> None:
        self.picking = True
        self.selection.clear()
        self._refresh_picking()

    def stop_picking(self) -> None:
        self.picking = False
        self.selection.clear()
        self._refresh_picking()

    def _refresh_picking(self) -> None:
        self._grid.refresh()
        self._actions.refresh()

    # ── Tagging ───────────────────────────────────────────────────────────────

    async def _start(self, images: list[Path]) -> None:
        if state.busy or not images:
            return
        try:
            await run.io_bound(ensure_ollama)
        except RuntimeError as e:
            ui.notify(str(e), type="negative", timeout=0, close_button="OK")
            return
        state.job = Job(folder=state.folder, total=len(images))
        self.selection.clear()
        self.picking = False
        # No page context: the run must not be tied to this browser tab.
        background_tasks.create(
            _run_job(state.job, images, state.vision_model, state.text_model, dict(state.roll)),
            name="tagging",
        )
        self._actions.refresh()
        self._grid.refresh()

    def _stop(self) -> None:
        if state.job:
            state.job.stop_requested = True
            state.job.stage = "Stopping after the current frame…"

    def _dismiss(self) -> None:
        state.job = None
        self._actions.refresh()

    def _sync(self) -> None:
        """Mirror the tagging run into the page. Runs twice a second."""
        job = state.job if state.job and state.job.folder == state.folder else None
        if job is None:
            return
        if job.running:
            if hasattr(self, "stage"):
                self.stage.set_text(job.stage)
                self.bar.set_value(job.progress)
            if len(job.results) != self._seen_results:  # a frame finished: show it
                self._seen_results = len(job.results)
                self._grid.refresh()
            return
        if not job.acknowledged:
            job.acknowledged = True
            state.reload_folder()
            done = len(job.results) - len(job.failed)
            job.stage = f"Tagged {done} of {job.total} frame{'s' if job.total != 1 else ''}."
            if job.error:
                job.stage += f" Stopped with an error: {job.error}"
            elif job.failed:
                job.stage += f" {len(job.failed)} failed and stay untagged."
            elif job.stop_requested:
                job.stage += " Stopped early."
            self.render.refresh()

    # ── Untagging ─────────────────────────────────────────────────────────────

    def _confirm_untag(self, targets: list[Path]) -> None:
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Delete the metadata of {len(targets)} frame"
                     f"{'s' if len(targets) != 1 else ''}?").classes("text-lg")
            ui.label("Descriptions, tags, people, landmarks, favourites and any edits for "
                     "these frames are lost. The images themselves are not touched.") \
                .classes("text-quiet")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat")
                ui.button("Delete metadata", color="negative",
                          on_click=lambda: (dialog.close(), self._untag(targets)))
        dialog.open()

    def _untag(self, targets: list[Path]) -> None:
        for img in targets:
            img.with_suffix(".xmp").unlink(missing_ok=True)
        state.reload_folder()
        self.selection.clear()
        self.picking = False
        rebuild_contact_sheet(state.folder, state.roll)
        ui.notify(f"Removed metadata from {len(targets)} frame(s).")
        self.render.refresh()

    # ── Folder ────────────────────────────────────────────────────────────────

    def _rename(self, new_name: str) -> None:
        if state.busy:
            ui.notify("A tagging run is in progress — wait for it to finish.", type="warning")
            return
        target = state.folder.parent / new_name
        if target.exists():
            ui.notify(f"Cannot rename: '{new_name}' already exists.", type="negative")
            return
        state.folder.rename(target)
        state.open_folder(target)
        state.library = None  # read the library again: a roll changed its name
        ui.notify(f"Folder renamed to {new_name}", type="positive")
        self.on_moved()

    def _confirm_move(self) -> None:
        root = state.library_root
        target = root / state.folder.name
        with ui.dialog() as dialog, ui.card().classes("max-w-xl"):
            ui.label("Move this roll into the library?").classes("text-lg")
            ui.label(f"The folder moves from {display_path(state.folder.parent)} to "
                     f"{display_path(root)}, with everything in it.").classes("text-quiet")
            if target.exists():
                ui.label(f"There is already a folder called {state.folder.name} in the "
                         "library. Rename this one first.").classes("text-negative")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat")
                ui.button("Move", on_click=lambda: (dialog.close(), self._move(target))) \
                    .set_enabled(not target.exists())
        dialog.open()

    def _move(self, target: Path) -> None:
        if state.busy or target.exists():
            return
        try:
            moved = Path(shutil.move(str(state.folder), str(target)))
        except OSError as e:
            ui.notify(f"Could not move the folder: {e}", type="negative")
            return
        state.open_folder(moved)
        state.library = None  # read the library again: it has a new roll
        ui.notify(f"Moved into the library: {display_path(moved)}", type="positive")
        self.on_moved()
