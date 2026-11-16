"""
contact_gui/review.py
─────────────────────
Review step: one frame at a time, edited in place and saved automatically.

The editing column has three parts:
  • the description, edited by hand,
  • one entry line for everything else, and
  • a sheet listing what is on the frame: who, what, where, tags, category.

The entry line works in one of five modes — fact, tags, people, landmarks, place.
Tab switches mode while the line is empty; Return applies and leaves the line.
In fact mode the text goes to the model, which rewrites description, tags and
category; in the other modes it sets the field directly.

Everything entered there applies to the current frame plus any frames selected in
the filmstrip (⌘/Ctrl-click to add one, Shift-click for a range).
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from nicegui import run, ui

from processor.pipeline import rebuild_contact_sheet, tagged_pairs
from processor.roll import normalize_name, normalize_place
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
from .files import thumb_url
from .state import state

_SAVE_DELAY = 1.0  # seconds of quiet typing before a description is written to disk
# Everything on the review screen that is not the frame: header, paddings and the
# filmstrip. The frame takes the rest of the window, so the screen fits exactly.
_CHROME_HEIGHT = 223

# mode → (label shown in the entry line, placeholder, key that opens the line in this mode)
MODES = {
    "fact": ("fact", "Tell the model something about this frame", "f"),
    "tags": ("tags", "keyword, keyword", "t"),
    "people": ("people", "Name, Name", "p"),
    "landmarks": ("landmarks", "Name, Name", "l"),
    "place": ("place", "City, Country", "w"),
}
_MODE_KEYS = {key: mode for mode, (_, _, key) in MODES.items()}
_HINTS = {
    "fact": "Return sends this to the model · Tab switches to tags, people, landmarks, place",
    "tags": "Several with commas — \"quotes\" keep a comma inside one tag · "
            "Backspace on an empty line removes the last tag",
}


def _shown(value: str) -> str:
    """How an entry reads in the sheet, where entries are separated by commas: one with
    a comma of its own is quoted, the way it is typed."""
    return f'"{value}"' if "," in value else value


class ReviewView:
    def __init__(self, on_roll_changed: Callable[[], None], on_help: Callable[[], None]) -> None:
        self.on_roll_changed = on_roll_changed  # a new person/place was added to roll info
        self.on_help = on_help  # show the keyboard shortcuts
        self.pairs: list[tuple[Path, dict]] = []
        self.index = 0
        self.selection: set[int] = set()  # frames selected in addition to the current one
        self.mode = "fact"  # remembered from frame to frame
        self.person_names: list[str] = []
        self.landmark_names: list[str] = []
        self._loading = False
        self._refining = False
        self._save_timer: ui.timer | None = None
        self._undo: list[tuple[int, dict]] = []  # metadata as it was before the last refine

    # ── Build ─────────────────────────────────────────────────────────────────

    @ui.refreshable_method
    def render(self) -> None:
        self.pairs = tagged_pairs(state.folder) if state.folder else []
        self._save_timer = None
        self._undo = []
        self.selection = set()
        if not self.pairs:
            ui.label("No tagged frames yet. Tag some in the Tagging step first.") \
                .classes("text-grey-7")
            return
        self.index = min(self.index, len(self.pairs) - 1)

        # Fixed geometry: the image and the editing column have the same height and the
        # navigation sits on top, so nothing moves from one frame to the next.
        with ui.row().classes("w-full no-wrap gap-6 items-stretch") \
                .style(f"height: calc(100vh - {_CHROME_HEIGHT}px); min-height: 610px"):
            self.image = ui.image().props("fit=contain").classes("w-3/5 h-full frame")
            with ui.column().classes("w-2/5 h-full gap-2 no-wrap overflow-auto"):
                with ui.row().classes("w-full items-center no-wrap"):
                    self.prev_button = ui.button(icon="arrow_back",
                                                 on_click=lambda: self.go(self.index - 1)) \
                        .props("outline").tooltip("Previous frame (←)")
                    self.next_button = ui.button(icon="arrow_forward",
                                                 on_click=lambda: self.go(self.index + 1)) \
                        .props("outline").tooltip("Next frame (→)")
                    self.counter = ui.label().classes("mono text-grey-7 whitespace-nowrap")
                    self.name = ui.label().classes("mono font-bold whitespace-nowrap")
                    # how many frames are selected besides this one; click to clear
                    self.selection_label = ui.label().classes(
                        "mono text-xs text-primary whitespace-nowrap cursor-pointer"
                    ).on("click", self._clear_selection).tooltip("Click or press Esc to clear")
                    ui.space()
                    self.status = ui.label().classes("text-xs text-grey-6 mono truncate min-w-0")
                    self.star_button = ui.button(icon="star_border", on_click=self._toggle_star) \
                        .props("flat round dense size=sm").tooltip("Favourite (S)")
                    ui.button(icon="help_outline", on_click=self.on_help) \
                        .props("flat round dense size=sm color=grey-6") \
                        .tooltip("Keyboard shortcuts (?)")
                # Top edge: navigation. Bottom edge: the sheet, level with the bottom of the
                # frame. The leftover height is split evenly above the text and the sheet.
                ui.space()
                self._build_text()
                ui.space()
                self._build_sheet()

        with ui.row().classes("w-full no-wrap gap-3 p-2 strip -mt-2"):
            self.strip = [
                ui.image(thumb_url(img, 160)).props("fit=cover")
                .classes("w-24 h-20 shrink-0 cursor-pointer frame")
                .on("click", lambda e, i=i: self._strip_click(i, e.args),
                    ["shiftKey", "metaKey", "ctrlKey"])
                # a shift-click must select frames, not a stretch of the page's text
                .on("mousedown", js_handler="(e) => { if (e.shiftKey) e.preventDefault(); }")
                for i, (img, _) in enumerate(self.pairs)
            ]
        self._show()

    def _build_text(self) -> None:
        # Five lines of text
        self.description = ui.textarea("Description", on_change=self._changed_typing) \
            .props("outlined").classes("w-full box-fixed").style("--box-h: 8.75rem")
        self.description.on("blur", self.save)

        # The one entry line. "fact-field" is what Return and "/" look for (see main.py).
        self.note = ui.input().props("outlined dense").classes("w-full fact-field")
        with self.note.add_slot("prepend"):
            self.mode_label = ui.label().classes("entry-mode")
        with self.note.add_slot("append"):
            # Facts already given to the model, and undo for the last one
            with ui.icon("format_list_bulleted", size="xs").classes("text-grey-6") \
                    as self.notes_icon:
                self.notes_tip = ui.tooltip("").classes("text-sm max-w-xs whitespace-pre-line")
            self.undo_button = ui.button(icon="undo", on_click=self._undo_refine) \
                .props("flat dense round size=sm").tooltip("Undo the last fact")
        self.note.on("keydown.enter", self._apply)
        # Tab switches mode on an empty line and completes a name otherwise
        self.note.on("keydown.tab.prevent", self._tab, ["shiftKey"])
        self.note.on("keydown.backspace", self._backspace)

        # What the current mode offers: the roll's people, landmarks or places to click
        # Room for three rows of chips; they wrap instead of scrolling sideways
        with ui.row().classes("w-full items-start content-start gap-1 overflow-y-auto") \
                .style("height: 5.25rem"):
            self._candidates()

    def _build_sheet(self) -> None:
        with ui.column().classes("w-full gap-0 sheet"):
            self._sheet()
            with ui.row().classes("sheet-row w-full items-center no-wrap"):
                ui.label("category").classes("sheet-key")
                self.category = ui.select(sorted(VALID_CATEGORIES), on_change=self._changed_now) \
                    .props("dense borderless options-dense").classes("sheet-select mono")

    @ui.refreshable_method
    def _sheet(self) -> None:
        """Who, what, where and the tags of the current frame. Click an entry to remove it."""
        meta = self.pairs[self.index][1]
        place, inherited = meta.get("place", ""), False
        if not place:
            place, inherited = self._roll_place(), True
        rows = [
            ("who", "people", meta.get("people", []), "h-7"),
            ("what", "landmarks", meta.get("landmarks", []), "h-7"),
            ("where", "place", [place] if place else [], "h-7"),
            ("tags", "tags", meta.get("tags", []), "h-14"),
        ]
        for key, mode, values, height in rows:
            with ui.row().classes(f"sheet-row w-full items-start no-wrap {height}"):
                ui.label(key).classes("sheet-key cursor-pointer") \
                    .on("click", lambda mode=mode: self._open(mode)) \
                    .tooltip(f"Add {mode} ({MODES[mode][2].upper()})")
                # values carry their own trailing comma (CSS), so a wrapped line never
                # starts or ends with a stray separator
                with ui.row().classes("grow gap-x-2 gap-y-0 items-center overflow-auto h-full sheet-values"):
                    if not values:
                        ui.label("—").classes("sheet-empty")
                    for value in values:
                        if mode == "place" and inherited:
                            ui.label(value).classes("sheet-value sheet-inherited") \
                                .tooltip("From the roll's location")
                        else:
                            ui.label(value if mode == "place" else _shown(value)) \
                                .classes("sheet-value sheet-removable") \
                                .on("click", lambda mode=mode, value=value: self._remove(mode, value)) \
                                .tooltip("Click to remove")

    @ui.refreshable_method
    def _candidates(self) -> None:
        meta = self.pairs[self.index][1]
        if self.mode == "people":
            self._candidate_chips(self.person_names, meta.get("people", []), self._set_person, True)
        elif self.mode == "landmarks":
            self._candidate_chips(self.landmark_names, meta.get("landmarks", []),
                                  self._set_landmark, False)
        elif self.mode == "place":
            current = meta.get("place") or self._roll_place()
            self._candidate_chips(self._known_places()[:8], [current],
                                  lambda place, on: self._set_place(place if on else ""), False)
        else:
            ui.label(_HINTS[self.mode]).classes("text-xs text-grey-6")

    @staticmethod
    def _candidate_chips(names: list[str], present: list[str], on_toggle, numbered: bool) -> None:
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

    # ── Navigation and selection ──────────────────────────────────────────────

    def go(self, index: int) -> None:
        if not self.pairs or not 0 <= index < len(self.pairs):
            return
        self.save()
        self.index = index
        self.selection.clear()
        self._show()

    def handle_key(self, e) -> None:
        """Keys pressed while no field has the cursor."""
        if not self.pairs or not e.action.keydown or e.modifiers.meta or e.modifiers.ctrl:
            return
        key = str(e.key.name)
        if e.key.arrow_left:
            self.go(self.index - 1)
        elif e.key.arrow_right:
            self.go(self.index + 1)
        elif key in ("a", "A"):
            self._select_all()
        elif key in ("s", "S"):
            self._toggle_star()
        elif key == "Escape":
            self._clear_selection()
        elif key.lower() in _MODE_KEYS:
            self._open(_MODE_KEYS[key.lower()])
        elif key in list("123456789"):
            n = int(key) - 1
            if n < len(self.person_names):
                name = self.person_names[n]
                self._set_person(name, name not in self.pairs[self.index][1].get("people", []))

    def _strip_click(self, i: int, args: dict) -> None:
        if args.get("metaKey") or args.get("ctrlKey"):
            self.selection ^= {i}
        elif args.get("shiftKey"):
            lo, hi = sorted((self.index, i))
            self.selection |= set(range(lo, hi + 1))
        else:
            self.go(i)
            return
        self.selection.discard(self.index)
        self._show_selection()

    def _select_all(self) -> None:
        self.selection = set(range(len(self.pairs))) - {self.index}
        self._show_selection()

    def _clear_selection(self) -> None:
        self.selection.clear()
        self._show_selection()

    def _targets(self) -> list[int]:
        """Frames an entry applies to: the current one and the selection."""
        return sorted({self.index, *self.selection})

    # ── Display ───────────────────────────────────────────────────────────────

    def _show(self) -> None:
        """Load the current frame into the existing elements."""
        img, meta = self.pairs[self.index]
        self.person_names = list(dict.fromkeys(
            [*state.roll_values("subjects"), *meta.get("people", [])]))
        self.landmark_names = list(dict.fromkeys(
            [*state.roll_values("landmarks"), *meta.get("landmarks", [])]))
        self._loading = True
        self.image.set_source(thumb_url(img, 1600))
        self.name.set_text(img.name)
        self.category.set_value(meta.get("category", "other"))
        self.description.set_value(meta.get("description", ""))
        self._loading = False
        notes = meta.get("notes", [])
        self.notes_icon.set_visibility(bool(notes))
        self.notes_tip.set_text("Facts given:\n" + "\n".join(f"• {n}" for n in notes))
        self._sheet.refresh()
        self._show_mode()
        self.counter.set_text(f"{self.index + 1} / {len(self.pairs)}")
        self.prev_button.set_enabled(self.index > 0)
        self.next_button.set_enabled(self.index < len(self.pairs) - 1)
        self.undo_button.set_visibility(bool(self._undo) and not self._refining)
        if not self._refining:
            self.status.set_text("")
        self._show_selection()
        # Centre the current frame in the strip. There is no Python API for scrolling a
        # plain container, hence the one line of JavaScript.
        ui.run_javascript(
            f"getHtmlElement({self.strip[self.index].id})"
            '?.scrollIntoView({inline: "center", block: "nearest", behavior: "smooth"})'
        )

    def _show_selection(self) -> None:
        for i, thumb in enumerate(self.strip):
            thumb.classes(remove="frame-current frame-selected frame-dim")
            thumb.classes(add="frame-current" if i == self.index
                          else "frame-selected" if i in self.selection else "frame-dim")
            thumb.classes(add="frame-starred" if self.pairs[i][1].get("starred") else "",
                          remove="" if self.pairs[i][1].get("starred") else "frame-starred")
        n = len(self.selection)
        self.selection_label.set_text(f"+{n} selected" if n else "")
        on = bool(self.pairs[self.index][1].get("starred"))
        self.star_button.props(f'icon={"star" if on else "star_border"} '
                               f'color={"primary" if on else "grey-6"}')

    # ── The entry line ────────────────────────────────────────────────────────

    def _show_mode(self) -> None:
        label, placeholder, _ = MODES[self.mode]
        self.mode_label.set_text(label)
        self.note.props(f'placeholder="{placeholder}"')
        self._candidates.refresh()
        # Inline completion as you type (→ or Tab accepts)
        self.note.set_autocomplete({
            "fact": completions(self._all_people(), self._all_landmarks(), self._known_places()),
            "tags": [],
            "people": self._all_people(),
            "landmarks": self._all_landmarks(),
            "place": self._known_places(),
        }[self.mode])

    def _set_mode(self, mode: str) -> None:
        self.mode = mode
        self._show_mode()

    def _open(self, mode: str) -> None:
        """Put the cursor in the entry line, in the given mode."""
        self._set_mode(mode)
        self.note.run_method("focus")

    def _leave(self) -> None:
        """Return applies and hands the keyboard back, so ← → work straight away."""
        self.note.run_method("blur")

    def _all_people(self) -> list[str]:
        return list(dict.fromkeys([*self.person_names, *state.suggestions("subjects")]))

    def _all_landmarks(self) -> list[str]:
        return list(dict.fromkeys([*self.landmark_names, *state.suggestions("landmarks")]))

    def _tab(self, e) -> None:
        text = self.note.value or ""
        if not text.strip():
            modes = list(MODES)
            step = -1 if e.args.get("shiftKey") else 1
            self._set_mode(modes[(modes.index(self.mode) + step) % len(modes)])
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

    def _backspace(self) -> None:
        """Backspace on an empty line removes the last entry of the current mode."""
        if (self.note.value or "") or self.mode == "fact":
            return
        meta = self.pairs[self.index][1]
        if self.mode == "place":
            if meta.get("place"):
                self._remove("place", meta["place"])
        elif meta.get(self.mode):
            self._remove(self.mode, meta[self.mode][-1])

    async def _apply(self) -> None:
        text = (self.note.value or "").strip()
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

    # ── Saving hand edits ─────────────────────────────────────────────────────

    def _toggle_star(self) -> None:
        """Mark the current frame (and the selection) as a favourite, or take it back.

        Shared with the contact sheet, which is rebuilt so its file shows the same stars.
        """
        on = not self.pairs[self.index][1].get("starred")
        for i in self._targets():
            meta = self.pairs[i][1]
            if bool(meta.get("starred")) != on:
                self._write(i, {**meta, "starred": on}, affects_summary=False)
        rebuild_contact_sheet(state.folder, state.roll)
        self._show_selection()

    def _write(self, i: int, meta: dict, affects_summary: bool = True) -> None:
        img = self.pairs[i][0]
        # Tags stay generic keywords: lowercase, and never a person, landmark or place
        meta = {**meta, "tags": sanitize_tags(meta.get("tags"), self._names(meta),
                                              meta.get("place", ""))}
        write_xmp(img, meta, state.roll)
        self.pairs[i] = (img, meta)
        state.edited_since_summary = state.edited_since_summary or affects_summary
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
        """Write the current frame's sidecar if the description or category changed."""
        if not self.pairs or self._loading:
            return
        if self._save_timer is not None:
            self._save_timer.cancel()
            self._save_timer = None
        meta = self.pairs[self.index][1]
        edited = {
            **meta,
            "category": self.category.value or "other",
            "description": (self.description.value or "").strip(),
        }
        if all(edited[k] == meta.get(k) for k in ("category", "description")):
            return
        self._write(self.index, edited)

    # ── People, landmarks, tags and place ─────────────────────────────────────

    @staticmethod
    def _names(meta: dict) -> list[str]:
        return [*meta.get("people", []), *meta.get("landmarks", [])]

    def _set_member(self, field: str, roll_key: str | None, name: str, present: bool) -> None:
        """Add or remove one entry of a list field on the current frame and the selection."""
        self.save()
        for i in self._targets():
            meta = self.pairs[i][1]
            members = [m for m in meta.get(field, []) if m != name]
            if present:
                members.append(name)
            if members != meta.get(field, []):
                self._write(i, {**meta, field: members})
        if present and roll_key and state.add_roll_values(roll_key, [name]):
            self.on_roll_changed()

    def _set_person(self, name: str, present: bool) -> None:
        self._set_member("people", "subjects", name, present)
        self._refresh_names()

    def _set_landmark(self, name: str, present: bool) -> None:
        self._set_member("landmarks", "landmarks", name, present)
        self._refresh_names()

    def _refresh_names(self) -> None:
        """The roll's lists may have grown; show the new candidates."""
        meta = self.pairs[self.index][1]
        self.person_names = list(dict.fromkeys(
            [*state.roll_values("subjects"), *meta.get("people", [])]))
        self.landmark_names = list(dict.fromkeys(
            [*state.roll_values("landmarks"), *meta.get("landmarks", [])]))
        self._candidates.refresh()

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
            meta = self.pairs[i][1]
            self._write(i, {**meta, "tags": [*meta.get("tags", []), *values]})

    def _remove(self, mode: str, value: str) -> None:
        """Take an entry off the current frame and the selection."""
        if mode == "people":
            self._set_person(value, False)
        elif mode == "landmarks":
            self._set_landmark(value, False)
        elif mode == "tags":
            self._set_member("tags", None, value, False)
        elif mode == "place":
            self._set_place("")

    def _roll_place(self) -> str:
        locations = state.roll_values("location")
        return locations[0] if len(locations) == 1 else ""

    def _known_places(self) -> list[str]:
        """Suggestions, most relevant first: this roll's locations, places already used
        on its frames, then locations from earlier rolls."""
        used = [meta.get("place", "") for _, meta in self.pairs]
        return list(dict.fromkeys(
            p for p in [*state.roll_values("location"), *used, *state.suggestions("location")] if p
        ))

    def _set_place(self, typed: str) -> None:
        self.save()
        place = normalize_place(typed, self._known_places())
        if place == self._roll_place():
            place = ""  # same as the roll's only location: nothing to store on the frame
        for i in self._targets():
            meta = self.pairs[i][1]
            if place != meta.get("place", ""):
                self._write(i, {**meta, "place": place})
        if place and state.add_roll_values("location", [place]):
            self.on_roll_changed()
        self._sheet.refresh()
        self._candidates.refresh()

    # ── Refining with the model ───────────────────────────────────────────────

    async def _refine(self, note: str) -> None:
        if self._refining:
            return
        self.save()
        self._leave()
        targets = self._targets()
        self._refining = True
        self.note.disable()
        self.undo_button.set_visibility(False)
        undo: list[tuple[int, dict]] = []
        failed: list[str] = []
        try:
            self.status.set_text("Starting model…")
            await run.io_bound(ensure_ollama)
            for n, i in enumerate(targets, 1):
                img, meta = self.pairs[i]
                self.status.set_text(f"Refining {n} / {len(targets)}…")
                try:
                    new = await run.io_bound(refine_frame, img, meta, note, state.vision_model,
                                             state.roll_values("location"),
                                             state.roll_values("subjects"),
                                             state.roll_values("landmarks"))
                except Exception as e:
                    failed.append(f"{img.name}: {e}")
                    continue
                undo.append((i, meta))
                self._write(i, new)
                if i == self.index:
                    self._show()
        except RuntimeError as e:  # Ollama could not be started
            failed.append(str(e))
        finally:
            self._refining = False
            self.note.enable()

        if undo:
            self._undo = undo
            self.note.set_value("")
            refined = [self.pairs[i][1] for i, _ in undo]
            changed = state.add_roll_values("location", [m.get("place", "") for m in refined])
            landmarks = [name for m in refined for name in m.get("landmarks", [])]
            if state.add_roll_values("landmarks", landmarks) or changed:
                self.on_roll_changed()
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
