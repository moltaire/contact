"""
contact_gui/roll_form.py
────────────────────────
Step 2: roll metadata (film, camera, lens, date, location, …) written to roll.yaml.
"""

from collections.abc import Callable

from nicegui import ui

from processor.roll import (
    KNOWN_CAMERAS,
    KNOWN_FILM_STOCKS,
    _history_sorted,
    _join_list_field,
    _load_history,
    _record,
    _save_history,
    _split_list_field,
    normalize_name,
    normalize_place,
    write_roll_yaml,
)

from .files import thumb_url
from .state import state


def _dedup(items: list[str]) -> list[str]:
    return list(dict.fromkeys(i for i in items if i))


def _pick_one(label: str, current: str, options: list[str]) -> ui.select:
    """Dropdown that also accepts a new value typed in."""
    return ui.select(
        _dedup([current, *options]), label=label, value=current or None,
        with_input=True, new_value_mode="add-unique", clearable=True,
    ).props("outlined dense").classes("w-full")


def _pick_many(label: str, current: list[str], options: list[str]) -> ui.select:
    return ui.select(
        _dedup([*current, *options]), label=label, value=current,
        with_input=True, new_value_mode="add-unique", multiple=True,
    ).props("outlined dense use-chips").classes("w-full")


class RollView:
    def __init__(self, on_saved: Callable[[], None]) -> None:
        self.on_saved = on_saved

    @ui.refreshable_method
    def render(self) -> None:
        if state.folder is None:
            ui.label("Select a folder first.").classes("text-grey-7")
            return
        roll = state.roll
        history = _load_history()

        def past(key: str) -> list[str]:
            return _history_sorted(history, key)

        with ui.row().classes("w-full no-wrap gap-8 items-start"):
            with ui.column().classes("w-3/5 gap-3"):
                self.label = ui.input("Label", value=roll.get("label", ""),
                                      placeholder="e.g. Oslo Summer 2024") \
                    .props("outlined dense").classes("w-full")
                self.film = _pick_one("Film stock", roll.get("film", ""),
                                      past("film") + KNOWN_FILM_STOCKS)
                self.camera = _pick_one("Camera", roll.get("camera", ""),
                                        past("camera") + KNOWN_CAMERAS)
                self.lens = _pick_many("Lens", _split_list_field(roll.get("lens", "")),
                                       past("lens"))
                self.date = ui.input("Date", value=roll.get("date", ""),
                                     placeholder="YYYY-MM or YYYY-MM-DD") \
                    .props("outlined dense").classes("w-full")
                self.location = _pick_many("Location (City, Country)",
                                           _split_list_field(roll.get("location", "")),
                                           past("location"))
                self.subjects = _pick_many("People",
                                           _split_list_field(roll.get("subjects", "")),
                                           past("subjects"))
                self.landmarks = _pick_many("Landmarks",
                                            _split_list_field(roll.get("landmarks", "")),
                                            past("landmarks"))
                self.lab = _pick_one("Lab", roll.get("lab", ""), past("lab"))
                self.lab_notes = ui.input("Lab notes", value=roll.get("lab_notes", ""),
                                          placeholder="e.g. push 1 stop") \
                    .props("outlined dense").classes("w-full")
                self.notes = ui.textarea("Notes", value=roll.get("notes", "")) \
                    .props("outlined dense autogrow").classes("w-full")
                ui.button("Save and continue", on_click=self._save)

            # Frames alongside the form, to check subjects and locations while typing
            with ui.grid(columns=3).classes("w-2/5 gap-2"):
                for img in state.images:
                    ui.image(thumb_url(img, 160)).props("fit=contain") \
                        .classes("w-full h-24 frame").tooltip(img.name)

    def _save(self) -> None:
        # One spelling per place: "athens,greece" becomes "Athens, Greece" and is not
        # stored next to an entry that differs only in case or spacing.
        known = _history_sorted(_load_history(), "location")
        locations = list(dict.fromkeys(
            normalize_place(loc, known) for loc in (self.location.value or [])
        ))
        known_people = _history_sorted(_load_history(), "subjects")
        past_landmarks = _history_sorted(_load_history(), "landmarks")
        subjects = list(dict.fromkeys(
            normalize_name(name, known_people) for name in (self.subjects.value or [])
        ))
        landmarks = list(dict.fromkeys(
            normalize_name(name, past_landmarks) for name in (self.landmarks.value or [])
        ))
        data = {
            "film": self.film.value or "",
            "camera": self.camera.value or "",
            "lens": _join_list_field(self.lens.value or []),
            "date": self.date.value or "",
            "location": _join_list_field([loc for loc in locations if loc]),
            "subjects": _join_list_field([name for name in subjects if name]),
            "landmarks": _join_list_field([name for name in landmarks if name]),
            "lab": self.lab.value or "",
            "lab_notes": self.lab_notes.value or "",
            # roll.yaml is line-based, so a note stays one line on disk
            "notes": " ".join((self.notes.value or "").split()),
            "label": self.label.value or "",
        }
        write_roll_yaml(state.folder, data)

        history = _load_history()
        for key in ("film", "camera", "lab", "lab_notes"):
            _record(history, key, data[key])
        for key in ("lens", "location", "subjects", "landmarks"):
            for item in _split_list_field(data[key]):
                _record(history, key, item)
        _save_history(history)

        state.reload_folder()
        ui.notify("Roll info saved", type="positive")
        self.on_saved()
