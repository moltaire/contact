"""
contact_gui/state.py
────────────────────
Application state for the NiceGUI front end.

contact is a single-user local tool, so the state is deliberately one
module-level object: it outlives page reloads and tab switches, which is what
lets a tagging run carry on in the background while the browser comes and goes.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from processor.pipeline import Event, FrameResult, is_tagged, list_images
from processor.roll import (
    HISTORY_PATH,
    _history_sorted,
    _join_list_field,
    _load_history,
    _record,
    _save_history,
    _split_list_field,
    load_roll_yaml,
    write_roll_yaml,
)
from processor.tagger import FALLBACK_MODEL, list_models, list_vision_models


SETTINGS_PATH = HISTORY_PATH.parent / "settings.json"


@dataclass
class Job:
    """A tagging run. Written by the worker thread, read by the UI timer."""

    folder: Path
    total: int
    running: bool = True
    stop_requested: bool = False
    index: int = 0
    current: str = ""
    stage: str = "Starting…"
    results: list[FrameResult] = field(default_factory=list)
    error: str = ""
    acknowledged: bool = False  # set once the UI has reacted to the run finishing

    def on_event(self, event: Event) -> None:
        if event.kind == "frame_start":
            self.index = event.index
            self.current = event.image.name
            self.stage = f"Tagging {event.image.name}  ({event.index} / {event.total})"
        elif event.kind == "frame_done":
            self.results.append(event.result)
        elif event.kind == "summary":
            self.stage = "Writing roll summary…"
        elif event.kind == "sheet":
            self.stage = "Building contact sheet…"

    @property
    def progress(self) -> float:
        return len(self.results) / self.total if self.total else 1.0

    @property
    def failed(self) -> list[FrameResult]:
        return [r for r in self.results if not r.ok]


class State:
    def __init__(self) -> None:
        self.folder: Path | None = None
        self.roll: dict = {}
        self.images: list[Path] = []
        self.selected: set[str] = set()
        self.all_models: list[str] = []
        self.vision_models: list[str] = []
        self.vision_model: str = FALLBACK_MODEL
        self.text_model: str = FALLBACK_MODEL
        self.job: Job | None = None
        self.edited_since_summary = False  # set by review, cleared when the summary is rewritten

    # ── Folder ────────────────────────────────────────────────────────────────

    def open_folder(self, path: Path) -> None:
        self.folder = path
        self.reload_folder()
        self.selected = {img.name for img in self.images}

    def reload_folder(self) -> None:
        if self.folder is None:
            return
        self.images = list_images(self.folder)
        self.roll = load_roll_yaml(self.folder)

    @property
    def title(self) -> str:
        if self.folder is None:
            return ""
        return self.roll.get("label", "").strip() or self.folder.name

    @property
    def tagged(self) -> list[Path]:
        return [img for img in self.images if is_tagged(img)]

    @property
    def busy(self) -> bool:
        return self.job is not None and self.job.running

    def summary_is_stale(self) -> bool:
        """True if frames were edited after the roll summary was last written."""
        if self.folder is None or not self.tagged:
            return False
        if self.edited_since_summary:
            return True
        roll_yaml = self.folder / "roll.yaml"
        if not roll_yaml.exists():
            return True
        written = roll_yaml.stat().st_mtime
        return any(img.with_suffix(".xmp").stat().st_mtime > written for img in self.tagged)

    # ── Roll lists (subjects, locations) ──────────────────────────────────────

    def roll_values(self, key: str) -> list[str]:
        """The roll's own entries for a list field such as 'subjects' or 'location'."""
        return _split_list_field(self.roll.get(key, ""))

    def suggestions(self, key: str) -> list[str]:
        """The roll's entries first, then everything used on earlier rolls."""
        return list(dict.fromkeys([*self.roll_values(key), *_history_sorted(_load_history(), key)]))

    def add_roll_values(self, key: str, values: list[str]) -> bool:
        """Add names found during review to the roll's list in roll.yaml and to the history.

        Review is where people and places actually get assigned, so anything new there
        flows back into the roll info. Returns True if roll.yaml changed.
        """
        current = self.roll_values(key)
        seen = {c.casefold() for c in current}
        new = [v for v in dict.fromkeys(values) if v and v.casefold() not in seen]
        if not new or self.folder is None:
            return False
        write_roll_yaml(self.folder, {**self.roll, key: _join_list_field(current + new)})
        history = _load_history()
        for value in new:
            _record(history, key, value)
        _save_history(history)
        self.roll = load_roll_yaml(self.folder)
        return True

    # ── Models ────────────────────────────────────────────────────────────────

    def refresh_models(self) -> None:
        """Ask Ollama what is installed and apply the saved choice. Blocking — call it
        off the event loop."""
        self.all_models = list_models()
        self.vision_models = list_vision_models()
        saved = self._load_settings()
        if saved.get("vision_model") in self.vision_models:
            self.vision_model = saved["vision_model"]
        elif self.vision_models and self.vision_model not in self.vision_models:
            self.vision_model = self.vision_models[0]
        if saved.get("text_model") in self.all_models:
            self.text_model = saved["text_model"]
        elif self.text_model not in self.all_models:
            self.text_model = self.vision_model

    def save_models(self) -> None:
        """Remember the model choice for the next start."""
        try:
            SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
            SETTINGS_PATH.write_text(json.dumps(
                {"vision_model": self.vision_model, "text_model": self.text_model}, indent=2
            ), encoding="utf-8")
        except OSError:
            pass

    @staticmethod
    def _load_settings() -> dict:
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}


state = State()
