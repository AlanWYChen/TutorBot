"""Credential-free PNG crop subprocess; coordinates reference canonical page pixels."""

import math
import resource
import sys


def main() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    from typing import Any

    import pymupdf as native

    pymupdf: Any = native
    image = pymupdf.Pixmap(sys.stdin.buffer.read(25 * 1024 * 1024 + 1))
    x, y, width, height = map(float, sys.argv[1:5])
    left, top = math.floor(x), math.floor(y)
    right, bottom = math.ceil(x + width), math.ceil(y + height)
    if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
        raise ValueError("invalid crop")
    crop = pymupdf.Pixmap(image.colorspace, pymupdf.IRect(0, 0, right - left, bottom - top), False)
    crop.set_origin(left, top)
    crop.copy(image, pymupdf.IRect(left, top, right, bottom))
    sys.stdout.buffer.write(crop.tobytes("png"))


if __name__ == "__main__":
    main()
