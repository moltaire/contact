"""
contact_gui/files.py
────────────────────
HTTP routes that serve images from the open roll folder: cached, upright
thumbnails for the UI and the raw files the contact sheet links to.
Only files directly inside the currently open folder are ever served.
"""

import hashlib
import io
import os
from pathlib import Path
from urllib.parse import quote

from fastapi import Body, HTTPException
from fastapi.responses import FileResponse, Response
from nicegui import app
from PIL import Image, ImageOps

from processor.pipeline import rebuild_contact_sheet
from processor.roll import IMAGE_EXTS
from processor.sidecar import _read_xmp_meta, write_xmp

from .state import state

_SIZES = (160, 320, 1600)
_cache: dict[tuple[str, float, int], bytes] = {}
_CACHE_LIMIT = 6000  # the library shows eight small previews per roll
# Previews are also kept on disk, so a library is only slow the very first time.
# They are keyed by file, size and modification time: an edited or rotated scan
# simply gets a new preview; old ones are harmless and can be deleted at any time.
PREVIEW_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "contact" / "previews"


def thumb_url(image: Path, size: int = 320) -> str:
    """URL of an upright JPEG preview. The mtime keeps the browser cache honest."""
    return f"/thumb/{size}/{quote(image.name)}?v={int(image.stat().st_mtime)}"


def roll_file_url(name: str) -> str:
    return f"/roll/{quote(name)}"


def library_thumb_url(image: Path, size: int = 320) -> str:
    """Preview of a frame in any roll of the library, addressed as roll folder + file."""
    return (f"/library-thumb/{size}/{quote(image.parent.name)}/{quote(image.name)}"
            f"?v={int(image.stat().st_mtime)}")


def _plain(name: str) -> bool:
    return bool(name) and "/" not in name and "\\" not in name and not name.startswith(".")


def _resolve(name: str) -> Path:
    folder = state.folder
    if folder is None or "/" in name or "\\" in name or name.startswith("."):
        raise HTTPException(404)
    path = folder / name
    if not path.is_file():
        raise HTTPException(404)
    return path


def _render(path: Path, size: int) -> bytes:
    """An upright JPEG preview: from memory, else from disk, else made now and kept."""
    mtime = path.stat().st_mtime
    key = (str(path), mtime, size)
    if key in _cache:
        return _cache[key]
    name = hashlib.sha1(f"{path}|{mtime}|{size}".encode()).hexdigest() + ".jpg"
    stored = PREVIEW_DIR / name[:2] / name
    try:
        data = stored.read_bytes()
    except OSError:
        img = Image.open(path)
        img.draft("RGB", (size, size))  # JPEG: decode at a reduced scale, much faster
        img = ImageOps.exif_transpose(img)
        img.thumbnail((size, size))
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85)
        data = buf.getvalue()
        try:
            stored.parent.mkdir(parents=True, exist_ok=True)
            tmp = stored.with_suffix(".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, stored)
        except OSError:
            pass  # no disk cache — still works, just slower next time
    if len(_cache) >= _CACHE_LIMIT:
        _cache.clear()
    _cache[key] = data
    return data


def warm_previews(images: list[Path], size: int) -> None:
    """Make previews ahead of time. Blocking — run it off the event loop."""
    for image in images:
        try:
            _render(image, size)
        except Exception:
            continue


# Plain `def` routes run in FastAPI's thread pool, so Pillow never blocks the event loop.
@app.get("/thumb/{size}/{name}")
def thumb(size: int, name: str) -> Response:
    path = _resolve(name)
    if size not in _SIZES or path.suffix.lower() not in IMAGE_EXTS:
        raise HTTPException(404)
    try:
        data = _render(path, size)
    except Exception:
        raise HTTPException(415, "cannot render this image") from None
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.get("/library-thumb/{size}/{roll}/{name}")
def library_thumb(size: int, roll: str, name: str) -> Response:
    """Only images one level below the library folder are served."""
    root = state.library_root
    if root is None or not _plain(roll) or not _plain(name) or size not in _SIZES:
        raise HTTPException(404)
    path = root / roll / name
    if not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
        raise HTTPException(404)
    try:
        data = _render(path, size)
    except Exception:
        raise HTTPException(415, "cannot render this image") from None
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "max-age=86400"})


@app.post("/api/star")
def star(payload: dict = Body(...)) -> dict:
    """The contact sheet, shown inside the app, saves a favourite to the frame's sidecar."""
    path = _resolve(str(payload.get("name", "")))
    sidecar = path.with_suffix(".xmp")
    if path.suffix.lower() not in IMAGE_EXTS or not sidecar.exists():
        raise HTTPException(404)
    meta = {**_read_xmp_meta(sidecar), "starred": bool(payload.get("starred"))}
    write_xmp(path, meta, state.roll)
    rebuild_contact_sheet(state.folder, state.roll)  # the file on disk stays in step
    return {"starred": meta["starred"]}


@app.get("/roll/{name}")
def roll_file(name: str) -> FileResponse:
    """The contact sheet (index.html) and the images it references by relative path."""
    path = _resolve(name)
    if path.name != "index.html" and path.suffix.lower() not in IMAGE_EXTS:
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "no-cache"})
