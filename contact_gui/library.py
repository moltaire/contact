"""
contact_gui/library.py
──────────────────────
The library: every roll in one parent folder, shown as pictures.

Two views of the same thing, switched with a toggle:
  Rolls   one card per roll — a miniature contact sheet of eight frames — grouped by year
  Frames  the frames themselves, grouped by roll
Both follow the search box and the filters. Clicking a roll card shows that roll's
frames here; the button on the card opens the roll's own page. Clicking a frame opens
the frame overlay (contact_gui/frames.py) on the frames shown.
"""

from collections.abc import Callable
from pathlib import Path

from nicegui import background_tasks, run, ui

from processor.library import Frame, Hit, Roll, all_frames, facets, search

from .files import library_thumb_url
from .folder import pick_folder
from .state import display_path, state

_CARD_FRAMES = 8     # frames on a roll card: two rows of four
_MAX_FRAMES = 400    # frames drawn at once in the Frames view
_MAX_CHIPS = 24      # filter chips per row
_FACETS = {"people": "person", "place": "place", "film": "film"}  # row → query prefix


def _short(items: list[str], limit: int = 2) -> str:
    more = len(items) - limit
    return ", ".join(items[:limit]) + (f" +{more}" if more > 0 else "")


def _img(url: str, classes: str) -> ui.element:
    """A plain <img>: hundreds of them are lighter than as many image components."""
    return ui.element("img").props(f'src="{url}" loading="lazy" draggable="false"').classes(classes)


def _roll_hits(roll: Roll) -> list[Hit]:
    """Every image of a roll as a viewer item; untagged ones have no metadata yet."""
    meta = {f.image: f for f in roll.frames}
    return [Hit(roll, meta.get(image) or Frame(image, {})) for image in roll.images]


class LibraryView:
    def __init__(self, on_open: Callable[..., bool],
                 on_nav_change: Callable[[bool], None], overlay) -> None:
        # on_open(roll folder, frame file name or None, tab=None): open a roll's page
        self.on_open = on_open
        self.on_nav_change = on_nav_change  # record the place in the browser history
        self.query = ""
        self.view = "Rolls"
        self.show_filters = False
        self.focus: Path | None = None      # a roll whose frames are shown on their own
        self._loading = False
        self.overlay = overlay  # the frame overlay, shared with the roll overview

    def set_focus(self, folder: Path | None, record: bool = False) -> None:
        """Show one roll's frames (a roll card was clicked), or all rolls again (None)."""
        if folder == self.focus:
            return
        self.focus = folder
        # a roll shown from the list has the list right behind it in the history
        self._focus_pushed = folder is not None
        if hasattr(self, "_body"):
            self._body.refresh()
        if record:
            self.on_nav_change(False)
            ui.run_javascript("window.scrollTo(0, 0)")

    @ui.refreshable_method
    def render(self) -> None:
        if state.library_root is None:
            self._choose_root("Choose the folder that holds your roll folders. "
                              "contact reads them; it does not move or change anything.")
            return

        with ui.row().classes("w-full items-center no-wrap gap-3"):
            self.search = ui.input(placeholder="Search all frames") \
                .props("outlined dense clearable").classes("grow library-search")
            self.search.value = self.query
            self.search.on("clear", lambda: self._search(""))
            self.search.on_value_change(lambda e: self._search(e.value))
            self.view_toggle = ui.toggle(["Rolls", "Frames"], value=self.view,
                                         on_change=self._set_view) \
                .props("dense no-caps unelevated toggle-color=transparent toggle-text-color=black") \
                .classes("mode-toggle").tooltip("V")
            ui.button("Filters", icon="tune", on_click=self._toggle_filters) \
                .props("flat dense color=grey-6")

        if state.library is None:
            with ui.row().classes("items-center gap-2"):
                ui.spinner(size="sm")
                ui.label("Reading the library…").classes("text-sm text-grey-6")
            if not self._loading:
                self._loading = True
                ui.timer(0.1, self._load, once=True)
            return
        self._filters()
        self._body()

    # ── Library folder ────────────────────────────────────────────────────────

    def _choose_root(self, text: str) -> None:
        ui.label(text).classes("text-grey-7")
        with ui.row().classes("w-full items-center no-wrap"):
            ui.button("Choose library folder…", icon="folder_open", on_click=self._browse) \
                .props("outline")
            field = ui.input(placeholder="/path/to/all/rolls").props("outlined dense") \
                .classes("grow")
            field.on("keydown.enter", lambda: self._set_root(field.value))
            ui.button("Use", on_click=lambda: self._set_root(field.value)).props("flat")

    def _change_root(self) -> None:
        with ui.dialog() as dialog, ui.card().classes("w-[640px] max-w-full"):
            self._choose_root("Choose another library folder.")
            ui.button("Cancel", on_click=dialog.close).props("flat").classes("self-end")
        self._dialog = dialog
        dialog.open()

    async def _browse(self) -> None:
        picked = await run.io_bound(pick_folder, "Select the library folder")
        if picked:
            self._set_root(picked)

    def _set_root(self, value: str) -> None:
        path = Path((value or "").strip()).expanduser()
        if not (value or "").strip() or not path.is_dir():
            ui.notify(f"Folder not found: {value}", type="negative")
            return
        if getattr(self, "_dialog", None):
            self._dialog.close()
        state.set_library(path.resolve())
        self.query = ""
        self.render.refresh()

    async def _load(self) -> None:
        await run.io_bound(state.refresh_library)
        self._loading = False
        self.render.refresh()
        self._warm_previews()

    def _warm_previews(self) -> None:
        """Make the card previews in the background, so they are ready on disk next time."""
        from .files import warm_previews
        rolls = state.library or []
        images = [img for r in rolls for img in list(dict.fromkeys([*r.starred, *r.images]))[:_CARD_FRAMES]]
        background_tasks.create(run.io_bound(warm_previews, images, 160), name="previews")

    async def reload(self) -> None:
        """Pick up rolls that were added or edited; unchanged rolls are not read again."""
        if state.library_root is None or self._loading:
            return
        self._loading = True
        await run.io_bound(state.refresh_library)
        self._loading = False
        if self.overlay.is_open:
            return  # redrawing would change the frames the overlay steps through
        self.render.refresh()

    # ── Search, view and filters ──────────────────────────────────────────────

    def _search(self, query: str | None) -> None:
        query = query or ""
        if query != self.query:
            self.query = query
            self._filters.refresh()
            self._body.refresh()

    def _set_view(self, e) -> None:
        self.view = e.value or "Rolls"
        self._body.refresh()

    def toggle_view(self) -> None:
        """V: Rolls ⇄ Frames. Through the switch, so it slides and calls _set_view."""
        if getattr(self, "view_toggle", None) is not None and not self.view_toggle.is_deleted:
            self.view_toggle.set_value("Frames" if self.view == "Rolls" else "Rolls")

    def _toggle_filters(self) -> None:
        self.show_filters = not self.show_filters
        self._filters.refresh()

    def _toggle_favourites(self) -> None:
        term = "is:starred"
        query = " ".join(self.query.replace(term, "").split()) if term in self.query \
            else f"{self.query} {term}".strip()
        self.search.set_value(query)

    def _toggle_term(self, prefix: str, value: str) -> None:
        term = f'{prefix}:"{value}"'
        query = " ".join(self.query.replace(term, "").split()) if term in self.query \
            else f"{self.query} {term}".strip()
        self.search.set_value(query)

    @ui.refreshable_method
    def _filters(self) -> None:
        """Collapsed by default. One wrapping row per kind — nothing scrolls sideways."""
        if not self.show_filters:
            return
        found = facets(state.library or [])
        with ui.column().classes("w-full gap-1 library-filters"):
            for key, prefix in _FACETS.items():
                values = found[key]
                if not values:
                    continue
                with ui.row().classes("w-full items-start no-wrap gap-3"):
                    ui.label(key if key != "place" else "places").classes("sheet-key")
                    with ui.row().classes("grow gap-1"):
                        for value, _count in values[:_MAX_CHIPS]:
                            on = f'{prefix}:"{value}"' in self.query
                            ui.chip(value, color="primary" if on else "grey-9",
                                    text_color="white",
                                    on_click=lambda prefix=prefix, value=value:
                                        self._toggle_term(prefix, value)) \
                                .props("dense square").classes("candidate")
                        if len(values) > _MAX_CHIPS:
                            ui.label(f"+{len(values) - _MAX_CHIPS} more — type to search") \
                                .classes("text-xs text-grey-6 self-center")
            with ui.row().classes("w-full items-center no-wrap gap-3"):
                ui.label("show").classes("sheet-key")
                on = "is:starred" in self.query
                ui.chip("favourites", icon="star", color="primary" if on else "grey-9",
                        text_color="white", on_click=self._toggle_favourites) \
                    .props("dense square").classes("candidate")
            with ui.row().classes("w-full items-center no-wrap gap-3"):
                ui.label("library").classes("sheet-key")
                ui.label(display_path(state.library_root)).classes("text-xs text-grey-6 mono")
                ui.button("Change", on_click=self._change_root).props("flat dense size=sm")
                ui.button("Read again", on_click=self.reload).props("flat dense size=sm")

    # ── Rolls and frames ──────────────────────────────────────────────────────

    @ui.refreshable_method
    def _body(self) -> None:
        rolls = state.library or []
        if not rolls:
            ui.label("No rolls found in this folder. A roll is a subfolder with scans and a "
                     "roll.yaml or tagged frames.").classes("text-grey-7")
            return
        searching = bool(self.query.strip())
        focused = next((r for r in rolls if r.folder == self.focus), None)
        if focused is not None:
            self._roll_frames(focused, searching)
            return
        hits = search(rolls, self.query) if searching else all_frames(rolls)
        by_roll: dict[int, list[Hit]] = {}
        for hit in hits:
            by_roll.setdefault(id(hit.roll), []).append(hit)
        # while searching, only rolls with a match; otherwise every roll, tagged or not
        shown = [r for r in rolls if id(r) in by_roll] if searching else rolls

        n_frames, n_rolls = len(hits), len(shown)
        ui.label(
            "Nothing found" if searching and not hits else
            f"{n_frames} frame{'s' if n_frames != 1 else ''} in "
            f"{n_rolls} roll{'s' if n_rolls != 1 else ''}"
        ).classes("text-xs text-grey-6 mono")

        if self.view == "Rolls":
            self._roll_cards(shown, by_roll if searching else {})
        else:
            self._frame_groups(shown, by_roll)

    def _roll_frames(self, roll: Roll, searching: bool) -> None:
        """One roll's frames, as clicked from its card. Search narrows them further."""
        everything = _roll_hits(roll)
        if searching:
            found = {id(h.frame) for h in search([roll], self.query)}
            hits = [h for h in everything if id(h.frame) in found]
        else:
            hits = everything
        with ui.row().classes("w-full items-center no-wrap gap-3 library-focus"):
            ui.button("All rolls", icon="arrow_back", on_click=lambda: self.on_back()) \
                .props("flat dense no-caps color=grey-5")
            with ui.column().classes("gap-0 grow min-w-0"):
                ui.label(roll.label).classes("library-card-title truncate w-full")
                ui.label(" · ".join(v for v in [
                    roll.date, roll.info.get("film", ""), roll.info.get("camera", ""),
                    _short(roll.locations),
                    f"{len(hits)} of {roll.image_count} frames" if searching
                    else f"{roll.image_count} frames"] if v)).classes("library-card-sub truncate w-full")
            ui.button("Open roll", icon="arrow_forward",
                      on_click=lambda: self.on_open(roll.folder)) \
                .props("unelevated no-caps").tooltip("Tag, edit, contact sheet, rename")
        if not hits:
            ui.label("No frames of this roll match the search.").classes("text-grey-7")
            return
        with ui.element("div").classes("library-frames mt-2"):
            for n, hit in enumerate(hits):
                classes = "library-hit" + ("" if hit.frame.meta else " library-untagged")
                with ui.element("div").classes("library-hit-box" +
                                               (" frame-starred" if hit.frame.meta.get("starred")
                                                else "")):
                    _img(library_thumb_url(hit.frame.image, 320), classes) \
                        .on("click", lambda n=n: self.open_frames(hits, n, roll=roll))

    def open_frames(self, items: list[Hit], index: int, roll: Roll | None = None) -> None:
        """Open the frame overlay on these frames: one roll's, or the search results."""
        if roll is not None:
            origin = {"from": "library", "scope": "roll", "roll": str(roll.folder)}
            label = roll.label
        else:
            origin = {"from": "library", "scope": "results", "q": self.query}
            label = f"Search: {self.query.strip()}" if self.query.strip() else "Library"
        self.overlay.open(items, index, origin, label)

    def items_for(self, origin: dict) -> tuple[list[Hit], str]:
        """The frames an overlay opened from the library stepped through, rebuilt for the
        browser history (back/forward)."""
        rolls = state.library or []
        if origin.get("scope") == "roll":
            roll = next((r for r in rolls if str(r.folder) == origin.get("roll")), None)
            return (_roll_hits(roll), roll.label) if roll else ([], "")
        query = origin.get("q", "")
        hits = search(rolls, query) if query.strip() else all_frames(rolls)
        shown = []
        for roll in rolls:  # the order the Frames view shows them in
            shown += [h for h in hits if h.roll is roll]
        return shown[:_MAX_FRAMES], (f"Search: {query.strip()}" if query.strip() else "Library")

    def on_back(self) -> None:
        """"All rolls": back in the browser history if the roll was opened from there."""
        if getattr(self, "_focus_pushed", False):
            ui.run_javascript("history.back()")
        else:
            self.set_focus(None)
            self.on_nav_change(True)

    def _roll_cards(self, rolls: list[Roll], matches: dict[int, list[Hit]]) -> None:
        years: dict[str, list[Roll]] = {}
        for roll in rolls:
            years.setdefault(roll.year or "Undated", []).append(roll)
        for year, group in years.items():
            ui.label(year).classes("library-year")
            with ui.element("div").classes("library-grid"):
                for roll in group:
                    self._roll_card(roll, matches.get(id(roll)))

    def _roll_card(self, roll: Roll, matched: list[Hit] | None) -> None:
        # matching frames first, then the roll's favourites, then the rest in order
        first = [hit.frame.image for hit in matched or []]
        images = list(dict.fromkeys([*first, *roll.starred, *roll.images]))[:_CARD_FRAMES]
        hits = _roll_hits(roll)
        position = {h.frame.image: n for n, h in enumerate(hits)}
        with ui.element("div").classes("library-card") \
                .on("click", lambda: self.set_focus(roll.folder, record=True)):
            with ui.element("div").classes("library-sheet"):
                for image in images:
                    # a frame opens the viewer on this roll; the rest of the card opens it
                    _img(library_thumb_url(image, 160), "library-frame") \
                        .on("click.stop", lambda n=position[image], hits=hits, roll=roll:
                            self.open_frames(hits, n, roll=roll))
                for _ in range(_CARD_FRAMES - len(images)):
                    ui.element("div").classes("library-frame library-frame-empty")
            count = (f"{len(matched)} of {len(roll.frames)} match" if matched is not None
                     else f"{roll.image_count} frames")
            with ui.row().classes("w-full items-start no-wrap gap-2"):
                with ui.column().classes("grow gap-0 min-w-0"):
                    ui.label(roll.label).classes("library-card-title truncate w-full")
                    ui.label(" · ".join(v for v in [roll.date, roll.info.get("film", ""), count]
                                        if v)).classes("library-card-sub truncate w-full")
                # the roll's own page; .stop keeps the card's own click (browse its
                # frames here) from firing as well
                ui.button(icon="arrow_forward") \
                    .props("flat dense round size=sm color=grey-6").classes("library-card-info") \
                    .on("click.stop", lambda: self.on_open(roll.folder)) \
                    .tooltip("Open roll")

    def _frame_groups(self, rolls: list[Roll], by_roll: dict[int, list[Hit]]) -> None:
        # the viewer steps through exactly the frames on screen, in this order
        shown = [hit for roll in rolls for hit in by_roll.get(id(roll), [])][:_MAX_FRAMES]
        position = {id(hit): n for n, hit in enumerate(shown)}
        budget = _MAX_FRAMES
        for roll in rolls:
            group = by_roll.get(id(roll), [])
            if not group:
                continue
            if budget <= 0:
                ui.label(f"Showing the first {_MAX_FRAMES} frames — search or filter to narrow "
                         "it down.").classes("text-xs text-grey-6 mt-3")
                break
            group, budget = group[:budget], budget - len(group)
            with ui.row().classes("w-full items-baseline gap-3 library-roll"):
                ui.label(roll.label).classes("mono font-bold cursor-pointer") \
                    .on("click", lambda roll=roll: self.on_open(roll.folder))
                ui.label(" · ".join(v for v in [roll.date, roll.info.get("film", ""),
                                                 _short(roll.locations)] if v)) \
                    .classes("mono text-xs text-grey-6")
                ui.space()
                ui.label(f"{len(group)} of {len(roll.frames)}").classes("mono text-xs text-grey-6")
            with ui.element("div").classes("library-frames"):
                for hit in group:
                    # no caption or tooltip: the frame speaks for itself
                    _img(library_thumb_url(hit.frame.image, 320), "library-hit") \
                        .on("click", lambda n=position[id(hit)]:
                            self.open_frames(shown, n))
