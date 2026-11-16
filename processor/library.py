"""
processor/library.py
────────────────────
The library: every roll in one parent folder, read from what contact already
writes (roll.yaml and the XMP sidecars), and a search across all their frames.

Nothing here knows about any UI, and nothing is written to disk.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .roll import IMAGE_EXTS, _normalize_date, _split_list_field, load_roll_yaml
from .sidecar import _read_xmp_meta


@dataclass
class Frame:
    image: Path
    meta: dict


@dataclass
class Roll:
    folder: Path
    info: dict                      # roll.yaml as a dict
    frames: list[Frame]             # tagged frames only, in file order
    images: list[Path]              # all images in the folder, tagged or not
    signature: tuple = field(default=(), repr=False, compare=False)

    @property
    def image_count(self) -> int:
        return len(self.images)

    @property
    def cover(self) -> Path | None:
        return self.images[0] if self.images else None

    @property
    def year(self) -> str:
        return self.sort_date[:4]

    @property
    def label(self) -> str:
        return self.info.get("label", "").strip() or self.folder.name

    @property
    def date(self) -> str:
        return self.info.get("date", "").strip()

    @property
    def sort_date(self) -> str:
        """Sortable "YYYY-MM" (or "YYYY"); rolls without a date sort last."""
        return _normalize_date(self.date)

    @property
    def locations(self) -> list[str]:
        return _split_list_field(self.info.get("location", ""))

    @property
    def people(self) -> list[str]:
        """Everyone marked on a frame, then anyone only listed in roll info."""
        on_frames = [p for f in self.frames for p in f.meta.get("people", [])]
        return list(dict.fromkeys([*on_frames, *_split_list_field(self.info.get("subjects", ""))]))

    @property
    def landmarks(self) -> list[str]:
        on_frames = [m for f in self.frames for m in f.meta.get("landmarks", [])]
        return list(dict.fromkeys([*on_frames, *_split_list_field(self.info.get("landmarks", ""))]))

    def place_of(self, frame: Frame) -> str:
        """Where a frame was taken: its own place, else the roll's if it has exactly one."""
        return frame.meta.get("place") or (self.locations[0] if len(self.locations) == 1 else "")


@dataclass
class Hit:
    roll: Roll
    frame: Frame


# ── Scanning ──────────────────────────────────────────────────────────────────


def _signature(folder: Path, images: list[Path]) -> tuple:
    """Changes whenever the roll's info, its images or any sidecar changes."""
    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return 0.0

    return (
        mtime(folder / "roll.yaml"),
        tuple((img.name, mtime(img.with_suffix(".xmp"))) for img in images),
    )


def scan_roll(folder: Path, previous: Roll | None = None) -> Roll | None:
    """Read one roll folder. Returns None if the folder is not a roll.

    A roll is a folder with images and either a roll.yaml or at least one sidecar.
    `previous` is an earlier scan of the same folder; it is returned as is when
    nothing in the folder changed.
    """
    try:
        images = sorted(
            f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        )
    except OSError:
        return None
    if not images:
        return None
    signature = _signature(folder, images)
    if previous is not None and previous.signature == signature:
        return previous
    tagged = [img for img in images if img.with_suffix(".xmp").exists()]
    if not tagged and not (folder / "roll.yaml").exists():
        return None
    return Roll(
        folder=folder,
        info=load_roll_yaml(folder),
        frames=[Frame(img, _read_xmp_meta(img.with_suffix(".xmp"))) for img in tagged],
        images=images,
        signature=signature,
    )


def scan_library(root: Path, previous: list[Roll] | None = None) -> list[Roll]:
    """Every roll directly inside `root`, newest first.

    Pass the result of the last scan as `previous` and unchanged rolls are not re-read.
    """
    known = {roll.folder: roll for roll in previous or []}
    try:
        folders = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith(".")]
    except OSError:
        return []
    rolls = [roll for d in folders if (roll := scan_roll(d, known.get(d))) is not None]
    # newest first; undated rolls last, by name
    return sorted(rolls, key=lambda r: (r.sort_date == "", _descending(r.sort_date), r.label.casefold()))


def _descending(text: str) -> tuple:
    return tuple(-ord(c) for c in text)


# ── Searching ─────────────────────────────────────────────────────────────────

# "person:ines" limits a word to one field. Several names lead to the same field.
_FIELD_ALIASES = {
    "person": "people", "people": "people", "who": "people",
    "landmark": "landmarks", "landmarks": "landmarks", "what": "landmarks",
    "place": "place", "where": "place", "location": "place",
    "tag": "tags", "tags": "tags",
    "film": "film", "camera": "camera", "lens": "lens",
    "date": "date", "year": "date",
    "roll": "roll", "label": "roll",
    "category": "category", "cat": "category",
    "file": "file",
}


def fold(text: str) -> str:
    """Lowercase and strip accents, so "zizkov" finds "Žižkov"."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _fields(roll: Roll, frame: Frame) -> dict[str, str]:
    """The searchable text of one frame, by field, already folded."""
    meta, info = frame.meta, roll.info
    raw = {
        "people": " | ".join(meta.get("people", [])),
        "landmarks": " | ".join(meta.get("landmarks", [])),
        "place": roll.place_of(frame) or " | ".join(roll.locations),
        "tags": " | ".join(meta.get("tags", [])),
        "film": info.get("film", ""),
        "camera": info.get("camera", ""),
        "lens": info.get("lens", ""),
        "date": roll.date,
        "roll": f"{roll.label} {roll.folder.name}",
        "category": meta.get("category", ""),
        "file": frame.image.name,
        "description": meta.get("description", ""),
    }
    return {key: fold(value) for key, value in raw.items()}


def parse_query(query: str) -> list[tuple[str | None, str]]:
    """Split a query into (field, text) terms. Quotes keep words together.

    `ines "national theatre" film:hp5` → [(None, "ines"), (None, "national theatre"),
    ("film", "hp5")]. An unknown prefix is searched as plain text, colon included.
    """
    terms: list[tuple[str | None, str]] = []
    for match in re.finditer(r'(?:(\w+):)?(?:"([^"]*)"|(\S+))', query):
        prefix, quoted, bare = match.groups()
        text = quoted if quoted is not None else bare
        field_name = _FIELD_ALIASES.get(prefix.casefold()) if prefix else None
        if prefix and field_name is None:
            text = f"{prefix}:{text}"
        if text.strip():
            terms.append((field_name, fold(text.strip())))
    return terms


def search(rolls: list[Roll], query: str) -> list[Hit]:
    """Frames matching every term of the query, in roll order (newest roll first).

    A plain term may match anywhere: description, tags, people, landmarks, place,
    category, file name, or the roll's label, film, camera, lens and date.
    An empty query matches nothing.
    """
    terms = parse_query(query)
    if not terms:
        return []
    hits: list[Hit] = []
    for roll in rolls:
        for frame in roll.frames:
            fields = _fields(roll, frame)
            everything = " \n ".join(fields.values())
            if all(text in (fields[name] if name else everything) for name, text in terms):
                hits.append(Hit(roll, frame))
    return hits


def all_frames(rolls: list[Roll]) -> list[Hit]:
    """Every tagged frame of the library, in roll order."""
    return [Hit(roll, frame) for roll in rolls for frame in roll.frames]


def facets(rolls: list[Roll]) -> dict[str, list[tuple[str, int]]]:
    """What there is to filter by, most frequent first: people and places by frame
    count, film stocks by roll count."""
    counts: dict[str, dict[str, int]] = {"people": {}, "place": {}, "film": {}}
    for roll in rolls:
        if roll.info.get("film"):
            counts["film"][roll.info["film"]] = counts["film"].get(roll.info["film"], 0) + 1
        for frame in roll.frames:
            for person in frame.meta.get("people", []):
                counts["people"][person] = counts["people"].get(person, 0) + 1
            place = roll.place_of(frame)
            if place:
                counts["place"][place] = counts["place"].get(place, 0) + 1
    return {
        key: sorted(values.items(), key=lambda item: (-item[1], item[0].casefold()))
        for key, values in counts.items()
    }
