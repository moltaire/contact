"""
processor/sidecar.py
────────────────────
XMP sidecar read/write and image loading helpers.
No internal imports — stdlib only.
"""

import base64
import json
import re
import subprocess
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _apply_exif_orientation(data: bytes) -> bytes:
    """Bake the EXIF orientation into the pixels.

    Scanners often store portrait frames as landscape pixels plus an orientation
    flag. Ollama ignores the flag, so without this the model sees the frame sideways.
    Returns the input unchanged if Pillow is unavailable or the image is already upright.
    """
    try:
        import io

        from PIL import Image, ImageOps

        img = Image.open(io.BytesIO(data))
        if img.getexif().get(0x0112, 1) == 1:
            return data
        img = ImageOps.exif_transpose(img)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=90)
        return buf.getvalue()
    except Exception:
        return data


def _load_image_b64(path: Path, max_pixels: int = 1500) -> str:
    """Return a base64-encoded, upright JPEG, downscaled via macOS sips to speed up inference."""
    data = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = Path(tmp.name)
        result = subprocess.run(
            ["sips", "-Z", str(max_pixels), "-s", "format", "jpeg", str(path), "--out", str(tmp_path)],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and tmp_path.stat().st_size > 0:
            data = tmp_path.read_bytes()
        tmp_path.unlink(missing_ok=True)
    except Exception:
        pass
    if data is None:
        data = path.read_bytes()
    return base64.b64encode(_apply_exif_orientation(data)).decode()


def _xe(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _xe_decode(s: str) -> str:
    return (
        s.replace("&quot;", '"')
        .replace("&gt;", ">")
        .replace("&lt;", "<")
        .replace("&amp;", "&")
    )


def _list_field(tag: str, items: list, container: str = "Bag") -> str:
    """An rdf:Bag (unordered) or rdf:Seq (ordered) property; nothing if the list is empty."""
    if not items:
        return ""
    lis = "\n".join(f"          <rdf:li>{_xe(i)}</rdf:li>" for i in items)
    return (
        f"      <{tag}>\n        <rdf:{container}>\n{lis}\n"
        f"        </rdf:{container}>\n      </{tag}>\n"
    )


def write_xmp(image_path: Path, meta: dict, roll: dict) -> Path:
    """Write the sidecar for one frame.

    Besides the model's output, meta may carry what the photographer added in review:
      people    — names of the people in this frame
      landmarks — named things in it: buildings, monuments, venues ("Neue Nationalgalerie")
      place     — where it was taken, as "City, Country" (overrides the roll's location list)
      notes     — facts told to the model ("this is the Parthenon"), kept so a re-tag can reuse them
    Names, landmarks and the place are also written as keywords so that other software
    finds them, and into the standard IPTC fields: sublocation, city, country.
    """
    people = meta.get("people") or []
    landmarks = meta.get("landmarks") or []
    place = meta.get("place") or ""
    keywords = list(dict.fromkeys(
        [*meta.get("tags", []), *people, *landmarks, *([place] if place else [])]
    ))
    # City and country come from the frame's place, or from the roll when it has exactly one
    roll_locations = [v.strip() for v in roll.get("location", "").split("|") if v.strip()]
    where = place or (roll_locations[0] if len(roll_locations) == 1 else "")
    segments = [s.strip() for s in where.split(",") if s.strip()]
    city, country = (segments[-2], segments[-1]) if len(segments) >= 2 else ("", "")
    tags_xml = "\n".join(f"      <rdf:li>{_xe(t)}</rdf:li>" for t in keywords)

    def field(tag: str, value: str) -> str:
        return f"      <{tag}>{_xe(value)}</{tag}>\n" if value else ""

    xmp = (
        '<?xpacket begin="\ufeff" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
        '  <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
        '    <rdf:Description rdf:about=""\n'
        '      xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
        '      xmlns:xmp="http://ns.adobe.com/xap/1.0/"\n'
        '      xmlns:Iptc4xmpCore="http://iptc.org/std/Iptc4xmpCore/1.0/xmlns/"\n'
        '      xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/"\n'
        '      xmlns:photoshop="http://ns.adobe.com/photoshop/1.0/"\n'
        '      xmlns:film="http://ns.contact.local/1.0/">\n'
        + field("dc:description", meta.get("description", ""))
        + "      <dc:subject>\n"
        + "        <rdf:Bag>\n"
        + tags_xml + "\n"
        + "        </rdf:Bag>\n"
        + "      </dc:subject>\n"
        + field("xmp:CreateDate", roll.get("date", ""))
        + field("Iptc4xmpCore:Location", "; ".join(landmarks) or place or roll.get("location", ""))
        + field("photoshop:City", city)
        + field("photoshop:Country", country)
        + _list_field("Iptc4xmpExt:PersonInImage", people)
        + _list_field("film:landmarks", landmarks)
        + field("film:place", place)
        + _list_field("film:userNotes", meta.get("notes") or [], "Seq")
        + field("film:stock", roll.get("film", ""))
        + field("film:camera", roll.get("camera", ""))
        + field("film:lens", roll.get("lens", ""))
        + field("film:notes", roll.get("notes", ""))
        + field("film:category", meta.get("category", "other"))
        + field("film:visionRaw", meta.get("vision_raw", ""))
        + field("film:processedAt", datetime.now(timezone.utc).isoformat())
        + '    </rdf:Description>\n'
        + '  </rdf:RDF>\n'
        + '</x:xmpmeta>\n'
        + '<?xpacket end="w"?>'
    )

    xmp_path = image_path.with_suffix(".xmp")
    xmp_path.write_text(xmp, encoding="utf-8")
    return xmp_path


_EMPTY_META = {
    "description": "", "category": "other", "tags": [], "vision_raw": "",
    "people": [], "landmarks": [], "place": "", "notes": [],
}


def _read_list(content: str, tag: str) -> list:
    block = re.search(rf"<{tag}>(.*?)</{tag}>", content, re.DOTALL)
    if not block:
        return []
    return [_xe_decode(i) for i in re.findall(r"<rdf:li>([^<]+)</rdf:li>", block.group(1))]


def _read_xmp_meta(xmp_path: Path) -> dict:
    """Read back everything write_xmp stores about a frame."""
    try:
        content = xmp_path.read_text(encoding="utf-8")
    except Exception:
        return {**_EMPTY_META, "tags": [], "people": [], "landmarks": [], "notes": []}

    def text(tag: str) -> str:
        m = re.search(rf"<{tag}>(.*?)</{tag}>", content, re.DOTALL)
        return _xe_decode(m.group(1).strip()) if m else ""

    people = _read_list(content, "Iptc4xmpExt:PersonInImage")
    landmarks = _read_list(content, "film:landmarks")
    place = text("film:place")
    # Names, landmarks and the place are mirrored into the keywords on write; take them
    # out again so that `tags` holds only the descriptive tags.
    mirrored = {*people, *landmarks, place}
    # Sidecars written before landmarks were their own field hold them inside the place
    # ("Charles Bridge, Prague, Czechia"): split the local part off.
    segments = [s.strip() for s in place.split(",") if s.strip()]
    if len(segments) >= 3:
        local, place = ", ".join(segments[:-2]), ", ".join(segments[-2:])
        if local not in landmarks:
            landmarks = [*landmarks, local]
    return {
        "description": text("dc:description"),
        "category":    text("film:category") or "other",
        "tags":        [t for t in _read_list(content, "dc:subject") if t not in mirrored],
        # Carried along so that editing a frame doesn't drop the model's original text
        "vision_raw":  text("film:visionRaw"),
        "people":      people,
        "landmarks":   landmarks,
        "place":       place,
        "notes":       _read_list(content, "film:userNotes"),
    }
