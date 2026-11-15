"""
contact_gui/settings.py
───────────────────────
Settings dialog behind the gear icon: which models to use, the remembered
options offered in roll info and review, and a way to stop the app.
"""

from collections.abc import Callable

from nicegui import app, ui

from processor.roll import (
    HISTORY_KEYS,
    _history_sorted,
    _load_history,
    _save_history,
    delete_history_entry,
    move_history_entry,
    rename_history_entry,
)

# Landmarks used to be filed under people; these two lists can hand entries to each other.
_MOVE_TARGET = {"subjects": "landmarks", "landmarks": "subjects"}

from .state import state


class SettingsDialog:
    def __init__(self, on_lists_changed: Callable[[], None]) -> None:
        self.on_lists_changed = on_lists_changed  # suggestions elsewhere need a refresh
        self.list_key = "location"
        with ui.dialog() as self.dialog, ui.card().classes("w-[640px] max-w-full"):
            with ui.tabs().props("dense align=left") as tabs:
                ui.tab("models", label="Models")
                ui.tab("lists", label="Remembered options")
            with ui.tab_panels(tabs, value="models").classes("w-full"):
                with ui.tab_panel("models"):
                    self._models()
                with ui.tab_panel("lists"):
                    self._lists()
            ui.separator()
            with ui.row().classes("w-full items-center"):
                ui.button("Quit contact", icon="power_settings_new", on_click=self._quit) \
                    .props("flat color=grey-6")
                ui.space()
                ui.button("Close", on_click=self.dialog.close).props("flat")

    def open(self) -> None:
        self._lists.refresh()
        self.dialog.open()

    # ── Models ────────────────────────────────────────────────────────────────

    def _models(self) -> None:
        ui.label("contact uses models installed in Ollama on this computer. "
                 "Nothing is sent anywhere else.").classes("text-sm text-grey-6")
        self._model_select("Vision model", state.vision_models, "vision_model")
        ui.label("Looks at each frame and writes its description, tags and category. "
                 "It also rewrites a frame when you tell it a fact in review. "
                 "This is the one that matters for quality and speed.") \
            .classes("text-sm text-grey-6")
        self._model_select("Text model", state.all_models, "text_model")
        ui.label("Never sees an image. It only writes the short roll summary from the "
                 "frame descriptions. Using the same model as above is fine and avoids "
                 "loading a second one into memory.").classes("text-sm text-grey-6")
        ui.label("Install another model with `ollama pull <name>`, then reload this page.") \
            .classes("text-xs text-grey-6 mono")

    def _model_select(self, label: str, options: list[str], attr: str) -> None:
        current = getattr(state, attr)
        ui.select(list(dict.fromkeys([*options, current])), label=label,
                  on_change=state.save_models) \
            .bind_value(state, attr).props("outlined dense").classes("w-full")

    # ── Remembered options ────────────────────────────────────────────────────

    @ui.refreshable_method
    def _lists(self) -> None:
        ui.label("What roll info and review offer as suggestions. Renaming an entry to the "
                 "name of another merges them. This only changes suggestions — rolls "
                 "already saved keep what they have.").classes("text-sm text-grey-6")
        ui.toggle(HISTORY_KEYS, value=self.list_key, on_change=self._pick_list) \
            .props("dense flat no-caps")
        history = _load_history()
        entries = _history_sorted(history, self.list_key)
        if not entries:
            ui.label("Nothing remembered yet.").classes("text-sm text-grey-6")
            return
        # Rows are edited and removed in place — rebuilding the list would throw the
        # scroll position back to the top after every change.
        self.rows: dict[str, tuple[ui.row, ui.label]] = {}
        with ui.scroll_area().classes("w-full h-72"):
            for value in entries:
                self._row(value, history[self.list_key][value]["count"])

    def _row(self, value: str, count: int) -> None:
        entry = {"value": value}  # the row's current name; it changes when renamed
        with ui.row().classes("w-full items-center no-wrap gap-2") as row:
            field = ui.input(value=value).props("dense outlined").classes("grow")
            field.on("keydown.enter", lambda: self._rename(entry, field))
            field.on("blur", lambda: self._rename(entry, field))
            count_label = ui.label(f"{count}×").classes("text-xs text-grey-6 mono w-8 text-right")
            target = _MOVE_TARGET.get(self.list_key)
            if target:
                ui.button(icon="place" if target == "landmarks" else "person",
                          on_click=lambda: self._move(entry, target)) \
                    .props("flat dense color=grey-6").tooltip(f"Move to {HISTORY_KEYS[target]}")
            ui.button(icon="delete_outline", on_click=lambda: self._delete(entry)) \
                .props("flat dense color=grey-6").tooltip("Forget this entry")
        self.rows[value] = (row, count_label)

    def _pick_list(self, e) -> None:
        self.list_key = e.value
        self._lists.refresh()

    def _rename(self, entry: dict, field: ui.input) -> None:
        old, new = entry["value"], (field.value or "").strip()
        if not new:
            field.set_value(old)
            return
        if new == old:
            return
        history = _load_history()
        merged = new in history.get(self.list_key, {})
        rename_history_entry(history, self.list_key, old, new)
        _save_history(history)
        row, count_label = self.rows.pop(old)
        if merged:
            # This row disappears into the one it was renamed to
            row.delete()
            self.rows[new][1].set_text(f"{history[self.list_key][new]['count']}×")
            ui.notify(f"Merged “{old}” into “{new}”")
        else:
            entry["value"] = new
            field.set_value(new)
            self.rows[new] = (row, count_label)
        self.on_lists_changed()

    def _move(self, entry: dict, target: str) -> None:
        history = _load_history()
        move_history_entry(history, self.list_key, target, entry["value"])
        _save_history(history)
        self.rows.pop(entry["value"])[0].delete()
        ui.notify(f"Moved “{entry['value']}” to {HISTORY_KEYS[target]}")
        self.on_lists_changed()

    def _delete(self, entry: dict) -> None:
        history = _load_history()
        delete_history_entry(history, self.list_key, entry["value"])
        _save_history(history)
        self.rows.pop(entry["value"])[0].delete()
        self.on_lists_changed()

    # ── Quit ──────────────────────────────────────────────────────────────────

    def _quit(self) -> None:
        if state.busy:
            ui.notify("A tagging run is in progress. Stop it first, or let it finish.",
                      type="warning")
            return
        self.dialog.close()
        with ui.dialog().props("persistent") as stopped, ui.card():
            ui.label("contact has stopped.").classes("text-lg")
            ui.label("You can close this tab.").classes("text-grey-6")
        stopped.open()
        ui.timer(0.5, app.shutdown, once=True)
