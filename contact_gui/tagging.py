"""
contact_gui/tagging.py
──────────────────────
Step 3: pick frames and models, then tag in the background.

The run lives in `state.job`, not in the page, so it keeps going when the
browser tab is switched, reloaded or closed. A timer mirrors it into the UI.
"""

from collections.abc import Callable
from pathlib import Path

from nicegui import background_tasks, run, ui

from processor.pipeline import is_tagged, tag_images
from processor.tagger import ensure_ollama

from .files import thumb_url
from .state import Job, state


async def _run_job(job: Job, images: list[Path], vision_model: str, text_model: str, roll: dict) -> None:
    try:
        await run.io_bound(
            tag_images, job.folder, images, vision_model, text_model, roll,
            on_event=job.on_event, should_stop=lambda: job.stop_requested,
        )
    except Exception as e:  # anything unexpected still has to release the UI
        job.error = str(e)
    finally:
        job.running = False


class TaggingView:
    def __init__(self, on_finished: Callable[[bool], None]) -> None:
        self.on_finished = on_finished  # called with True when every frame succeeded

    @ui.refreshable_method
    def render(self) -> None:
        if state.folder is None:
            ui.label("Select a folder first.").classes("text-grey-7")
            return
        if not state.images:
            ui.label("No images found in this folder.").classes("text-grey-7")
            return

        with ui.row().classes("w-full items-center"):
            self._model_select("Vision model", state.vision_models, "vision_model")
            self._model_select("Text model", state.all_models, "text_model")
            ui.space()
            self.untag_button = ui.button("Un-tag selected", on_click=self._confirm_untag) \
                .props("flat color=grey-8")
            self.retag_button = ui.button("Re-tag selected",
                                          on_click=lambda: self._start(retag=True)) \
                .props("outline")
            self.tag_button = ui.button("Tag untagged",
                                        on_click=lambda: self._start(retag=False))

        with ui.card().classes("w-full") as self.progress_card:
            with ui.row().classes("w-full items-center no-wrap"):
                self.stage = ui.label().classes("grow")
                self.stop_button = ui.button("Stop", icon="stop", on_click=self._stop) \
                    .props("flat color=negative")
                self.dismiss_button = ui.button("Dismiss", on_click=self._dismiss).props("flat")
            self.bar = ui.linear_progress(0, show_value=False)
            self.failures = ui.column().classes("gap-0")

        with ui.row().classes("items-center"):
            ui.button("Select all", on_click=lambda: self._select_all(True)).props("flat dense")
            ui.button("Select none", on_click=lambda: self._select_all(False)).props("flat dense")

        self.checkboxes: dict[str, ui.checkbox] = {}
        with ui.grid(columns=6).classes("w-full gap-3"):
            for img in state.images:
                with ui.column().classes("gap-0"):
                    ui.image(thumb_url(img)).props("fit=contain").classes("w-full h-40 frame")
                    self.checkboxes[img.name] = ui.checkbox(
                        ("✓ " if is_tagged(img) else "") + img.name,
                        value=img.name in state.selected,
                        on_change=lambda e, name=img.name: self._toggle(name, e.value),
                    ).classes("text-xs break-all mono")

        self._shown_failures = 0
        self._sync()
        ui.timer(0.5, self._sync)

    def _model_select(self, label: str, options: list[str], attr: str) -> None:
        current = getattr(state, attr)
        ui.select(list(dict.fromkeys([*options, current])), label=label) \
            .bind_value(state, attr).props("outlined dense").classes("w-64")

    # ── Selection ─────────────────────────────────────────────────────────────

    def _toggle(self, name: str, checked: bool) -> None:
        (state.selected.add if checked else state.selected.discard)(name)

    def _select_all(self, checked: bool) -> None:
        for box in self.checkboxes.values():
            box.set_value(checked)

    def _selected_images(self) -> list[Path]:
        return [img for img in state.images if img.name in state.selected]

    # ── Running ───────────────────────────────────────────────────────────────

    async def _start(self, retag: bool) -> None:
        if state.busy:
            return
        images = self._selected_images()
        if not retag:
            images = [img for img in images if not is_tagged(img)]
        if not images:
            ui.notify("Nothing to tag: select some frames" +
                      ("" if retag else " that are not tagged yet") + ".", type="info")
            return
        self.tag_button.disable()
        try:
            await run.io_bound(ensure_ollama)
        except RuntimeError as e:
            ui.notify(str(e), type="negative", timeout=0, close_button="OK")
            self.tag_button.enable()
            return
        state.job = Job(folder=state.folder, total=len(images))
        # No page context: the run must not be tied to this browser tab.
        background_tasks.create(
            _run_job(state.job, images, state.vision_model, state.text_model, dict(state.roll)),
            name="tagging",
        )
        self._sync()

    def _stop(self) -> None:
        if state.job:
            state.job.stop_requested = True
            state.job.stage = "Stopping after the current frame…"

    def _dismiss(self) -> None:
        state.job = None
        self._sync()

    def _sync(self) -> None:
        """Mirror the job into the UI. Runs twice a second and after every action."""
        job = state.job if state.job and state.job.folder == state.folder else None
        busy = state.busy
        for button in (self.tag_button, self.retag_button, self.untag_button):
            button.set_enabled(not busy)
        self.progress_card.set_visibility(job is not None)
        if job is None:
            return

        self.stop_button.set_visibility(job.running)
        self.dismiss_button.set_visibility(not job.running)
        self.bar.set_value(job.progress)
        for result in job.failed[self._shown_failures:]:
            with self.failures:
                ui.label(f"✗ {result.image.name}: {result.error}").classes("text-negative text-sm")
        self._shown_failures = len(job.failed)

        if job.running:
            self.stage.set_text(job.stage)
            return

        done = len(job.results) - len(job.failed)
        summary = f"Tagged {done} of {job.total} frame{'s' if job.total != 1 else ''}."
        if job.error:
            summary += f" The run stopped with an error: {job.error}"
        elif job.failed:
            summary += f" {len(job.failed)} failed and were left untagged — press Tag untagged to retry."
        elif job.stop_requested:
            summary += " Stopped early."
        self.stage.set_text(summary)

        if not job.acknowledged:
            job.acknowledged = True
            state.reload_folder()
            self.on_finished(not job.failed and not job.error and not job.stop_requested)

    # ── Un-tagging ────────────────────────────────────────────────────────────

    def _confirm_untag(self) -> None:
        targets = [img for img in self._selected_images() if is_tagged(img)]
        if not targets:
            ui.notify("None of the selected frames are tagged.", type="info")
            return
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Delete the metadata sidecars of {len(targets)} frame"
                     f"{'s' if len(targets) != 1 else ''}?").classes("text-lg")
            ui.label("Descriptions, tags and any edits for these frames are lost. "
                     "The images themselves are not touched.").classes("text-grey-7")
            with ui.row().classes("w-full justify-end"):
                ui.button("Cancel", on_click=dialog.close).props("flat")
                ui.button("Delete sidecars", color="negative",
                          on_click=lambda: (dialog.close(), self._untag(targets)))
        dialog.open()

    def _untag(self, targets: list[Path]) -> None:
        for img in targets:
            img.with_suffix(".xmp").unlink(missing_ok=True)
        state.reload_folder()
        ui.notify(f"Removed metadata from {len(targets)} frame(s).")
        self.on_finished(False)
