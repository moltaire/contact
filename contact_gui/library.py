"""
contact_gui/library.py
──────────────────────
The library: every roll in one parent folder, shown as pictures.

Two views of the same thing, switched with a toggle:
  Rolls   one card per roll — a miniature contact sheet of eight frames — grouped by year
  Frames  the frames themselves, grouped by roll
Both follow the search box and the filters. Clicking a roll opens it; clicking a frame
opens its roll in review at that frame.
"""

from collections.abc import Callable
from pathlib import Path

from nicegui import run, ui

from processor.library import Hit, Roll, all_frames, facets, search

from .files import library_thumb_url
from .folder import _pick_folder_dialog
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


class LibraryView:
    def __init__(self, on_open: Callable[..., None]) -> None:
        # on_open(roll folder, frame file name or None, tab=None): open a roll, in review
        # at a frame, or on a given step such as "roll" for its roll info
        self.on_open = on_open
        self.query = ""
        self.view = "Rolls"
        self.show_filters = False
        self._loading = False

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
            ui.toggle(["Rolls", "Frames"], value=self.view, on_change=self._set_view) \
                .props("dense no-caps unelevated toggle-color=primary toggle-text-color=black")
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
        picked = await run.io_bound(_pick_folder_dialog)
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

    async def reload(self) -> None:
        """Pick up rolls that were added or edited; unchanged rolls are not read again."""
        if state.library_root is None or self._loading:
            return
        self._loading = True
        await run.io_bound(state.refresh_library)
        self._loading = False
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
        with ui.element("div").classes("library-card") \
                .on("click", lambda: self.on_open(roll.folder, None)):
            with ui.element("div").classes("library-sheet"):
                for image in images:
                    _img(library_thumb_url(image, 160), "library-frame")
                for _ in range(_CARD_FRAMES - len(images)):
                    ui.element("div").classes("library-frame library-frame-empty")
            count = (f"{len(matched)} of {len(roll.frames)} match" if matched is not None
                     else f"{roll.image_count} frames")
            with ui.row().classes("w-full items-start no-wrap gap-2"):
                with ui.column().classes("grow gap-0 min-w-0"):
                    ui.label(roll.label).classes("library-card-title truncate w-full")
                    ui.label(" · ".join(v for v in [roll.date, roll.info.get("film", ""), count]
                                        if v)).classes("library-card-sub truncate w-full")
                # straight to the roll's info instead of review; .stop keeps the card's
                # own click from firing as well
                ui.button(icon="edit_note") \
                    .props("flat dense round size=sm color=grey-6").classes("library-card-info") \
                    .on("click.stop", lambda: self.on_open(roll.folder, None, tab="roll")) \
                    .tooltip("Roll info")

    def _frame_groups(self, rolls: list[Roll], by_roll: dict[int, list[Hit]]) -> None:
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
                    .on("click", lambda roll=roll: self.on_open(roll.folder, None))
                ui.label(" · ".join(v for v in [roll.date, roll.info.get("film", ""),
                                                 _short(roll.locations)] if v)) \
                    .classes("mono text-xs text-grey-6")
                ui.space()
                ui.label(f"{len(group)} of {len(roll.frames)}").classes("mono text-xs text-grey-6")
            with ui.element("div").classes("library-frames"):
                for hit in group:
                    # no caption or tooltip: the frame speaks for itself
                    _img(library_thumb_url(hit.frame.image, 320), "library-hit") \
                        .on("click", lambda hit=hit: self.on_open(hit.roll.folder,
                                                                  hit.frame.image.name))
