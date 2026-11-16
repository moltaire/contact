"""
processor/pipeline.py
─────────────────────
The tagging run shared by every front end (CLI, Streamlit, NiceGUI):
tag frames → write sidecars → roll summary → contact sheet.

Front ends pass an `on_event` callback to follow progress and a `should_stop`
callable to cancel between frames. Nothing here knows about any UI.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .html import write_roll_html
from .roll import IMAGE_EXTS, _split_list_field
from .sidecar import _read_xmp_meta, write_xmp
from .tagger import analyze_image, refine_frame, sanitize_tags, write_roll_summary


@dataclass
class FrameResult:
    image: Path
    meta: dict | None = None
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.meta is not None


@dataclass
class Event:
    """One step of a tagging run.

    kind is one of: 'frame_start', 'frame_done', 'summary', 'sheet', 'done'.
    index is 1-based; result is set for 'frame_done'.
    """

    kind: str
    index: int = 0
    total: int = 0
    image: Path | None = None
    result: FrameResult | None = None


@dataclass
class RunResult:
    frames: list[FrameResult] = field(default_factory=list)
    stopped: bool = False

    @property
    def failed(self) -> list[FrameResult]:
        return [f for f in self.frames if not f.ok]


def list_images(folder: Path) -> list[Path]:
    return sorted(
        f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS
    )


def is_tagged(image: Path) -> bool:
    return image.with_suffix(".xmp").exists()


def tagged_pairs(folder: Path) -> list[tuple[Path, dict]]:
    """Every tagged frame in the folder with the metadata from its sidecar."""
    return [
        (img, _read_xmp_meta(img.with_suffix(".xmp")))
        for img in list_images(folder)
        if is_tagged(img)
    ]


def rebuild_contact_sheet(folder: Path, roll: dict) -> Path | None:
    """Regenerate index.html from the sidecars. Returns its path, or None if nothing is tagged."""
    pairs = tagged_pairs(folder)
    if not pairs:
        return None
    write_roll_html(folder, pairs, roll)
    return folder / "index.html"


def refresh_roll_summary(folder: Path, roll: dict, vision_model: str, text_model: str) -> bool:
    """Rewrite the roll summary from the sidecars as they are now, then the contact sheet.

    The summary is first written at the end of a tagging run; call this after frames
    were edited in review so it reflects the corrections. Returns False if nothing is tagged.
    """
    pairs = tagged_pairs(folder)
    if not pairs:
        return False
    write_roll_summary(folder, [meta for _, meta in pairs], roll, vision_model, text_model)
    rebuild_contact_sheet(folder, roll)
    return True


def tag_images(
    folder: Path,
    images: list[Path],
    vision_model: str,
    text_model: str,
    roll: dict,
    *,
    on_event: Callable[[Event], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    verbose: bool = False,
    dry_run: bool = False,
) -> RunResult:
    """Tag `images`, then refresh the roll summary and contact sheet for the whole folder.

    A frame that fails gets no sidecar, so it stays untagged and is picked up by the
    next run. The summary and contact sheet always cover every tagged frame in the
    folder, not just the ones from this run.
    """
    emit = on_event or (lambda event: None)
    run = RunResult()
    total = len(images)

    for n, img in enumerate(images, 1):
        if should_stop and should_stop():
            run.stopped = True
            break
        emit(Event("frame_start", n, total, img))
        try:
            # What the photographer added in review survives a re-tag: people, landmarks and place
            # are carried over, and their notes are applied to the fresh description.
            kept = _read_xmp_meta(img.with_suffix(".xmp")) if is_tagged(img) else {}
            meta = analyze_image(img, vision_model, text_model, roll, verbose)
            meta.update({k: kept[k] for k in ("people", "landmarks", "place", "notes", "starred")
                         if kept.get(k)})
            if meta.get("notes"):
                meta = refine_frame(img, meta, None, vision_model,
                                    _split_list_field(roll.get("location", "")),
                                    _split_list_field(roll.get("subjects", "")),
                                    _split_list_field(roll.get("landmarks", "")))
            meta["tags"] = sanitize_tags(
                meta["tags"], [*meta.get("people", []), *meta.get("landmarks", [])],
                meta.get("place", ""),
            )
            if not dry_run:
                write_xmp(img, meta, roll)
            result = FrameResult(img, meta)
        except Exception as e:
            result = FrameResult(img, error=str(e))
        run.frames.append(result)
        emit(Event("frame_done", n, total, img, result))

    if not dry_run and any(f.ok for f in run.frames):
        emit(Event("summary", total=total))
        all_meta = [meta for _, meta in tagged_pairs(folder)]
        write_roll_summary(folder, all_meta, roll, vision_model, text_model)
        emit(Event("sheet", total=total))
        rebuild_contact_sheet(folder, roll)

    emit(Event("done", total=total))
    return run
