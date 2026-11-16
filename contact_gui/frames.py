"""
contact_gui/frames.py
─────────────────────
The frame overlay: one frame at a time, full screen, over whatever it was opened
from — a library search, one roll's frames in the library, or a roll's overview.
Esc (or the browser's back button) returns there exactly as it was.

Two modes, toggled with E and remembered:
  View  the frame as large as possible, with a quiet sheet beside it
  Edit  the same, plus the description to edit, one entry line for facts, tags,
        people, landmarks and the place, and a filmstrip to select several frames

The frames may come from several rolls. Each keeps its own roll: suggestions, the
roll's lists, the contact sheet and the roll summary are always those of the frame's
own roll.
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from nicegui import background_tasks, run, ui

from processor.library import Hit
from processor.orientation import OrientationError, rotate
from processor.pipeline import rebuild_contact_sheet, refresh_roll_summary
from processor.roll import _history_sorted, _load_history, _split_list_field, normalize_name, normalize_place
from processor.sidecar import write_xmp
from processor.tagger import VALID_CATEGORIES, ensure_ollama, refine_frame, sanitize_tags

from .commands import (
    CommandError,
    complete,
    complete_value,
    completions,
    is_command,
    parse_command,
    split_values,
)
from .files import library_thumb_url, thumb_url
from .state import add_to_roll, state

_SAVE_DELAY = 1.0  # seconds of quiet typing before a description is written to disk

# mode → (label shown in the entry line, placeholder, key that opens the line in this mode)
MODES = {
    "fact": ("fact", "Tell the model something about this frame", "f"),
    "tags": ("tags", "keyword, keyword", "t"),
    "people": ("people", "Name, Name", "p"),
    "landmarks": ("landmarks", "Name, Name", "l"),
    "place": ("place", "City, Country", "w"),
}
_MODE_KEYS = {key: mode for mode, (_, _, key) in MODES.items()}
_MAX_CHIPS = 24  # suggestions under the entry line


def frame_url(image: Path, size: int) -> str:
    """Preview URL for a frame in the open roll or anywhere in the library."""
    root = state.library_root
    if root is not None and image.parent.parent == root:
        return library_thumb_url(image, size)
    return thumb_url(image, size)


def _shown(value: str) -> str:
    """How an entry reads in the sheet, where entries are separated by commas: one with
    a comma of its own is quoted, the way it is typed."""
    return f'"{value}"' if "," in value else value


def _values(info: dict, key: str) -> list[str]:
    return _split_list_field(info.get(key, ""))


class FrameOverlay:
    def __init__(self, on_open_roll: Callable[[Path], bool], on_change: Callable[[bool], None],
                 on_closed: Callable[[], None], on_help: Callable[[], None]) -> None:
        self.on_open_roll = on_open_roll  # R: the roll's overview
        self.on_change = on_change        # record the place in the browser history (replace?)
        self.on_closed = on_closed        # the view underneath should show any edits
        self.on_help = on_help
        self.items: list[Hit] = []
        self.index = 0
        self.origin: dict = {}            # what the frames came from, for the history
        self.origin_label = ""
        self.selection: set[int] = set()  # frames selected besides the current one
        self.mode = "fact"                # the entry line's mode, remembered
        self.touched: set[Path] = set()   # rolls edited while open
        self._pushed = False
        self._loading = False
        self._refining = False
        self._save_timer: ui.timer | None = None
        self._undo: list[tuple[int, dict]] = []
        self._anchor = 0  # where a Shift-arrow selection started
        with ui.dialog().props("maximized persistent transition-show=fade "
                               "transition-hide=fade") as self.dialog:
            with ui.element("div").classes("frame-overlay"):
                self._top()
                with ui.element("div").classes("frame-main"):
                    with ui.element("div").classes("frame-stage"):
                        self.image = ui.image().props("fit=contain no-spinner no-transition") \
                            .classes("frame-image")
                    with ui.element("div").classes("frame-side"):
                        self._side()
                self._strip()

    # ── Opening and closing ───────────────────────────────────────────────────

    @property
    def is_open(self) -> bool:
        return bool(self.dialog.value)

    @property
    def editing(self) -> bool:
        return state.frame_edit_mode

    def open(self, items: list[Hit], index: int, origin: dict, label: str,
             edit: bool | None = None) -> None:
        if not items:
            return
        if edit is not None:
            state.frame_edit_mode = edit
        self._set(items, index, origin, label)
        self.dialog.open()
        self._pushed = True
        self.on_change(False)

    def restore(self, items: list[Hit], index: int, origin: dict, label: str) -> None:
        """Reopen at a place from the browser history (back/forward)."""
        if not items:
            self.close(record=False)
            return
        self._set(items, index, origin, label)
        self._pushed = True
        self.dialog.open()

    def _set(self, items: list[Hit], index: int, origin: dict, label: str) -> None:
        self.items, self.origin, self.origin_label = items, origin, label
        self.index = max(0, min(index, len(items) - 1))
        self.selection = set()
        self._undo = []
        self.origin_button.set_text(label or "Back")
        self.mode_toggle.set_value(self.editing)
        self._strip.refresh()
        self._show()

    def close(self, record: bool = True) -> None:
        """Back to where the overlay was opened from. With `record`, through the browser
        history, whose back handler then closes it."""
        if not self.is_open:
            return
        self.save()
        if record and self._pushed:
            self._pushed = False
            ui.run_javascript("history.back()")
            return
        self._pushed = False
        self.dialog.close()
        self._finish_rolls()
        self.on_closed()

    def place(self) -> dict:
        hit = self.items[self.index]
        return {**self.origin, "frame_roll": str(hit.roll.folder), "frame": hit.frame.image.name}

    # ── Layout ────────────────────────────────────────────────────────────────

    def _top(self) -> None:
        """Built once; only its texts change from frame to frame."""
        with ui.row().classes("frame-top w-full items-center no-wrap gap-3"):
            self.origin_button = ui.button("Back", icon="arrow_back",
                                           on_click=lambda: self.close()) \
                .props("flat dense no-caps color=grey-5").classes("frame-origin") \
                .tooltip("Back (Esc)")
            self.roll_link = ui.label().classes("frame-roll cursor-pointer truncate min-w-0") \
                .on("click", self._open_roll).tooltip("Open the roll (R)")
            self.counter = ui.label().classes("mono text-xs text-grey-6 whitespace-nowrap")
            self.selection_label = ui.label().classes(
                "mono text-xs text-primary whitespace-nowrap cursor-pointer"
            ).on("click", self._clear_selection).tooltip("Click or press Esc to clear")
            ui.space()
            self.status = ui.label().classes("mono text-xs text-grey-6 truncate min-w-0")
            ui.button(icon="rotate_left", on_click=lambda: self._rotate(False)) \
                .props("flat round dense size=sm color=grey-6").tooltip("Rotate left ([)")
            ui.button(icon="rotate_right", on_click=lambda: self._rotate(True)) \
                .props("flat round dense size=sm color=grey-6").tooltip("Rotate right (])")
            self.star_button = ui.button(icon="star_border", on_click=self._toggle_star) \
                .props("flat round dense size=sm").tooltip("Favourite (S)")
            self.mode_toggle = ui.toggle({False: "View", True: "Edit"}, value=self.editing,
                                         on_change=lambda e: self._set_editing(bool(e.value))) \
                .props("dense no-caps unelevated toggle-color=transparent toggle-text-color=black") \
                .classes("mode-toggle mx-2").tooltip("E")
            ui.button(icon="help_outline", on_click=self.on_help) \
                .props("flat round dense size=sm color=grey-6").tooltip("Keyboard shortcuts (?)")
            ui.button(icon="close", on_click=lambda: self.close()) \
                .props("flat round dense size=sm color=grey-5").tooltip("Back (Esc)")

    @ui.refreshable_method
    def _side(self) -> None:
        if not self.items:
            return
        hit = self.items[self.index]
        meta = hit.frame.meta
        if not meta:
            ui.label("Not tagged yet.").classes("text-grey-6")
            ui.label("Tag it on the roll's overview (R), then come back to edit.") \
                .classes("text-xs text-grey-6")
            return
        if self.editing:
            self._edit_text(hit)
        else:
            # read-only, but dressed like the field it becomes in Edit, so nothing moves
            with ui.element("div").classes("field-box frame-description"):
                ui.label("Description").classes("field-box-label")
                ui.label(meta.get("description", ""))
        ui.space()
        with ui.column().classes("w-full gap-0 sheet"):
            self._sheet()
            with ui.row().classes("sheet-row w-full items-center no-wrap"):
                ui.label("category").classes("sheet-key")
                if self.editing:
                    self.category = ui.select(sorted(VALID_CATEGORIES),
                                              value=meta.get("category", "other"),
                                              on_change=self._changed_now) \
                        .props("dense borderless options-dense").classes("sheet-select mono")
                else:
                    ui.label(meta.get("category", "other")).classes("sheet-value")

    def _edit_text(self, hit: Hit) -> None:
        meta = hit.frame.meta
        self._loading = True
        self.description = ui.textarea("Description", value=meta.get("description", ""),
                                       on_change=self._changed_typing) \
            .props("outlined").classes("w-full box-fixed").style("--box-h: 8.75rem")
        self._loading = False
        self.description.on("blur", self.save)

        # The one entry line. "fact-field" is what Return and "/" look for (see main.py).
        self.note = ui.input().props("outlined dense").classes("w-full fact-field")
        with self.note.add_slot("prepend"):
            self.mode_label = ui.label().classes("entry-mode")
        with self.note.add_slot("append"):
            notes = meta.get("notes", [])
            if notes:
                with ui.icon("format_list_bulleted", size="xs").classes("text-grey-6"):
                    ui.tooltip("Facts given:\n" + "\n".join(f"• {n}" for n in notes)) \
                        .classes("text-sm max-w-xs whitespace-pre-line")
            if self._undo and not self._refining:
                ui.button(icon="undo", on_click=self._undo_refine) \
                    .props("flat dense round size=sm").tooltip("Undo the last fact")
        # the typed text travels with the key press: the field's own value may not have
        # reached the server yet when Return follows the last keystroke immediately
        self.note.on("keydown.enter", self._apply, js_handler="(e) => emit(e.target.value)")
        self.note.on("keydown.tab.prevent", self._tab,
                     js_handler="(e) => emit({shiftKey: e.shiftKey, value: e.target.value})")
        self.note.on("keydown.backspace", self._backspace, js_handler="(e) => emit(e.target.value)")
        # grows into the free space above the sheet; never scrolls
        with ui.row().classes("w-full items-start content-start gap-1 frame-candidates"):
            self._candidates()
        self._show_mode()

    @ui.refreshable_method
    def _sheet(self) -> None:
        """People, landmarks, place and the tags of the current frame. In Edit, click an entry
        to remove it, or a key to add one."""
        if not self.items:
            return
        hit = self.items[self.index]
        meta = hit.frame.meta
        place, inherited = meta.get("place", ""), False
        if not place:
            place, inherited = hit.roll.place_of(hit.frame), True
        rows = [
            ("people", "people", meta.get("people", [])),
            ("landmarks", "landmarks", meta.get("landmarks", [])),
            ("place", "place", [place] if place else []),
            ("tags", "tags", meta.get("tags", [])),
        ]
        for key, mode, values in rows:
            with ui.row().classes("sheet-row w-full items-start no-wrap"):
                label = ui.label(key).classes("sheet-key")
                if self.editing:
                    label.classes("cursor-pointer").on("click", lambda mode=mode: self._open(mode)) \
                        .tooltip(f"Add {mode} ({MODES[mode][2].upper()})")
                with ui.row().classes("grow gap-x-2 gap-y-0 items-center sheet-values"):
                    if not values:
                        ui.label("—").classes("sheet-empty")
                    for value in values:
                        shown = value if mode == "place" else _shown(value)
                        if not self.editing or (mode == "place" and inherited):
                            ui.label(shown).classes("sheet-value" +
                                                    (" sheet-inherited" if inherited and mode == "place" else ""))
                        else:
                            ui.label(shown).classes("sheet-value sheet-removable") \
                                .on("click", lambda mode=mode, value=value: self._remove(mode, value)) \
                                .tooltip("Click to remove")

    @ui.refreshable_method
    def _candidates(self) -> None:
        if not self.items:
            return
        hit = self.items[self.index]
        meta = hit.frame.meta
        if self.mode == "people":
            self._chips(self._roll_people(), meta.get("people", []), self._set_person, True)
        elif self.mode == "landmarks":
            self._chips(self._roll_landmarks(), meta.get("landmarks", []), self._set_landmark, False)
        elif self.mode == "place":
            current = meta.get("place") or hit.roll.place_of(hit.frame)
            self._chips(self._known_places()[:8], [current],
                        lambda place, on: self._set_place(place if on else ""), False)

    @staticmethod
    def _chips(names: list[str], present: list[str], on_toggle, numbered: bool) -> None:
        """Clickable names under the entry line, in the roll's order (1–9 toggle people
        by it). Past _MAX_CHIPS only the ones on this frame stay; the rest are found by
        typing, Tab completes."""
        if len(names) > _MAX_CHIPS:
            keep = set(names[:_MAX_CHIPS - sum(1 for n in names[_MAX_CHIPS:] if n in present)])
            names = [n for n in names if n in keep or n in present]
        if not names:
            ui.label("Nothing on this roll yet — type a name and press Return") \
                .classes("text-xs text-grey-6")
        for n, name in enumerate(names, 1):
            on = name in present
            chip = ui.chip(name, color="primary" if on else "grey-9", text_color="white",
                           on_click=lambda name=name, on=on: on_toggle(name, not on)) \
                .props("dense square").classes("shrink-0 candidate")
            if numbered and n <= 9:
                chip.tooltip(f"Press {n} to toggle")

    @ui.refreshable_method
    def _strip(self) -> None:
        """The frames of this set, to jump around and select several. Edit only."""
        self.thumbs = []
        if not self.items or not self.editing:
            return
        with ui.row().classes("frame-strip w-full no-wrap gap-3 strip"):
            for i, hit in enumerate(self.items):
                # marked here as well: a refresh is applied after the caller's own updates
                self.thumbs.append(
                    ui.image(frame_url(hit.frame.image, 160)).props("fit=cover")
                    .classes("w-24 h-16 shrink-0 cursor-pointer frame " + self._thumb_classes(i))
                    .on("click", lambda e, i=i: self._strip_click(i, e.args),
                        ["shiftKey", "metaKey", "ctrlKey"])
                    .on("mousedown", js_handler="(e) => { if (e.shiftKey) e.preventDefault(); }")
                )

    # ── Showing a frame ───────────────────────────────────────────────────────

    def _show(self) -> None:
        hit = self.items[self.index]
        self.image.set_source(frame_url(hit.frame.image, 1600))
        self.counter.set_text(f"{self.index + 1} / {len(self.items)} · {hit.frame.image.name}")
        self.roll_link.set_text(hit.roll.label)
        # the roll's name once: the back button already carries it when we came from it
        self.roll_link.set_visibility(hit.roll.label != self.origin_label)
        if not self._refining:
            self.status.set_text("")
        self._side.refresh()
        self._show_selection()
        # get the neighbours ready, so stepping shows them at once
        from .files import warm_previews
        around = {self.items[(self.index + d) % len(self.items)].frame.image for d in (1, -1, 2)}
        background_tasks.create(run.io_bound(warm_previews, list(around), 1600), name="ahead")

    def _thumb_classes(self, i: int) -> str:
        mark = ("frame-current" if i == self.index
                else "frame-selected" if i in self.selection else "frame-dim")
        return mark + (" frame-starred" if self.items[i].frame.meta.get("starred") else "")

    def _show_selection(self) -> None:
        for i, thumb in enumerate(getattr(self, "thumbs", [])):
            thumb.classes(remove="frame-current frame-selected frame-dim frame-starred")
            thumb.classes(add=self._thumb_classes(i))
        if self.thumbs:
            ui.run_javascript(
                f"getHtmlElement({self.thumbs[self.index].id})"
                '?.scrollIntoView({inline: "center", block: "nearest", behavior: "smooth"})'
            )
        n = len(self.selection)
        self.selection_label.set_text(f"+{n} selected" if n else "")
        on = bool(self.items[self.index].frame.meta.get("starred"))
        self.star_button.props(f'icon={"star" if on else "star_border"} '
                               f'color={"primary" if on else "grey-6"}')

    def _set_editing(self, on: bool) -> None:
        if on == self.editing:
            return
        self.save()
        state.frame_edit_mode = on
        self.mode_toggle.set_value(on)
        if not on:
            self.selection.clear()
        self._strip.refresh()
        self._show()

    # ── Keys ──────────────────────────────────────────────────────────────────

    def handle_key(self, e) -> None:
        """Keys pressed while no field has the cursor."""
        if not self.items or not e.action.keydown or e.modifiers.meta or e.modifiers.ctrl:
            return
        key = str(e.key.name)
        if (e.key.arrow_left or e.key.arrow_right) and e.modifiers.shift and self.editing:
            self._extend(-1 if e.key.arrow_left else 1)
        elif e.key.arrow_left:
            self.step(-1)
        elif e.key.arrow_right:
            self.step(1)
        elif key == "Escape":
            if self.selection:
                self._clear_selection()
            else:
                self.close()
        elif key in ("e", "E"):
            self._set_editing(not self.editing)
        elif key in ("s", "S"):
            self._toggle_star()
        elif key in ("r", "R"):
            self._open_roll()
        elif key in ("[", "]"):
            self._rotate(clockwise=key == "]")
        elif key == "Enter" and not self.editing:
            self._set_editing(True)
            if self.items[self.index].frame.meta:
                # the entry line is built by a refresh that lands after this handler, so
                # the focus has to wait for it in the browser
                ui.run_javascript(
                    "(() => { let n = 0; const t = setInterval(() => {"
                    " const f = document.querySelector('.frame-overlay .fact-field input');"
                    " if (f || ++n > 40) { clearInterval(t); f?.focus(); } }, 25); })()"
                )
        elif not self.editing:
            return
        elif key in ("a", "A"):
            self.selection = set(range(len(self.items))) - {self.index}
            self._show_selection()
        elif key.lower() in _MODE_KEYS:
            self._open(_MODE_KEYS[key.lower()])
        elif key in list("123456789"):
            people = self._roll_people()
            n = int(key) - 1
            if n < len(people):
                name = people[n]
                self._set_person(name, name not in self.items[self.index].frame.meta.get("people", []))

    def step(self, by: int) -> None:
        if not self.items:
            return
        self.save()
        self.index = (self.index + by) % len(self.items)
        self.selection.clear()
        self._show()
        self.on_change(True)  # stepping does not add history entries

    def _extend(self, by: int) -> None:
        """Shift-← →: step and select every frame from where the selection started, as in
        a file list. Stepping back towards the start shrinks it again."""
        if not self.selection:
            self._anchor = self.index
        to = self.index + by
        if not 0 <= to < len(self.items):
            return
        self.save()
        self.index = to
        lo, hi = sorted((self._anchor, to))
        self.selection = set(range(lo, hi + 1)) - {to}
        self._show()
        self.on_change(True)

    def _strip_click(self, i: int, args: dict) -> None:
        if args.get("metaKey") or args.get("ctrlKey"):
            self.selection ^= {i}
        elif args.get("shiftKey"):
            lo, hi = sorted((self.index, i))
            self.selection |= set(range(lo, hi + 1))
        else:
            self.save()
            self.index = i
            self.selection.clear()
            self._show()
            self.on_change(True)
            return
        self.selection.discard(self.index)
        self._show_selection()

    def _clear_selection(self) -> None:
        self.selection.clear()
        self._show_selection()

    def _targets(self) -> list[int]:
        """Frames an action applies to: the current one and the selection, if tagged."""
        return [i for i in sorted({self.index, *self.selection}) if self.items[i].frame.meta]

    # ── The entry line ────────────────────────────────────────────────────────

    def _show_mode(self) -> None:
        if not hasattr(self, "note") or self.note.is_deleted:
            return
        label, placeholder, _ = MODES[self.mode]
        self.mode_label.set_text(label)
        self.note.props(f'placeholder="{placeholder}"')
        self._candidates.refresh()
        self.note.set_autocomplete({
            "fact": completions(self._all_people(), self._all_landmarks(), self._known_places()),
            "tags": [],
            "people": self._all_people(),
            "landmarks": self._all_landmarks(),
            "place": self._known_places(),
        }[self.mode])

    def _open(self, mode: str) -> None:
        """Put the cursor in the entry line, in the given mode."""
        if not self.items[self.index].frame.meta:
            return
        self.mode = mode
        self._show_mode()
        if hasattr(self, "note") and not self.note.is_deleted:
            self.note.run_method("focus")

    def _leave(self) -> None:
        """Return applies and hands the keyboard back, so ← → work straight away."""
        self.note.run_method("blur")

    def _tab(self, e) -> None:
        text = (e.args.get("value") if isinstance(e.args, dict) else self.note.value) or ""
        if not text.strip():
            modes = list(MODES)
            step = -1 if e.args.get("shiftKey") else 1
            self.mode = modes[(modes.index(self.mode) + step) % len(modes)]
            self._show_mode()
            return
        if self.mode == "fact":
            completed = complete(text, self._all_people(), self._all_landmarks(),
                                 self._known_places())
        else:
            known = {"people": self._all_people(), "landmarks": self._all_landmarks(),
                     "place": self._known_places(), "tags": []}[self.mode]
            completed = complete_value(text, known, single=self.mode == "place")
        if completed != text:
            self.note.set_value(completed)

    def _backspace(self, e=None) -> None:
        """Backspace on an empty line removes the last entry of the current mode."""
        typed = e.args if e is not None and isinstance(e.args, str) else self.note.value
        if (typed or "") or self.mode == "fact":
            return
        meta = self.items[self.index].frame.meta
        if self.mode == "place":
            if meta.get("place"):
                self._remove("place", meta["place"])
        elif meta.get(self.mode):
            self._remove(self.mode, meta[self.mode][-1])

    async def _apply(self, e=None) -> None:
        typed = e.args if e is not None and isinstance(e.args, str) else self.note.value
        text = (typed or "").strip()
        if not text:
            self._leave()
            return
        if self.mode == "fact":
            if is_command(text):
                self._run_command(text)
            else:
                await self._refine(text)
            return
        if self.mode == "people":
            self._add_people(split_values(text))
        elif self.mode == "landmarks":
            self._add_landmarks(split_values(text))
        elif self.mode == "tags":
            self._add_tags(split_values(text))
        elif self.mode == "place":
            self._set_place(text)
        self.note.set_value("")
        self._leave()

    def _run_command(self, text: str) -> None:
        """A line starting with "/" in fact mode, e.g. "/person Felix". No model involved."""
        try:
            command, values = parse_command(text)
        except CommandError as e:
            ui.notify(str(e), type="warning")
            return
        if command == "person":
            self._add_people(values)
        elif command == "landmark":
            self._add_landmarks(values)
        elif command == "place":
            self._set_place(values[0])
        elif command == "tag":
            self._add_tags(values)
        self.note.set_value("")
        self._leave()

    # ── Suggestions (from the current frame's own roll) ──────────────────────

    def _roll_info(self) -> dict:
        return self.items[self.index].roll.info

    def _roll_people(self) -> list[str]:
        meta = self.items[self.index].frame.meta
        return list(dict.fromkeys([*_values(self._roll_info(), "subjects"), *meta.get("people", [])]))

    def _roll_landmarks(self) -> list[str]:
        meta = self.items[self.index].frame.meta
        return list(dict.fromkeys([*_values(self._roll_info(), "landmarks"),
                                   *meta.get("landmarks", [])]))

    def _all_people(self) -> list[str]:
        return list(dict.fromkeys([*self._roll_people(), *_history_sorted(_load_history(), "subjects")]))

    def _all_landmarks(self) -> list[str]:
        return list(dict.fromkeys([*self._roll_landmarks(),
                                   *_history_sorted(_load_history(), "landmarks")]))

    def _known_places(self) -> list[str]:
        """This roll's locations, places already used on its frames here, then history."""
        roll = self.items[self.index].roll
        used = [h.frame.meta.get("place", "") for h in self.items if h.roll is roll]
        return list(dict.fromkeys(
            p for p in [*roll.locations, *used, *_history_sorted(_load_history(), "location")] if p
        ))

    # ── Saving ────────────────────────────────────────────────────────────────

    def _write(self, i: int, meta: dict, affects_summary: bool = True) -> None:
        hit = self.items[i]
        # Tags stay generic keywords: lowercase, and never a person, landmark or place
        meta = {**meta, "tags": sanitize_tags(meta.get("tags"), self._names(meta),
                                              meta.get("place", ""))}
        write_xmp(hit.frame.image, meta, hit.roll.info)
        hit.frame.meta.clear()
        hit.frame.meta.update(meta)  # the library and the overview share this object
        if affects_summary:
            self.touched.add(hit.roll.folder)
            if hit.roll.folder == state.folder:
                state.edited_since_summary = True
        if i == self.index:
            self._sheet.refresh()
            self._candidates.refresh()
        if not self._refining:
            self.status.set_text(f"Saved {datetime.now():%H:%M:%S}")

    def _changed_now(self) -> None:
        if not self._loading:
            self.save()

    def _changed_typing(self) -> None:
        if self._loading:
            return
        self.status.set_text("Editing…")
        if self._save_timer is not None:
            self._save_timer.cancel()
        self._save_timer = ui.timer(_SAVE_DELAY, self.save, once=True)

    def save(self) -> None:
        """Write the current frame's description and category if they were edited."""
        if not self.items or self._loading or not self.editing:
            return
        if self._save_timer is not None:
            self._save_timer.cancel()
            self._save_timer = None
        meta = self.items[self.index].frame.meta
        if not meta or not hasattr(self, "description") or self.description.is_deleted:
            return
        edited = {**meta, "description": (self.description.value or "").strip()}
        if hasattr(self, "category") and not self.category.is_deleted:
            edited["category"] = self.category.value or "other"
        if all(edited.get(k) == meta.get(k) for k in ("category", "description")):
            return
        self._write(self.index, edited)

    @staticmethod
    def _names(meta: dict) -> list[str]:
        return [*meta.get("people", []), *meta.get("landmarks", [])]

    def _add_to_rolls(self, key: str, values: list[str], targets: list[int]) -> None:
        """New names flow back into the roll info of each frame's own roll."""
        for roll in {id(self.items[i].roll): self.items[i].roll for i in targets}.values():
            if add_to_roll(roll.folder, roll.info, key, values) and roll.folder == state.folder:
                state.reload_folder()

    # ── Favourites and rotation ───────────────────────────────────────────────

    def _toggle_star(self) -> None:
        """Mark the current frame (and the selection) as a favourite, or take it back.
        Shared with the contact sheet, which is rebuilt so its file shows the same stars."""
        targets = self._targets()
        if not targets:
            ui.notify("Tag this frame first — a favourite is saved with its metadata.",
                      type="info")
            return
        on = not self.items[self.index].frame.meta.get("starred")
        for i in targets:
            meta = self.items[i].frame.meta
            if bool(meta.get("starred")) != on:
                self._write(i, {**meta, "starred": on}, affects_summary=False)
        for roll in {id(self.items[i].roll): self.items[i].roll for i in targets}.values():
            rebuild_contact_sheet(roll.folder, roll.info)
        self._show_selection()

    def _rotate(self, clockwise: bool) -> None:
        """Turn the current frame (and the selection) a quarter turn. Only the scan's EXIF
        orientation flag changes, so it shows turned in Finder and Lightroom too."""
        turned, problems = 0, []
        for i in sorted({self.index, *self.selection}):
            image = self.items[i].frame.image
            try:
                rotate(image, clockwise)
                turned += 1
            except (OrientationError, OSError) as e:
                problems.append(f"{image.name}: {e}")
                continue
            if i < len(self.thumbs):
                self.thumbs[i].set_source(frame_url(image, 160))
            if i == self.index:
                self.image.set_source(frame_url(image, 1600))
        if turned:
            self.status.set_text(f"Rotated {turned} frame{'s' if turned != 1 else ''}")
        if problems:
            ui.notify("Could not rotate:\n" + "\n".join(problems), type="warning",
                      multi_line=True)

    # ── People, landmarks, tags and place ─────────────────────────────────────

    def _set_member(self, field: str, roll_key: str | None, name: str, present: bool) -> None:
        self.save()
        targets = self._targets()
        for i in targets:
            meta = self.items[i].frame.meta
            members = [m for m in meta.get(field, []) if m != name]
            if present:
                members.append(name)
            if members != meta.get(field, []):
                self._write(i, {**meta, field: members})
        if present and roll_key:
            self._add_to_rolls(roll_key, [name], targets)
        self._candidates.refresh()

    def _set_person(self, name: str, present: bool) -> None:
        self._set_member("people", "subjects", name, present)

    def _set_landmark(self, name: str, present: bool) -> None:
        self._set_member("landmarks", "landmarks", name, present)

    def _add_people(self, values: list[str]) -> None:
        known = self._all_people()
        for value in values:
            self._set_person(normalize_name(value, known), True)

    def _add_landmarks(self, values: list[str]) -> None:
        known = self._all_landmarks()
        for value in values:
            self._set_landmark(normalize_name(value, known), True)

    def _add_tags(self, values: list[str]) -> None:
        self.save()
        for i in self._targets():
            meta = self.items[i].frame.meta
            self._write(i, {**meta, "tags": [*meta.get("tags", []), *values]})

    def _remove(self, mode: str, value: str) -> None:
        if mode == "people":
            self._set_person(value, False)
        elif mode == "landmarks":
            self._set_landmark(value, False)
        elif mode == "tags":
            self._set_member("tags", None, value, False)
        elif mode == "place":
            self._set_place("")

    def _set_place(self, typed: str) -> None:
        self.save()
        place = normalize_place(typed, self._known_places())
        targets = self._targets()
        for i in targets:
            hit = self.items[i]
            own = place
            if own and len(hit.roll.locations) == 1 and own == hit.roll.locations[0]:
                own = ""  # same as the roll's only location: nothing to store on the frame
            if own != hit.frame.meta.get("place", ""):
                self._write(i, {**hit.frame.meta, "place": own})
        if place:
            self._add_to_rolls("location", [place], targets)
        self._sheet.refresh()
        self._candidates.refresh()

    # ── Refining with the model ───────────────────────────────────────────────

    async def _refine(self, note: str) -> None:  # noqa: C901
        if self._refining:
            return
        self.save()
        self._leave()
        targets = self._targets()
        self._refining = True
        self.note.disable()
        undo: list[tuple[int, dict]] = []
        failed: list[str] = []
        try:
            self.status.set_text("Starting model…")
            await run.io_bound(ensure_ollama)
            for n, i in enumerate(targets, 1):
                hit = self.items[i]
                self.status.set_text(f"Refining {n} / {len(targets)}…")
                info = hit.roll.info
                try:
                    new = await run.io_bound(refine_frame, hit.frame.image, dict(hit.frame.meta),
                                             note, state.vision_model,
                                             _values(info, "location"), _values(info, "subjects"),
                                             _values(info, "landmarks"))
                except Exception as e:
                    failed.append(f"{hit.frame.image.name}: {e}")
                    continue
                undo.append((i, dict(hit.frame.meta)))
                self._write(i, new)
                for key, field in (("location", "place"), ("landmarks", "landmarks")):
                    found = new.get(field) or []
                    found = [found] if isinstance(found, str) else found
                    if found:
                        self._add_to_rolls(key, [v for v in found if v], [i])
        except RuntimeError as e:  # Ollama could not be started
            failed.append(str(e))
        finally:
            self._refining = False
            if not self.note.is_deleted:
                self.note.enable()

        if undo:
            self._undo = undo
        self._show()
        self.status.set_text(f"Refined {len(undo)} frame{'s' if len(undo) != 1 else ''}"
                             if undo else "")
        if failed:
            ui.notify("Could not refine:\n" + "\n".join(failed), type="negative",
                      multi_line=True, timeout=0, close_button="OK")

    def _undo_refine(self) -> None:
        count = len(self._undo)
        for i, old in self._undo:
            self._write(i, old)
        self._undo = []
        self._show()
        self.status.set_text(f"Restored {count} frame{'s' if count != 1 else ''}")

    # ── Leaving ───────────────────────────────────────────────────────────────

    def _open_roll(self) -> None:
        hit = self.items[self.index]
        self.save()
        self.dialog.close()  # stays in the history: back returns to this frame
        if self.on_open_roll(hit.roll.folder):
            self._finish_rolls()
        else:
            self.dialog.open()

    def _finish_rolls(self) -> None:
        """Bring the contact sheet of every edited roll up to date, and its summary in the
        background."""
        touched = [h.roll for h in self.items if h.roll.folder in self.touched]
        rolls = list({id(r): r for r in touched}.values())
        self.touched.clear()
        for roll in rolls:
            rebuild_contact_sheet(roll.folder, roll.info)
        if rolls:
            background_tasks.create(_refresh_summaries(rolls), name="summaries")


async def _refresh_summaries(rolls) -> None:
    try:
        await run.io_bound(ensure_ollama)
    except RuntimeError:
        return
    for roll in rolls:
        try:
            await run.io_bound(refresh_roll_summary, roll.folder, dict(roll.info),
                               state.vision_model, state.text_model)
        except Exception:
            continue
        if roll.folder == state.folder:
            state.reload_folder()
            state.edited_since_summary = False
