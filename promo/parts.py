#!/usr/bin/env python3
"""Draws the pieces of the film that the page already draws: the Merge button,
the cursor, and the two logos with the smear each one leaves.

    .venv/bin/python promo/parts.py

site/hero.py owns all of them. This imports its drawings and its smear rather
than carrying copies, so a change to the button or the arrow there reaches the
page and the film alike once both scripts have run.

The film needs them apart where the page has them as one picture, because each
moves on its own: the button builds itself and is pressed, the cursor travels,
and the logos arrive from the edges. The button also needs a raised state, which
the page never shows, because on the page it has already been pressed.

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

#: The button before it is pressed. A raised button is lit from the top left,
#: so its two edges trade places with the pressed one's, and the corner where
#: the lit edges met now joins two shadowed ones. The colors are hero.py's own.
RAISED_INK = {
    **hero.BUTTON_INK,
    "D": hero.BUTTON_INK["H"],
    "H": hero.BUTTON_INK["D"],
    "B": hero.BUTTON_INK["D"],
}


def pixel_svg(rows, inks):
    """A pixel drawing as an SVG one unit per cell, so CSS gives it its size.

    Each color is one path, for the reason hero.shape_of states: neighboring
    rectangles leave antialiased seams wherever the picture is scaled.
    """
    width, height = len(rows[0]), len(rows)
    paths = "\n  ".join(
        f'<path fill="{color}" d="{hero.shape_of(hero.cells_of(rows, mark), 1, 0, 0)}"/>'
        for mark, color in inks.items()
        if hero.cells_of(rows, mark))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
            f'width="{width}" height="{height}">\n  {paths}\n</svg>\n')


def write_logo(picture, towards, name):
    """The logo as the page draws it, and its smear beside it.

    The smear comes back at half the size it was worked out at and reaches one
    logo width past the logo, which is hero.STREAK's reach. The composition
    lines the sharp logo up with the end of its trail from that reach, which
    write_geometry passes on.
    """
    picture.save(ASSETS / f"{name}.png", optimize=True)
    trail, _ = hero.smear(picture, towards)
    trail.save(ASSETS / f"{name}-trail.png", optimize=True)


def write_geometry():
    """What the composition needs to know about the drawings, in their own cells.

    The cursor is placed by its tip, and the press lands under the r of the
    label with the tip two cursor cells above the button's lower edge, exactly
    as hero.py places them. The composition reads all of it from here rather
    than counting cells a second time.
    """
    tip_x, tip_y = hero.tip_of(hero.CURSOR, "#")
    r_middle = hero.letter_middles(hero.cells_of(hero.BUTTON, "L"), len(hero.BUTTON[0]))[2]
    geometry = {
        "button": {"columns": len(hero.BUTTON[0]), "rows": len(hero.BUTTON),
                   "pressColumn": r_middle, "tipRise": 2},
        "cursor": {"columns": len(hero.CURSOR[0]), "rows": len(hero.CURSOR),
                   "tip": [tip_x, tip_y]},
        "pi": dict(zip(("width", "height"), Image.open(ASSETS / "pi.png").size, strict=True)),
        "cube": dict(zip(("width", "height"), Image.open(ASSETS / "cube.png").size, strict=True)),
        "streak": {"reach": hero.STREAK["reach"], "opacity": hero.STREAK["opacity"]},
        "mark": dict(zip(("width", "height"), Image.open(SITE / "logo.png").size, strict=True)),
    }
    (ASSETS / "parts.js").write_text(
        "// Written by promo/parts.py. Change that and run it again.\n"
        f"window.PARTS = {json.dumps(geometry)};\n")
    print(f"parts.js: {geometry}")


def main():
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / "merge-raised.svg").write_text(pixel_svg(hero.BUTTON, RAISED_INK))
    (ASSETS / "merge-pressed.svg").write_text(pixel_svg(hero.BUTTON, hero.BUTTON_INK))
    (ASSETS / "cursor.svg").write_text(
        pixel_svg(hero.CURSOR, {"O": "#ffffff", "#": "#000000"}))
    write_logo(hero.pi_picture(), "left", "pi")
    write_logo(hero.cube_picture(), "right", "cube")
    write_geometry()


if __name__ == "__main__":
    main()
