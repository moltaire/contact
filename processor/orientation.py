"""
processor/orientation.py
────────────────────────
Turn a scan a quarter turn without losing anything.

JPEG and TIFF: only the orientation flag changes. Finder, Lightroom, darktable,
browsers and contact itself show the image turned accordingly, the image data is
copied byte for byte, and turning it back restores the original exactly.
- JPEG: only the EXIF segment is rewritten.
- TIFF: the flag lives in the file's first IFD. It is changed in place, or, when there
  is none yet, a copy of that IFD with the flag added is appended to the file and the
  header points to it; nothing else moves.

PNG: there is no orientation flag that other programs reliably honour, so the pixels
themselves are turned. PNG is lossless, so this is exact too; text chunks and the
colour profile are kept.

The new file is always written next to the old one and swapped in only once complete.
"""

import io
import os
import struct
import tempfile
from pathlib import Path

ORIENTATION = 0x0112

# Orientation flag → how far the stored pixels are turned clockwise for display.
# Mirrored orientations (2, 4, 5, 7) do not occur in scans and are left alone.
_DEGREES = {1: 0, 6: 90, 3: 180, 8: 270}
_FLAG = {degrees: flag for flag, degrees in _DEGREES.items()}

_JPEG_EXTS = {".jpg", ".jpeg"}
_TIFF_EXTS = {".tif", ".tiff"}
_PNG_EXTS = {".png"}


class OrientationError(ValueError):
    """The file cannot be rotated this way; the message says why."""


def can_rotate(path: Path) -> bool:
    return path.suffix.lower() in _JPEG_EXTS | _TIFF_EXTS | _PNG_EXTS


def _segments(data: bytes) -> list[tuple[int, int, int]]:
    """(marker, start, end) of each header segment, up to the start of the image data."""
    if data[:2] != b"\xff\xd8":
        raise OrientationError("not a JPEG file")
    segments, pos = [], 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise OrientationError("unexpected data in the JPEG header")
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker == 0xDA:  # start of scan: the image data follows, header is done
            break
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:  # markers without a length
            pos += 2
            continue
        (length,) = struct.unpack(">H", data[pos + 2:pos + 4])
        segments.append((marker, pos, pos + 2 + length))
        pos += 2 + length
    return segments


def _exif_segment(data: bytes, segments) -> tuple[int, int] | None:
    for marker, start, end in segments:
        if marker == 0xE1 and data[start + 4:start + 10] == b"Exif\x00\x00":
            return start, end
    return None


def _find_orientation(tiff: bytes) -> tuple[int, int, str] | None:
    """(value, offset of the value within `tiff`, byte order) of IFD0's orientation."""
    order = {b"II": "<", b"MM": ">"}.get(tiff[:2])
    if order is None:
        return None
    (ifd,) = struct.unpack(order + "I", tiff[4:8])
    if ifd + 2 > len(tiff):
        return None
    (count,) = struct.unpack(order + "H", tiff[ifd:ifd + 2])
    for n in range(count):
        entry = ifd + 2 + 12 * n
        if entry + 12 > len(tiff):
            return None
        tag, kind, number = struct.unpack(order + "HHI", tiff[entry:entry + 8])
        if tag == ORIENTATION and kind == 3 and number == 1:  # SHORT, one value
            (value,) = struct.unpack(order + "H", tiff[entry + 8:entry + 10])
            return value, entry + 8, order
    return None


def read_orientation(path: Path) -> int:
    """The orientation flag of a JPEG or TIFF; 1 (upright) when there is none."""
    data = path.read_bytes()
    if path.suffix.lower() in _TIFF_EXTS:
        found = _find_orientation(data)
        return found[0] if found else 1
    if path.suffix.lower() in _PNG_EXTS:
        return 1  # PNGs are turned in their pixels
    exif = _exif_segment(data, _segments(data))
    if exif is None:
        return 1
    found = _find_orientation(data[exif[0] + 10:exif[1]])
    return found[0] if found else 1


def rotated_flag(flag: int, clockwise: bool) -> int:
    if flag not in _DEGREES:
        raise OrientationError("this image is mirrored; contact only rotates")
    return _FLAG[(_DEGREES[flag] + (90 if clockwise else 270)) % 360]


def _with_orientation(data: bytes, flag: int) -> bytes:
    segments = _segments(data)
    exif = _exif_segment(data, segments)
    if exif is not None:
        start, end = exif
        tiff = data[start + 10:end]
        found = _find_orientation(tiff)
        if found:
            # The flag is already there: change its two bytes in place.
            _, offset, order = found
            at = start + 10 + offset
            return data[:at] + struct.pack(order + "H", flag) + data[at + 2:]
    # No flag yet: write an EXIF segment that has one, keeping any other EXIF fields.
    from PIL import Image

    existing = Image.Exif()
    if exif is not None:
        existing.load(data[exif[0] + 4:exif[1]])
    existing[ORIENTATION] = flag
    payload = existing.tobytes()
    if not payload.startswith(b"Exif\x00\x00"):
        payload = b"Exif\x00\x00" + payload
    if len(payload) + 2 > 0xFFFF:
        raise OrientationError("the EXIF data of this file is too large to rewrite")
    segment = b"\xff\xe1" + struct.pack(">H", len(payload) + 2) + payload
    if exif is not None:
        return data[:exif[0]] + segment + data[exif[1]:]
    # A new EXIF segment goes right after the JFIF header if there is one, else after SOI.
    insert = segments[0][2] if segments and segments[0][0] == 0xE0 else 2
    return data[:insert] + segment + data[insert:]


def _tiff_with_orientation(data: bytes, flag: int) -> bytes:
    order = {b"II": "<", b"MM": ">"}.get(data[:2])
    if order is None:
        raise OrientationError("not a TIFF file")
    (magic,) = struct.unpack(order + "H", data[2:4])
    if magic != 42:
        raise OrientationError("BigTIFF files are not supported")
    found = _find_orientation(data)
    if found:  # change the two bytes in place
        _, offset, order = found
        return data[:offset] + struct.pack(order + "H", flag) + data[offset + 2:]
    # No flag yet: append IFD0 again with an orientation entry, and point the header
    # at the copy. Values stored elsewhere in the file keep their offsets.
    (ifd,) = struct.unpack(order + "I", data[4:8])
    (count,) = struct.unpack(order + "H", data[ifd:ifd + 2])
    entries = [data[ifd + 2 + 12 * n:ifd + 14 + 12 * n] for n in range(count)]
    next_ifd = data[ifd + 2 + 12 * count:ifd + 6 + 12 * count]
    new = struct.pack(order + "HHIH", ORIENTATION, 3, 1, flag) + b"\x00\x00"
    entries.append(new)
    entries.sort(key=lambda e: struct.unpack(order + "H", e[:2])[0])  # tags ascend
    start = len(data) + (len(data) % 2)  # IFDs begin on a word boundary
    if start + 2 + 12 * len(entries) + 4 > 0xFFFFFFFF:
        raise OrientationError("the file is too large")
    block = struct.pack(order + "H", len(entries)) + b"".join(entries) + next_ifd
    return (data[:4] + struct.pack(order + "I", start) + data[8:]
            + b"\x00" * (start - len(data)) + block)


def _rotate_png(path: Path, clockwise: bool) -> bytes:
    from PIL import Image, PngImagePlugin

    with Image.open(path) as image:
        image.load()
        turned = image.transpose(Image.Transpose.ROTATE_270 if clockwise
                                 else Image.Transpose.ROTATE_90)
        info = PngImagePlugin.PngInfo()
        for key, value in (image.text or {}).items():
            info.add_text(key, value)
        options = {"pnginfo": info}
        for key in ("icc_profile", "dpi", "transparency", "gamma"):
            if key in image.info:
                options[key] = image.info[key]
        buf = io.BytesIO()
        turned.save(buf, "PNG", **options)
    return buf.getvalue()


def _replace(path: Path, updated: bytes) -> None:
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".rotate-", delete=False) as tmp:
        tmp.write(updated)
        tmp_path = Path(tmp.name)
    try:
        os.chmod(tmp_path, path.stat().st_mode)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)


def rotate(path: Path, clockwise: bool = True) -> int:
    """Turn a scan a quarter turn for display. Returns the new orientation flag (always
    1 for a PNG, whose pixels are turned)."""
    if not can_rotate(path):
        raise OrientationError("only JPEG, TIFF and PNG files can be rotated")
    suffix = path.suffix.lower()
    if suffix in _PNG_EXTS:
        _replace(path, _rotate_png(path, clockwise))
        return 1
    if suffix in _TIFF_EXTS:
        data = path.read_bytes()
        found = _find_orientation(data)
        flag = rotated_flag(found[0] if found else 1, clockwise)
        _replace(path, _tiff_with_orientation(data, flag))
        return flag
    data = path.read_bytes()
    exif = _exif_segment(data, _segments(data))
    found = _find_orientation(data[exif[0] + 10:exif[1]]) if exif else None
    flag = rotated_flag(found[0] if found else 1, clockwise)
    updated = _with_orientation(data, flag)

    # Safety: everything from the image data on must be byte for byte the same.
    old_scan = data.index(b"\xff\xda", _segments(data)[-1][2] if _segments(data) else 2)
    new_scan = updated.index(b"\xff\xda", _segments(updated)[-1][2])
    if data[old_scan:] != updated[new_scan:]:
        raise OrientationError("internal check failed; the file was not changed")
    _replace(path, updated)
    return flag


def _jpeg_for_tests(size=(30, 20), exif_flag: int | None = None, other_exif: bool = False) -> bytes:
    """A small JPEG, optionally with EXIF. Used by the tests."""
    from PIL import Image

    image = Image.new("RGB", size, (200, 30, 30))
    buf = io.BytesIO()
    if exif_flag is None and not other_exif:
        image.save(buf, "JPEG")
    else:
        exif = Image.Exif()
        if other_exif:
            exif[0x010F] = "Scanner Co"  # Make
        if exif_flag is not None:
            exif[ORIENTATION] = exif_flag
        image.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()
