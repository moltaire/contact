"""
contact_gui/roll_form.py
────────────────────────
The roll's facts (film, camera, lens, date, location, …) as a form, shown in place on
the roll page and written to roll.yaml.
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


class RollForm:
    """The roll's facts as a form, shown in place on the roll page (Edit info)."""

    def __init__(self, on_saved: Callable[[], None], on_cancel: Callable[[], None]) -> None:
        self.on_saved = on_saved
        self.on_cancel = on_cancel

    def build(self) -> None:
        roll = state.roll
        history = _load_history()

        def past(key: str) -> list[str]:
            return _history_sorted(history, key)

        # Two columns for the short facts, full width for lists and notes
        with ui.grid(columns=2).classes("roll-form w-full gap-x-4 gap-y-3"):
            self.label = ui.input("Label", value=roll.get("label", ""),
                                  placeholder="e.g. Oslo Summer 2024") \
                .props("outlined dense").classes("w-full col-span-2")
            self.film = _pick_one("Film stock", roll.get("film", ""),
                                  past("film") + KNOWN_FILM_STOCKS)
            self.date = ui.input("Date", value=roll.get("date", ""),
                                 placeholder="YYYY-MM or YYYY-MM-DD") \
                .props("outlined dense").classes("w-full")
            self.camera = _pick_one("Camera", roll.get("camera", ""),
                                    past("camera") + KNOWN_CAMERAS)
            self.lens = _pick_many("Lens", _split_list_field(roll.get("lens", "")),
                                   past("lens"))
            self.location = _pick_many("Location (City, Country)",
                                       _split_list_field(roll.get("location", "")),
                                       past("location"))
            self.lab = _pick_one("Lab", roll.get("lab", ""), past("lab"))
            self.subjects = _pick_many("People", _split_list_field(roll.get("subjects", "")),
                                       past("subjects")).classes("col-span-2")
            self.landmarks = _pick_many("Landmarks",
                                        _split_list_field(roll.get("landmarks", "")),
                                        past("landmarks")).classes("col-span-2")
            self.lab_notes = ui.input("Lab notes", value=roll.get("lab_notes", ""),
                                      placeholder="e.g. push 1 stop") \
                .props("outlined dense").classes("w-full col-span-2")
            self.notes = ui.textarea("Notes", value=roll.get("notes", "")) \
                .props("outlined dense autogrow").classes("w-full col-span-2")
            with ui.row().classes("col-span-2 gap-2"):
                ui.button("Save", on_click=self._save)
                ui.button("Cancel", on_click=self.on_cancel).props("outline color=grey-5")

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
        self.on_saved()
