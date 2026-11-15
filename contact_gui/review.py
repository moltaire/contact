"""
contact_gui/review.py
─────────────────────
Review step: one frame at a time, edited in place and saved automatically.

Besides editing the model's text by hand, the photographer can
  • tell the model a fact ("this is the Parthenon in Athens") and let it rewrite
    description, tags and category,
  • mark who and which landmarks are in the frame, and
  • set where it was taken.
These apply to the current frame plus any frames selected in the filmstrip
(⌘/Ctrl-click to add one, Shift-click for a range).
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from nicegui import run, ui

from processor.pipeline import tagged_pairs
from processor.roll import normalize_name, normalize_place
from processor.sidecar import write_xmp
from processor.tagger import VALID_CATEGORIES, ensure_ollama, refine_frame, sanitize_tags

from .files import thumb_url
from .state import state

_SAVE_DELAY = 1.0  # seconds of quiet typing before a description is written to disk


class ReviewView:
    def __init__(self, on_roll_changed: Callable[[], None]) -> None:
        self.on_roll_changed = on_roll_changed  # a new person/place was added to roll info
        self.pairs: list[tuple[Path, dict]] = []
        self.index = 0
        self.selection: set[int] = set()  # frames selected in addition to the current one
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
        # navigation sits on top, so nothing moves when a description or tag list is long.
        with ui.row().classes("w-full no-wrap gap-6 items-stretch") \
                .style("height: calc(100vh - 290px); min-height: 590px"):
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
                    self.name = ui.label().classes("mono font-bold truncate")
                    ui.space()
                    self.status = ui.label().classes("text-xs text-grey-6 mono whitespace-nowrap")
                    with ui.icon("help_outline", size="xs").classes("text-grey-6"):
                        ui.tooltip(
                            "Edits are saved automatically. ← → move between frames, "
                            "1–9 toggle people. People, place and facts also apply to frames "
                            "selected in the strip (⌘/Ctrl-click, Shift-click for a range)."
                        ).classes("text-sm max-w-xs")
                # Navigation stays at the top and the fields stack up from the bottom edge
                # of the frame; whatever height is left over becomes air below the navigation.
                # Every box has a fixed size and scrolls inside, so nothing ever moves.
                ui.space()
                self._build_fields()

        with ui.row().classes("w-full items-center gap-2 mt-2"):
            self.selection_label = ui.label().classes("text-xs text-grey-6")
            ui.button("Select all", on_click=self._select_all).props("flat dense size=sm")
            self.clear_button = ui.button("Clear selection", on_click=self._clear_selection) \
                .props("flat dense size=sm")
        with ui.row().classes("w-full no-wrap gap-3 p-2 strip"):
            self.strip = [
                ui.image(thumb_url(img, 160)).props("fit=cover")
                .classes("w-24 h-20 shrink-0 cursor-pointer frame")
                .on("click", lambda e, i=i: self._strip_click(i, e.args),
                    ["shiftKey", "metaKey", "ctrlKey"])
                for i, (img, _) in enumerate(self.pairs)
            ]
        self._show()

    def _build_fields(self) -> None:
        self.category = ui.select(sorted(VALID_CATEGORIES), label="Category",
                                  on_change=self._changed_now) \
            .props("outlined dense").classes("w-full")

        # Five lines of text
        self.description = ui.textarea("Description", on_change=self._changed_typing) \
            .props("outlined").classes("w-full box-fixed").style("--box-h: 8.75rem")
        self.description.on("blur", self.save)

        # Tell the model a fact and let it rewrite description, tags and category
        with ui.column().classes("w-full gap-0"):
            with ui.row().classes("w-full items-center no-wrap gap-2"):
                self.note = ui.input(
                    placeholder="Tell the model a fact, e.g. “this is the Parthenon”"
                ).props("outlined dense").classes("grow")
                self.note.on("keydown.enter", self._refine)
                self.refine_button = ui.button("Refine", on_click=self._refine).props("outline")
                self.undo_button = ui.button(icon="undo", on_click=self._undo_refine) \
                    .props("flat dense").tooltip("Undo the last refine")
            self.notes_label = ui.label().classes("text-xs text-grey-6 truncate w-full h-4 px-1")

        # Two rows of tags
        self.tags = ui.input_chips("Tags", new_value_mode="add-unique",
                                   on_change=self._changed_now) \
            .props("outlined").classes("w-full box-fixed").style("--box-h: 6rem")

        # People and landmarks: one row each, in a box that matches the fields around it.
        # The chips scroll sideways inside their row; the add fields never move.
        with ui.column().classes("w-full gap-1 field-box"):
            self.person_input = self._chip_row("People", self._people_chips, "+ person",
                                               "subjects", self._add_person)
            self.landmark_input = self._chip_row("Landmarks", self._landmark_chips,
                                                 "+ landmark", "landmarks", self._add_landmark)

        self.place = ui.select([], label="Place — City, Country", with_input=True,
                               clearable=True, new_value_mode="add-unique",
                               on_change=self._place_changed) \
            .props("outlined dense").classes("w-full")

    def _chip_row(self, label: str, chips, placeholder: str, history_key: str, on_add) -> ui.input:
        with ui.row().classes("w-full items-center no-wrap gap-2 h-10"):
            ui.label(label).classes("field-box-label w-20 shrink-0")
            with ui.row().classes("grow no-wrap gap-1 items-center strip h-full"):
                chips()
            field = ui.input(placeholder=placeholder,
                             autocomplete=state.suggestions(history_key)) \
                .props("dense borderless input-class=text-right").classes("w-24 shrink-0 text-sm")
            field.on("keydown.enter", on_add)
        return field

    def _chips(self, names: list[str], present: list[str], on_toggle, numbered: bool) -> None:
        for n, name in enumerate(names, 1):
            on = name in present
            chip = ui.chip(name, selectable=True, selected=on,
                           color="primary" if on else "grey-8", text_color="white",
                           on_selection_change=lambda e, name=name: on_toggle(name, e.value)) \
                .classes("shrink-0")
            if numbered and n <= 9:
                chip.tooltip(f"Press {n} to toggle")

    @ui.refreshable_method
    def _people_chips(self) -> None:
        """One toggle per person: the roll's subjects, plus anyone else on this frame."""
        people = self.pairs[self.index][1].get("people", [])
        self.person_names = list(dict.fromkeys([*state.roll_values("subjects"), *people]))
        self._chips(self.person_names, people, self._set_person, numbered=True)

    @ui.refreshable_method
    def _landmark_chips(self) -> None:
        """One toggle per landmark: the roll's landmarks, plus any others on this frame."""
        landmarks = self.pairs[self.index][1].get("landmarks", [])
        self.landmark_names = list(dict.fromkeys([*state.roll_values("landmarks"), *landmarks]))
        self._chips(self.landmark_names, landmarks, self._set_landmark, numbered=False)

    # ── Navigation and selection ──────────────────────────────────────────────

    def go(self, index: int) -> None:
        if not self.pairs or not 0 <= index < len(self.pairs):
            return
        self.save()
        self.index = index
        self.selection.clear()
        self._show()

    def handle_key(self, e) -> None:
        if not self.pairs or not e.action.keydown or e.modifiers.meta or e.modifiers.ctrl:
            return
        if e.key.arrow_left:
            self.go(self.index - 1)
        elif e.key.arrow_right:
            self.go(self.index + 1)
        elif str(e.key.name) in list("123456789"):
            n = int(str(e.key.name)) - 1
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
        """Frames that people, place and refine apply to: the current one and the selection."""
        return sorted({self.index, *self.selection})

    # ── Display ───────────────────────────────────────────────────────────────

    def _show(self) -> None:
        """Load the current frame into the existing elements — nothing is rebuilt."""
        img, meta = self.pairs[self.index]
        self._loading = True
        self.image.set_source(thumb_url(img, 1600))
        self.name.set_text(img.name)
        self.category.set_value(meta.get("category", "other"))
        self.description.set_value(meta.get("description", ""))
        self.tags.set_value(list(meta.get("tags", [])))
        # A frame without its own place shows the roll's, when the roll has exactly one
        self.place.set_options(self._known_places(),
                               value=meta.get("place") or self._roll_place() or None)
        self._loading = False
        notes = meta.get("notes", [])
        self.notes_label.set_text("Facts given: " + " · ".join(notes) if notes else "")
        self._people_chips.refresh()
        self._landmark_chips.refresh()
        self.counter.set_text(f"{self.index + 1} / {len(self.pairs)}")
        self.prev_button.set_enabled(self.index > 0)
        self.next_button.set_enabled(self.index < len(self.pairs) - 1)
        self.undo_button.set_enabled(bool(self._undo) and not self._refining)
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
        n = len(self.selection)
        self.selection_label.set_text(
            f"{n + 1} frames selected — people, place and facts apply to all of them." if n
            else "⌘/Ctrl-click or Shift-click frames to work on several at once."
        )
        self.clear_button.set_visibility(bool(n))

    # ── Saving hand edits ─────────────────────────────────────────────────────

    def _write(self, i: int, meta: dict) -> None:
        img = self.pairs[i][0]
        # Tags stay generic keywords: lowercase, and never a person or place of the frame
        meta = {**meta, "tags": sanitize_tags(meta.get("tags"), self._names(meta),
                                              meta.get("place", ""))}
        write_xmp(img, meta, state.roll)
        self.pairs[i] = (img, meta)
        state.edited_since_summary = True
        if i == self.index and meta["tags"] != list(self.tags.value or []):
            was_loading, self._loading = self._loading, True
            self.tags.set_value(list(meta["tags"]))
            self._loading = was_loading
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
        """Write the current frame's sidecar if category, description or tags changed."""
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
            "tags": sanitize_tags(self.tags.value, self._names(meta), meta.get("place", "")),
        }
        if all(edited[k] == meta.get(k) for k in ("category", "description", "tags")):
            return
        self._write(self.index, edited)

    # ── People, landmarks and place ───────────────────────────────────────────

    @staticmethod
    def _names(meta: dict) -> list[str]:
        return [*meta.get("people", []), *meta.get("landmarks", [])]

    def _set_member(self, field: str, roll_key: str, name: str, present: bool) -> None:
        """Add or remove a person or landmark on the current frame and the selection."""
        self.save()
        for i in self._targets():
            meta = self.pairs[i][1]
            members = [m for m in meta.get(field, []) if m != name]
            if present:
                members.append(name)
            if members != meta.get(field, []):
                self._write(i, {**meta, field: members})
        if present and state.add_roll_values(roll_key, [name]):
            self.on_roll_changed()

    def _set_person(self, name: str, present: bool) -> None:
        self._set_member("people", "subjects", name, present)
        self._people_chips.refresh()

    def _set_landmark(self, name: str, present: bool) -> None:
        self._set_member("landmarks", "landmarks", name, present)
        self._landmark_chips.refresh()

    def _add_person(self) -> None:
        name = normalize_name(self.person_input.value or "",
                              [*self.person_names, *state.suggestions("subjects")])
        self.person_input.set_value("")
        if name:
            self._set_person(name, True)

    def _add_landmark(self) -> None:
        name = normalize_name(self.landmark_input.value or "",
                              [*self.landmark_names, *state.suggestions("landmarks")])
        self.landmark_input.set_value("")
        if name:
            self._set_landmark(name, True)

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

    def _add_places_to_roll(self, places: list[str]) -> None:
        if state.add_roll_values("location", [p for p in places if p]):
            self.on_roll_changed()

    def _place_changed(self) -> None:
        if self._loading:
            return
        self.save()
        place = normalize_place(self.place.value or "", self._known_places())
        if place == self._roll_place():
            place = ""  # same as the roll's only location: nothing to store on the frame
        for i in self._targets():
            meta = self.pairs[i][1]
            if place != meta.get("place", ""):
                self._write(i, {**meta, "place": place})
        self._add_places_to_roll([place])
        # Show the tidied spelling and drop whatever was typed from the suggestions
        self._loading = True
        self.place.set_options(self._known_places(), value=place or self._roll_place() or None)
        self._loading = False

    # ── Refining with the model ───────────────────────────────────────────────

    async def _refine(self) -> None:
        note = (self.note.value or "").strip()
        if not note or self._refining:
            return
        self.save()
        targets = self._targets()
        self._refining = True
        self.refine_button.disable()
        self.undo_button.disable()
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
            self.refine_button.enable()

        if undo:
            self._undo = undo
            self.note.set_value("")
            refined = [self.pairs[i][1] for i, _ in undo]
            self._add_places_to_roll([m.get("place", "") for m in refined])
            landmarks = [name for m in refined for name in m.get("landmarks", [])]
            if state.add_roll_values("landmarks", landmarks):
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
