"""Rotation changes only the EXIF orientation flag, never the image data."""

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


def test_only_jpegs(tmp_path):
    path = tmp_path / "frame.tif"
    Image.new("RGB", (4, 4)).save(path)
    with pytest.raises(OrientationError):
        rotate(path)
    fake = tmp_path / "fake.jpg"
    fake.write_bytes(b"not a jpeg")
    with pytest.raises(OrientationError):
        rotate(fake)
    assert fake.read_bytes() == b"not a jpeg"
