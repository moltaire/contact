"""Rotation changes only the orientation flag of JPEGs and TIFFs, never their image
data; PNGs are turned exactly in their pixels."""

import pytest
from PIL import Image, ImageOps

from processor.orientation import (
    OrientationError,
    _jpeg_for_tests,
    read_orientation,
    rotate,
    rotated_flag,
)


def image_data(raw: bytes) -> bytes:
    """Everything from the start-of-scan marker on: the compressed pixels."""
    return raw[raw.index(b"\xff\xda"):]


def shown_size(path) -> tuple[int, int]:
    return ImageOps.exif_transpose(Image.open(path)).size


@pytest.mark.parametrize("exif_flag, other_exif", [(None, False), (1, False), (6, False),
                                                    (None, True), (8, True)])
def test_rotate_keeps_pixels_and_turns_the_image(tmp_path, exif_flag, other_exif):
    path = tmp_path / "frame.jpg"
    path.write_bytes(_jpeg_for_tests((30, 20), exif_flag, other_exif))
    before = path.read_bytes()
    start = read_orientation(path)
    assert start == (exif_flag or 1)

    flag = rotate(path, clockwise=True)
    after = path.read_bytes()
    assert image_data(after) == image_data(before)
    assert read_orientation(path) == flag == rotated_flag(start, True)
    if other_exif:
        assert Image.open(path).getexif().get(0x010F) == "Scanner Co"

    # four quarter turns bring it back to where it started
    for _ in range(3):
        rotate(path, clockwise=True)
    assert read_orientation(path) == start
    assert image_data(path.read_bytes()) == image_data(before)


def test_rotation_direction(tmp_path):
    path = tmp_path / "frame.jpg"
    path.write_bytes(_jpeg_for_tests((30, 20)))
    assert shown_size(path) == (30, 20)
    rotate(path, clockwise=True)
    assert shown_size(path) == (20, 30)
    assert read_orientation(path) == 6
    rotate(path, clockwise=False)
    rotate(path, clockwise=False)
    assert read_orientation(path) == 8


def test_flags():
    assert [rotated_flag(f, True) for f in (1, 6, 3, 8)] == [6, 3, 8, 1]
    assert [rotated_flag(f, False) for f in (1, 6, 3, 8)] == [8, 1, 6, 3]
    with pytest.raises(OrientationError):
        rotated_flag(2, True)


def test_other_files_are_refused(tmp_path):
    other = tmp_path / "frame.gif"
    Image.new("RGB", (4, 4)).save(other)
    with pytest.raises(OrientationError):
        rotate(other)
    fake = tmp_path / "fake.jpg"
    fake.write_bytes(b"not a jpeg")
    with pytest.raises(OrientationError):
        rotate(fake)
    assert fake.read_bytes() == b"not a jpeg"


def _pattern(size=(30, 20)) -> Image.Image:
    """An image whose rotation is visible in its pixels."""
    image = Image.new("RGB", size, (10, 10, 10))
    image.putpixel((0, 0), (250, 0, 0))
    return image


@pytest.mark.parametrize("with_flag", [False, True])
def test_tiff_turns_by_its_flag_and_keeps_pixels(tmp_path, with_flag):
    path = tmp_path / "frame.tif"
    _pattern().save(path, tiffinfo={0x0112: 1} if with_flag else {})
    before = path.read_bytes()

    assert rotate(path, clockwise=True) == 6
    after = path.read_bytes()
    assert read_orientation(path) == 6
    if with_flag:  # two bytes change, in place
        assert len(after) == len(before)
        assert sum(a != b for a, b in zip(before, after)) == 1
    else:  # the header points to an appended copy of IFD0; the rest is untouched
        assert after[:4] == before[:4] and after[8:len(before)] == before[8:]
    # shown turned (Pillow applies a TIFF's flag when it opens it; exif_transpose
    # covers older versions that leave it to the caller)
    assert ImageOps.exif_transpose(Image.open(path)).size == (20, 30)

    rotate(path, clockwise=False)
    assert read_orientation(path) == 1
    assert ImageOps.exif_transpose(Image.open(path)).size == (30, 20)
    assert path.read_bytes()[8:len(before)] == before[8:]


def test_png_turns_its_pixels_exactly(tmp_path):
    path = tmp_path / "frame.png"
    original = _pattern()
    original.save(path)
    assert rotate(path, clockwise=True) == 1
    with Image.open(path) as turned:
        assert turned.size == (20, 30)
        expected = original.transpose(Image.Transpose.ROTATE_270)
        assert turned.convert("RGB").tobytes() == expected.tobytes()
    rotate(path, clockwise=False)
    with Image.open(path) as back:
        assert back.convert("RGB").tobytes() == original.tobytes()
