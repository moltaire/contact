"""
contact_gui/review.py
─────────────────────
Review step: one frame at a time, edited in place and saved automatically.

Besides editing the model's text by hand, the photographer can
  • tell the model a fact ("this is the Parthenon in Athens") and let it rewrite
    description, tags and category,
  • mark who is in the frame, and
  • set where it was taken.
These three apply to the current frame plus any frames selected in the filmstrip
(⌘/Ctrl-click to add one, Shift-click for a range).
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from nicegui import run, ui

from processor.pipeline import tagged_pairs
from processor.roll import complete_place, normalize_name, normalize_place, place_region
from processor.sidecar import write_xmp
from processor.tagger import VALID_CATEGORIES, ensure_ollama, refine_frame

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
                .style("height: calc(100vh - 290px); min-height: 540px"):
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
                # Every box below has a fixed size and scrolls inside, so the column
                # never changes height from one frame to the next.
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
        self.description = ui.textarea("Description", on_change=self._changed_typing) \
            .props("outlined").classes("w-full box-fixed").style("--box-h: 8rem")
        self.description.on("blur", self.save)

        # Tell the model a fact and let it rewrite description, tags and category
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            self.note = ui.input(placeholder="Tell the model a fact, e.g. “this is the Parthenon”") \
                .props("outlined dense").classes("grow")
            self.note.on("keydown.enter", self._refine)
            self.refine_button = ui.button("Refine", on_click=self._refine).props("outline")
            self.undo_button = ui.button(icon="undo", on_click=self._undo_refine) \
                .props("flat dense").tooltip("Undo the last refine")
        self.notes_label = ui.label().classes("text-xs text-grey-6 truncate w-full h-4 -mt-1")

        self.tags = ui.input_chips("Tags (type and press Enter)", new_value_mode="add-unique",
                                   on_change=self._changed_now) \
            .props("outlined").classes("w-full box-fixed").style("--box-h: 5.5rem")

        with ui.column().classes("w-full gap-0"):
            # The input sits in the heading row, outside the scrolling chip area,
            # so it stays reachable however many names there are.
            with ui.row().classes("w-full items-center no-wrap h-7"):
                ui.label("People in this frame").classes("text-xs text-grey-6")
                ui.space()
                self.person_input = ui.input(placeholder="Add person…",
                                             autocomplete=state.suggestions("subjects")) \
                    .props("dense borderless input-class=text-right").classes("w-40 text-sm")
                self.person_input.on("keydown.enter", self._add_person)
            with ui.row().classes("w-full items-center gap-1 h-14 overflow-auto content-start"):
                self._people_chips()

        self.place = ui.select([], label="Place — Local place, City, Country", with_input=True,
                               clearable=True, new_value_mode="add-unique",
                               on_change=self._place_changed) \
            .props("outlined dense").classes("w-full")

    @ui.refreshable_method
    def _people_chips(self) -> None:
        """One toggle per person: the roll's subjects, plus anyone else on this frame."""
        people = self.pairs[self.index][1].get("people", [])
        self.person_names = list(dict.fromkeys([*state.roll_values("subjects"), *people]))
        for n, name in enumerate(self.person_names, 1):
            on = name in people
            chip = ui.chip(name, selectable=True, selected=on,
                           color="primary" if on else "grey-7", text_color="white",
                           on_selection_change=lambda e, name=name: self._set_person(name, e.value))
            if n <= 9:
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
        self.place.set_options(self._known_places(), value=meta.get("place") or None)
        self._loading = False
        notes = meta.get("notes", [])
        self.notes_label.set_text("Facts given: " + " · ".join(notes) if notes else "")
        self._people_chips.refresh()
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
        write_xmp(img, meta, state.roll)
        self.pairs[i] = (img, meta)
        state.edited_since_summary = True
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
            # Kept as typed: proper names in tags need their capitals
            "tags": [t.strip() for t in (self.tags.value or []) if t.strip()],
        }
        if all(edited[k] == meta.get(k) for k in ("category", "description", "tags")):
            return
        self._write(self.index, edited)

    # ── People and place ──────────────────────────────────────────────────────

    def _set_person(self, name: str, present: bool) -> None:
        self.save()
        for i in self._targets():
            meta = self.pairs[i][1]
            people = [p for p in meta.get("people", []) if p != name]
            if present:
                people.append(name)
            if people != meta.get("people", []):
                self._write(i, {**meta, "people": people})
        if present and state.add_roll_values("subjects", [name]):
            self.on_roll_changed()
        self._people_chips.refresh()

    def _add_person(self) -> None:
        name = normalize_name(self.person_input.value or "",
                              [*self.person_names, *state.suggestions("subjects")])
        self.person_input.set_value("")
        if name:
            self._set_person(name, True)

    def _known_places(self) -> list[str]:
        """Suggestions, most relevant first: this roll's locations, places already used
        on its frames, then locations from earlier rolls."""
        used = [meta.get("place", "") for _, meta in self.pairs]
        return list(dict.fromkeys(
            p for p in [*state.roll_values("location"), *used, *state.suggestions("location")] if p
        ))

    def _add_region_to_roll(self, places: list[str]) -> None:
        """Roll info keeps the "City, Country" level of every place used on a frame."""
        known = state.roll_values("location")
        regions = [normalize_place(place_region(p), known) for p in places if "," in p]
        if state.add_roll_values("location", regions):
            self.on_roll_changed()

    def _place_changed(self) -> None:
        if self._loading:
            return
        self.save()
        typed = self.place.value or ""
        place = complete_place(normalize_place(typed, self._known_places()),
                               state.roll_values("location"))
        for i in self._targets():
            meta = self.pairs[i][1]
            if place != meta.get("place", ""):
                self._write(i, {**meta, "place": place})
        self._add_region_to_roll([place])
        # Show the tidied spelling and drop whatever was typed from the suggestions
        self._loading = True
        self.place.set_options(self._known_places(), value=place or None)
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
                                             state.roll_values("location"))
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
            self._add_region_to_roll([self.pairs[i][1].get("place", "") for i, _ in undo])
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
