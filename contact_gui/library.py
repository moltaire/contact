"""
contact_gui/library.py
──────────────────────
The library: every roll in one parent folder as a sortable table, and a search
across all their frames. Clicking a roll opens it; clicking a found frame opens
its roll in review at that frame.
"""

from collections.abc import Callable
from pathlib import Path

from nicegui import run, ui

from processor.library import Hit, Roll, facets, search

from .files import library_thumb_url
from .folder import _pick_folder_dialog
from .state import display_path, state

_MAX_HITS = 400  # frames drawn for one search; more than that needs a narrower query
_FACETS = {"people": "person", "place": "place", "film": "film"}  # facet → query prefix

_COLUMNS = [
    {"name": "cover", "label": "", "field": "cover", "align": "left"},
    {"name": "label", "label": "Roll", "field": "label", "align": "left", "sortable": True},
    {"name": "date", "label": "Date", "field": "date", "align": "left", "sortable": True},
    {"name": "film", "label": "Film", "field": "film", "align": "left", "sortable": True},
    {"name": "camera", "label": "Camera", "field": "camera", "align": "left", "sortable": True},
    {"name": "place", "label": "Place", "field": "place", "align": "left", "sortable": True},
    {"name": "people", "label": "People", "field": "people", "align": "left"},
    {"name": "frames", "label": "Frames", "field": "frames", "align": "right", "sortable": True},
]


def _short(items: list[str], limit: int = 4) -> str:
    more = len(items) - limit
    return ", ".join(items[:limit]) + (f" +{more}" if more > 0 else "")


class LibraryView:
    def __init__(self, on_open: Callable[[Path, str | None], None]) -> None:
        self.on_open = on_open  # (roll folder, frame file name or None)
        self.query = ""
        self._loading = False

    @ui.refreshable_method
    def render(self) -> None:
        if state.library_root is None:
            self._choose_root("Choose the folder that holds your roll folders. "
                              "contact reads them; it does not move or change anything.")
            return

        with ui.row().classes("w-full items-center no-wrap gap-3"):
            self.search = ui.input(placeholder="Search all frames — ines, tower, "
                                               "\"national theatre\", film:hp5, place:athens") \
                .props("outlined dense clearable").classes("grow library-search")
            self.search.value = self.query
            self.search.on("keydown.enter", lambda: self._search(self.search.value))
            self.search.on("clear", lambda: self._search(""))
            self.search.on_value_change(lambda e: self._search(e.value))
            ui.button(icon="refresh", on_click=self.reload).props("flat round dense color=grey-6") \
                .tooltip("Read the library folder again")
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            self.summary = ui.label().classes("text-xs text-grey-6 mono")
            ui.space()
            ui.label(display_path(state.library_root)).classes("text-xs text-grey-6 mono")
            ui.button("Change", on_click=self._change_root).props("flat dense size=sm")

        if state.library is None:
            with ui.row().classes("items-center gap-2"):
                ui.spinner(size="sm")
                ui.label("Reading the library…").classes("text-sm text-grey-6")
            if not self._loading:
                self._loading = True
                ui.timer(0.1, self._load, once=True)
            return
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

    # ── Rolls and search results ──────────────────────────────────────────────

    def _search(self, query: str | None) -> None:
        query = query or ""
        if query != self.query:
            self.query = query
            self._body.refresh()

    def _add_term(self, prefix: str, value: str) -> None:
        term = f'{prefix}:"{value}"'
        query = self.query.replace(term, "").strip() if term in self.query \
            else f"{self.query} {term}".strip()
        self.search.set_value(query)

    @ui.refreshable_method
    def _body(self) -> None:
        rolls = state.library or []
        frames = sum(len(r.frames) for r in rolls)
        if not rolls:
            self.summary.set_text("")
            ui.label("No rolls found in this folder. A roll is a subfolder with scans and a "
                     "roll.yaml or tagged frames.").classes("text-grey-7")
            return
        self._facets(rolls)
        if not self.query.strip():
            self.summary.set_text(f"{len(rolls)} rolls · {frames} tagged frames")
            self._table(rolls)
            return
        hits = search(rolls, self.query)
        found_rolls = len({id(h.roll) for h in hits})
        self.summary.set_text(
            f"{len(hits)} frame{'s' if len(hits) != 1 else ''} in {found_rolls} "
            f"roll{'s' if found_rolls != 1 else ''}" if hits else "Nothing found"
        )
        self._results(hits)

    def _facets(self, rolls: list[Roll]) -> None:
        found = facets(rolls)
        with ui.row().classes("w-full no-wrap items-center gap-1 strip h-8"):
            for key, prefix in _FACETS.items():
                for value, _count in found[key][:8]:
                    on = f'{prefix}:"{value}"' in self.query
                    ui.chip(value, color="primary" if on else "grey-9", text_color="white",
                            on_click=lambda prefix=prefix, value=value: self._add_term(prefix, value)) \
                        .props("dense square").classes("shrink-0 candidate")
                ui.element("div").classes("w-3 shrink-0")

    def _table(self, rolls: list[Roll]) -> None:
        rows = [{
            "folder": str(r.folder),
            "cover": library_thumb_url(r.cover, 160) if r.cover else "",
            "label": r.label,
            "date": r.date,
            "film": r.info.get("film", ""),
            "camera": r.info.get("camera", ""),
            "place": _short(r.locations, 2),
            "people": _short(r.people),
            "frames": len(r.frames) if len(r.frames) == r.image_count
                      else f"{len(r.frames)} / {r.image_count}",
        } for r in rolls]
        table = ui.table(columns=_COLUMNS, rows=rows, row_key="folder", pagination=0) \
            .props("flat dense hide-pagination").classes("w-full library-table")
        table.add_slot("body-cell-cover", '''
            <q-td :props="props" style="width: 76px; padding: 4px 8px">
                <img v-if="props.value" :src="props.value" loading="lazy"
                     style="width: 60px; height: 44px; object-fit: cover; display: block">
            </q-td>''')
        table.on("rowClick", lambda e: self.on_open(Path(e.args[1]["folder"]), None))

    def _results(self, hits: list[Hit]) -> None:
        shown = hits[:_MAX_HITS]
        if len(hits) > len(shown):
            ui.label(f"Showing the first {len(shown)} frames — add a word to narrow it down.") \
                .classes("text-xs text-grey-6")
        groups: dict[int, list[Hit]] = {}
        for hit in shown:
            groups.setdefault(id(hit.roll), []).append(hit)
        for group in groups.values():
            roll = group[0].roll
            with ui.row().classes("w-full items-baseline gap-3 mt-3 library-roll"):
                ui.label(roll.label).classes("mono font-bold cursor-pointer") \
                    .on("click", lambda roll=roll: self.on_open(roll.folder, None)) \
                    .tooltip("Open this roll")
                ui.label(" · ".join(v for v in [roll.date, roll.info.get("film", ""),
                                                 _short(roll.locations, 2)] if v)) \
                    .classes("mono text-xs text-grey-6")
                ui.space()
                ui.label(f"{len(group)} of {len(roll.frames)}").classes("mono text-xs text-grey-6")
            with ui.row().classes("w-full gap-2"):
                for hit in group:
                    with ui.image(library_thumb_url(hit.frame.image, 320)).props("fit=cover") \
                            .classes("w-40 h-28 cursor-pointer frame library-hit") \
                            .on("click", lambda hit=hit: self.on_open(hit.roll.folder,
                                                                      hit.frame.image.name)):
                        ui.tooltip(hit.frame.meta.get("description", "") or hit.frame.image.name) \
                            .classes("text-sm max-w-xs")
