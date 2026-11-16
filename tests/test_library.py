"""Tests for the library scanner and the cross-roll search."""

import os
from pathlib import Path

from processor.library import facets, fold, parse_query, scan_library, scan_roll, search
from processor.roll import write_roll_yaml
from processor.sidecar import write_xmp


def make_roll(root: Path, name: str, info: dict, frames: dict[str, dict | None]) -> Path:
    """A roll folder with fake images; frames maps file name → metadata (None = untagged)."""
    folder = root / name
    folder.mkdir(parents=True)
    if info is not None:
        write_roll_yaml(folder, info)
    roll = info or {}
    for file_name, meta in frames.items():
        image = folder / file_name
        image.write_bytes(b"not really a jpeg")
        if meta is not None:
            write_xmp(image, {"category": "other", "tags": [], "description": "", **meta}, roll)
    return folder


def library(tmp_path: Path) -> Path:
    make_roll(tmp_path, "2023-09_prague", {
        "label": "Motorcycle Trip to Prague", "date": "2023-09", "film": "Ilford HP5 Plus",
        "camera": "Canon A-1", "location": "Prague, Czech Republic", "subjects": "Pippa",
    }, {
        "a_01.jpg": {"description": "The Žižkov Television Tower rises against the sky.",
                     "tags": ["tower", "sky"], "landmarks": ["Žižkov Television Tower"],
                     "category": "architecture"},
        "a_02.jpg": {"description": "Pippa, a striped cat, looks at the viewer.",
                     "tags": ["cat"], "people": ["Pippa"], "category": "nature"},
        "a_03.jpg": None,
    })
    make_roll(tmp_path, "2024-05_athens", {
        "label": "Athens", "date": "2024-05-12", "film": "Kodak Gold 200",
        "camera": "Minox 35 GT", "location": "Athens, Greece | Aegina, Greece",
    }, {
        "b_01.jpg": {"description": "The Parthenon stands above the city.",
                     "tags": ["temple", "columns"], "landmarks": ["Parthenon"],
                     "place": "Athens, Greece", "people": ["Ines"], "category": "architecture"},
        "b_02.jpg": {"description": "A harbour with fishing boats.", "tags": ["harbour", "boats"],
                     "place": "Aegina, Greece", "category": "landscape"},
    })
    make_roll(tmp_path, "undated", None, {"c_01.jpg": {"description": "A tower of crates."}})
    (tmp_path / "not-a-roll").mkdir()
    (tmp_path / "not-a-roll" / "notes.txt").write_text("hello")
    (tmp_path / ".hidden").mkdir()
    return tmp_path


def names(hits) -> list[str]:
    return [hit.frame.image.name for hit in hits]


# ── scanning ──────────────────────────────────────────────────────────────────


def test_scan_finds_rolls_newest_first_and_skips_other_folders(tmp_path):
    rolls = scan_library(library(tmp_path))
    assert [r.folder.name for r in rolls] == ["2024-05_athens", "2023-09_prague", "undated"]


def test_roll_summary_fields(tmp_path):
    prague = scan_library(library(tmp_path))[1]
    assert prague.label == "Motorcycle Trip to Prague"
    assert prague.date == "2023-09"
    assert prague.image_count == 3
    assert [f.image.name for f in prague.frames] == ["a_01.jpg", "a_02.jpg"]
    assert prague.cover.name == "a_01.jpg"
    assert prague.people == ["Pippa"]
    assert prague.landmarks == ["Žižkov Television Tower"]


def test_roll_without_label_uses_folder_name(tmp_path):
    assert scan_library(library(tmp_path))[2].label == "undated"


def test_frame_place_falls_back_to_a_single_roll_location(tmp_path):
    athens, prague, _ = scan_library(library(tmp_path))
    assert prague.place_of(prague.frames[0]) == "Prague, Czech Republic"
    assert athens.place_of(athens.frames[1]) == "Aegina, Greece"


def test_folder_without_images_is_not_a_roll(tmp_path):
    (tmp_path / "empty").mkdir()
    assert scan_roll(tmp_path / "empty") is None
    assert scan_library(tmp_path / "does-not-exist") == []


def test_rescan_reuses_unchanged_rolls_and_rereads_changed_ones(tmp_path):
    root = library(tmp_path)
    first = scan_library(root)
    again = scan_library(root, first)
    assert all(a is b for a, b in zip(first, again))

    sidecar = root / "2024-05_athens" / "b_02.xmp"
    stat = sidecar.stat()
    sidecar.write_text(sidecar.read_text().replace("fishing boats", "sailing boats"))
    os.utime(sidecar, (stat.st_atime, stat.st_mtime + 5))
    third = scan_library(root, again)
    assert third[0] is not again[0]
    assert "sailing boats" in third[0].frames[1].meta["description"]
    assert third[1] is again[1]


# ── searching ─────────────────────────────────────────────────────────────────


def test_plain_words_match_anywhere_and_all_must_match(tmp_path):
    rolls = scan_library(library(tmp_path))
    assert names(search(rolls, "tower")) == ["a_01.jpg", "c_01.jpg"]
    assert names(search(rolls, "tower sky")) == ["a_01.jpg"]
    assert names(search(rolls, "tower boats")) == []


def test_search_ignores_case_and_accents(tmp_path):
    rolls = scan_library(library(tmp_path))
    assert names(search(rolls, "ZIZKOV")) == ["a_01.jpg"]


def test_search_covers_people_landmarks_places_and_roll_fields(tmp_path):
    rolls = scan_library(library(tmp_path))
    assert names(search(rolls, "ines")) == ["b_01.jpg"]
    assert names(search(rolls, "parthenon")) == ["b_01.jpg"]
    assert names(search(rolls, "aegina")) == ["b_02.jpg"]
    assert names(search(rolls, "hp5")) == ["a_01.jpg", "a_02.jpg"]
    assert names(search(rolls, "minox")) == ["b_01.jpg", "b_02.jpg"]
    assert names(search(rolls, "2024")) == ["b_01.jpg", "b_02.jpg"]
    assert names(search(rolls, "motorcycle")) == ["a_01.jpg", "a_02.jpg"]


def test_people_listed_on_the_roll_do_not_match_every_frame(tmp_path):
    rolls = scan_library(library(tmp_path))
    assert names(search(rolls, "pippa")) == ["a_02.jpg"]


def test_field_prefix_limits_a_term_to_one_field(tmp_path):
    rolls = scan_library(library(tmp_path))
    assert names(search(rolls, "tag:tower")) == ["a_01.jpg"]
    assert names(search(rolls, "person:pippa")) == ["a_02.jpg"]
    assert names(search(rolls, "place:athens")) == ["b_01.jpg"]
    assert names(search(rolls, "film:gold place:aegina")) == ["b_02.jpg"]
    assert names(search(rolls, "cat:architecture")) == ["b_01.jpg", "a_01.jpg"]  # newest roll first


def test_quotes_keep_words_together(tmp_path):
    rolls = scan_library(library(tmp_path))
    assert names(search(rolls, '"television tower"')) == ["a_01.jpg"]
    assert names(search(rolls, '"tower television"')) == []


def test_empty_query_matches_nothing(tmp_path):
    assert search(scan_library(library(tmp_path)), "   ") == []


def test_parse_query():
    assert parse_query('ines "National Theatre" film:HP5 what:"Nová scéna" x:y') == [
        (None, "ines"), (None, "national theatre"), ("film", "hp5"),
        ("landmarks", "nova scena"), (None, "x:y"),
    ]


def test_fold():
    assert fold("Žižkov Nová SCÉNA") == "zizkov nova scena"


def test_facets_count_frames_for_people_and_places_and_rolls_for_film(tmp_path):
    found = facets(scan_library(library(tmp_path)))
    assert found["people"] == [("Ines", 1), ("Pippa", 1)]
    assert found["place"] == [("Prague, Czech Republic", 2), ("Aegina, Greece", 1),
                              ("Athens, Greece", 1)]
    assert found["film"] == [("Ilford HP5 Plus", 1), ("Kodak Gold 200", 1)]
