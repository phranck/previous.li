#!/usr/bin/env python3
"""Cuts rounded corners into the link preview, for the README to open on.

    .venv/bin/python site/readme-hero.py

It reads shots/og.png and writes shots/readme-hero.png. The README shows the
picture with rounded corners, and GitHub removes the style attribute from the
HTML it renders a README from, so a border-radius in the markup does nothing
there. The corners are cut into the file instead, with transparency outside
them. shots/og.png itself stays square, because a service that lays it on a
background of its own would show the cut.

The README sets the width the picture is shown at, and the radius in the file
is the radius wanted on screen scaled by how much that width shrinks the
picture. The width is read out of README.md, so the two cannot disagree.

It needs Pillow, which is not in the standard library:

    .venv/bin/pip install pillow
"""

import pathlib
import re

from PIL import Image, ImageDraw

HERE = pathlib.Path(__file__).parent
SOURCE = HERE / "shots" / "og.png"
DESTINATION = HERE / "shots" / "readme-hero.png"
README = HERE.parent / "README.md"

#: The corner on screen, in points, which is the page's own card radius.
CORNER = 24

#: How much finer the mask is drawn than the picture, so its curve is smooth
#: once it is brought down to the picture's own pixels.
SUPERSAMPLE = 4


def shown_width():
    """The width README.md shows the hero at, read from its img tag.

    Raises:
        SystemExit: when README.md shows no readme-hero.png with a width,
            because the radius would otherwise be worked out for a guess.
    """
    found = re.search(r'<img src="site/shots/readme-hero\.png"[^>]*width="(\d+)"', README.read_text())
    if not found:
        raise SystemExit("README.md shows no site/shots/readme-hero.png with a width.")
    return int(found.group(1))


def main():
    picture = Image.open(SOURCE).convert("RGBA")
    radius = round(CORNER * picture.width / shown_width())

    large = tuple(side * SUPERSAMPLE for side in picture.size)
    mask = Image.new("L", large, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, large[0] - 1, large[1] - 1), radius * SUPERSAMPLE, fill=255)
    picture.putalpha(mask.resize(picture.size, Image.LANCZOS))

    picture.save(DESTINATION, optimize=True)
    print(f"{DESTINATION.name}: {picture.width} by {picture.height}, corners of {radius} pixels.")


if __name__ == "__main__":
    main()
