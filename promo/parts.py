#!/usr/bin/env python3
"""Draws the pieces of the film that the page already draws: the π and the
NeXT cube, which flip onto the board a part to a module.

    .venv/bin/python promo/parts.py

site/hero.py owns both. This imports its drawings rather than carrying copies,
so a change there reaches the page and the film alike once both scripts have
run. The film needs them apart where the page has them as one picture, because
each arrives on the board on its own.

It writes into promo/assets/ and needs what hero.py needs: numpy, Pillow,
fontTools and rsvg-convert.
"""

import json
import pathlib
import sys

from PIL import Image

HERE = pathlib.Path(__file__).parent
SITE = HERE.parent / "site"
ASSETS = HERE / "assets"

sys.path.insert(0, str(SITE))
import hero


def write_logo(picture, name):
    """The logo as the page draws it, which the board shows a part to a
    module."""
    picture.save(ASSETS / f"{name}.png", optimize=True)


def write_geometry():
    """What the board needs to know about the drawings: the size of each logo
    and of the mark, in their own pixels, which it scales to the size it shows
    them at. The board reads them from here rather than measuring a second
    time."""
    geometry = {
        "pi": dict(zip(("width", "height"), Image.open(ASSETS / "pi.png").size, strict=True)),
        "cube": dict(zip(("width", "height"), Image.open(ASSETS / "cube.png").size, strict=True)),
        "mark": dict(zip(("width", "height"), Image.open(SITE / "logo.png").size, strict=True)),
    }
    (ASSETS / "parts.js").write_text(
        "// Written by promo/parts.py. Change that and run it again.\n"
        f"window.PARTS = {json.dumps(geometry)};\n")
    print(f"parts.js: {geometry}")


def main():
    ASSETS.mkdir(exist_ok=True)
    write_logo(hero.pi_picture(), "pi")
    write_logo(hero.cube_picture(), "cube")
    write_geometry()


if __name__ == "__main__":
    main()
