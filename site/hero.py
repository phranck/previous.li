#!/usr/bin/env python3
"""Draws the hero: the π and the NeXT cube smeared towards each other, a
pressed button between them, and the cursor that pressed it.

    python3 site/hero.py

It writes site/hero.svg, which index.html shows and og-image.svg places above
the name. Everything it needs is inside that one file, so it also works as the
source of an `<img>`, which cannot reach anything outside itself.

After the page Apple and NeXT put up in December 1996 to announce the purchase.
Everything is measured off
https://photos5.appleinsider.com/gallery/67459-141977-888-NeXT-xl.jpg

The smear is made here rather than in the SVG. A filter cannot do it: a blur
spreads a shape every way at once and leaves it recognisable, and the trick of
squashing a picture into a strip and stretching it back never happens either,
because SVG composes the transforms and rasterises once at the end, so nothing
is ever averaged. What is wanted is a picture shifted along one axis over and
over with a falling weight, which is what a moving thing leaves on film, and
that is done below with arithmetic on the pixels.

It needs numpy, Pillow and fontTools, which are not in the standard library,
and rsvg-convert, which pi.py draws the π with:

    python3 -m venv .venv && .venv/bin/pip install numpy pillow fonttools
    .venv/bin/python site/hero.py
"""

import base64
import io
import pathlib

import numpy
from pi import draw as draw_pi
from PIL import Image

HERE = pathlib.Path(__file__).parent

#: The cube's picture, and the part of it that is wanted.
CUBE = {"file": "next-cube.png", "box": (27, 0, 269, 296)}

#: How tall pi.py draws the π, outline included. It is twice what the page
#: shows, so the π stays sharp on a display with two device pixels to the
#: point and in the film, which shows it larger than the page does.
PI_HEIGHT = 544

#: Where each thing stands, and how tall. A logo's width follows from its picture.
#: The button is placed and the two logos follow from it, so neither of them
#: carries an x of its own: each stands off the button by GAP, and what moves
#: the button moves all three. Both the width and the height of the finished
#: picture follow from what ends up in it, so nothing is ever cut at an edge.
PLACE = {
    "pi": {"y": 106, "height": 272},
    "cube": {"y": 92, "height": 300},
    "button": {"x": 520, "y": 215},
}

#: What each logo leaves between itself and the button.
GAP = 38

#: How big one drawn pixel is, for the cursor and for the button.
CURSOR_UNIT = 8.5
BUTTON_UNIT = 5.25

#: The smear: how far it reaches as a share of the logo's own width, how many
#: copies are laid down along the way, and how fast each one fades. A higher
#: falloff keeps the smear tight to the logo, a lower one carries it further.
#: The reach is one logo width and the last copy carries no weight, so the
#: trail has faded to nothing by the time it has travelled the logo's length.
STREAK = {"reach": 1.0, "copies": 160, "falloff": 1.6, "opacity": 0.85}

#: The smear goes into the file at half the size it is worked out at. It holds
#: no detail to lose and this is most of the file's weight.
STREAK_SHRINK = 2

#: The button, as phranck drew it in site/editor.html. The face and the label
#: are the original's own colours; the two edges are greys turned the way a
#: pressed button turns them, because a pressed button is recessed rather than
#: outlined. The light edge is one step above the face and no more: on a dark
#: page a white one reads as a lit rim rather than as an edge catching light.
BUTTON_INK = {
    "F": "#454c56",   # the face
    "L": "#dedc6b",   # the label
    "D": "#14171d",   # the edge the shadow falls on, top and left
    "H": "#6d7482",   # the edge the light catches, bottom and right
    "B": "#aaaaaa",   # the corner where the two lit edges meet
}

BUTTON = [
    "DDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDDF",
    "DFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFH",
    "DFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFH",
    "DFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFH",
    "DFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFH",
    "DFFFFLFFFFFFFLFFFFFFFFFFFFFFFFFFFFFFFFFFH",
    "DFFFFLLFFFFFLLFFFFFFFFFFFFFFFFFFFFFFFFFFH",
    "DFFFFLLFFFFFLLFFLLLFFLFLFFLLFLFFLLLFFFFFH",
    "DFFFFLFLFFFLFLFLFFFLFLLFFLFFLLFLFFFLFFFFH",
    "DFFFFLFLFFFLFLFLFFFLFLFFFLFFFLFLFFFLFFFFH",
    "DFFFFLFFLFLFFLFLLLLLFLFFFLFFFLFLLLLLFFFFH",
    "DFFFFLFFLFLFFLFLFFFFFLFFFLFFFLFLFFFFFFFFH",
    "DFFFFLFFFLFFFLFLFFFLFLFFFLFFLLFLFFFLFFFFH",
    "DFFFFLFFFLFFFLFFLLLFFLFFFFLLFLFFLLLFFFFFH",
    "DFFFFFFFFFFFFFFFFFFFFFFFFFFFFLFFFFFFFFFFH",
    "DFFFFFFFFFFFFFFFFFFFFFFFFLFFFLFFFFFFFFFFH",
    "DFFFFFFFFFFFFFFFFFFFFFFFFFLLLFFFFFFFFFFFH",
    "DFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFH",
    "DFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFH",
    "FHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHB",
]

#: The arrow, as phranck drew it in site/editor.html against the original. A
#: hash for black, an O for white and a full stop for nothing, which is what
#: that editor exports. It is kept as a drawing rather than computed from the
#: black shape, because the white outline is not a rule: it carries a lip past
#: the tip, a longer run along the shoulder and a tail down the left edge.
CURSOR = [
    "............",
    ".OO.........",
    ".O#O........",
    ".O##O.......",
    ".O###O......",
    ".O####O.....",
    ".O#####O....",
    ".O######O...",
    ".O#######O..",
    ".O########O.",
    ".O#####OOOO.",
    ".O##O##O....",
    ".O#O.O##O...",
    ".OO..O##O...",
    "......O##O..",
    "......O##O..",
    ".......OO...",
    "............",
]

#: How far below itself each shadow reaches, so the picture is made tall enough
#: to hold it. A drop shadow runs to about its offset plus three times its
#: blur, past which there is nothing left to see.
BUTTON_SHADOW = {"dx": 6, "dy": 7, "blur": 4, "opacity": 0.55}
CURSOR_SHADOW = {"dx": 13, "dy": 15, "blur": 7, "opacity": 0.5}


def reach_of(shadow):
    """How far past the shape a shadow is still worth room."""
    return shadow["dy"] + shadow["blur"] * 3


def cells_of(rows, mark):
    """Every cell of one colour in a drawing."""
    return {(x, y) for y, row in enumerate(rows)
            for x, value in enumerate(row) if value == mark}


def tip_of(rows, mark):
    """Where the arrow's point sits in its own grid, so it can be put somewhere
    by its tip rather than by the corner of the sheet."""
    black = cells_of(rows, mark)
    top = min(y for _, y in black)
    return min(x for x, y in black if y == top), top


def shape_of(mask, unit, left, top):
    """Every cell of one colour as a single path, run by run.

    One path rather than one rectangle per run, because two rectangles sharing
    an edge are each antialiased against what is behind them and leave a seam
    along it. A cell is a whole number of drawing units and a unit need not be
    a whole number of pixels, so those seams fall wherever the picture is
    scaled. Inside one path the runs are filled as one region and there is no
    inside edge to soften.
    """
    parts = []
    for y in sorted({point[1] for point in mask}):
        row = sorted(x for x, other in mask if other == y)
        start = previous = row[0]
        for x in row[1:] + [None]:
            if x != previous + 1:
                width = (previous - start + 1) * unit
                parts.append(f'M{left + start * unit:g} {top + y * unit:g} '
                             f'h{width:g} v{unit:g} h{-width:g} Z')
                start = x
            previous = x
    return " ".join(parts)


def letter_middles(mask, width):
    """The middle column of each letter, found by the gaps between them.

    Read off the drawing, because that is where the letters are: the label is
    drawn cell by cell rather than set in a face, so nothing else knows where
    one letter ends and the next begins.
    """
    used = {x for x, _ in mask}
    middles, run = [], []
    for x in range(width + 1):
        if x in used:
            run.append(x)
        elif run:
            middles.append((run[0] + run[-1] + 1) / 2)
            run = []
    return middles


def inline(picture):
    """A picture as the address of itself, so the file needs nothing beside it."""
    carrier = io.BytesIO()
    picture.save(carrier, format="PNG", optimize=True)
    packed = base64.b64encode(carrier.getvalue()).decode("ascii")
    return f"data:image/png;base64,{packed}"


def pi_picture():
    """The π as the hero and the film show it: outlined, PI_HEIGHT tall."""
    return draw_pi(PI_HEIGHT, outlined=True)


def cube_picture():
    """The NeXT cube, cropped to itself."""
    return Image.open(HERE / CUBE["file"]).convert("RGBA").crop(CUBE["box"])


def smear(picture, towards):
    """A picture's smear: itself, laid down again and again along one axis.

    Each copy is one pixel further along and weaker than the last, and they are
    added in premultiplied alpha so a transparent pixel contributes nothing to
    the colour. What comes out is the picture's own colours drawn as bands in
    the order they stood in, which is what a thing moving sideways leaves behind.

    Returns the trail, and how far it reaches in the picture's own pixels.
    """
    source = numpy.asarray(picture, dtype=float) / 255.0
    height, width = source.shape[0], source.shape[1]

    alpha = source[:, :, 3:4]
    premultiplied = numpy.concatenate([source[:, :, :3] * alpha, alpha], axis=2)

    reach = round(width * STREAK["reach"])
    canvas = numpy.zeros((height, width + reach, 4))

    for step in range(STREAK["copies"]):
        share = step / (STREAK["copies"] - 1)
        weight = (1 - share) ** STREAK["falloff"]
        offset = round(share * reach)
        at = reach - offset if towards == "left" else offset
        canvas[:, at:at + width] += premultiplied * weight

    # Divided by what was laid down rather than by the peak, so the trail keeps
    # the logo's own strength where the copies pile up and fades from there.
    # Dividing by the peak flattens the whole thing instead.
    total = sum((1 - step / (STREAK["copies"] - 1)) ** STREAK["falloff"]
                for step in range(STREAK["copies"]))
    canvas /= total

    out_alpha = numpy.clip(canvas[:, :, 3:4], 0, 1)
    colour = numpy.divide(canvas[:, :, :3], numpy.where(out_alpha > 0.002, out_alpha, 1))
    flat = numpy.concatenate([numpy.clip(colour, 0, 1), out_alpha], axis=2)

    trail = Image.fromarray((flat * 255).astype("uint8"), "RGBA")
    return trail.resize((trail.width // STREAK_SHRINK, trail.height // STREAK_SHRINK),
                        Image.LANCZOS), reach


def main():
    pi, cube, button = PLACE["pi"], PLACE["cube"], PLACE["button"]
    button["w"] = len(BUTTON[0]) * BUTTON_UNIT
    button["h"] = len(BUTTON) * BUTTON_UNIT

    pi_sharp, cube_sharp = pi_picture(), cube_picture()
    pi_trail, pi_reach = smear(pi_sharp, "left")
    cube_trail, cube_reach = smear(cube_sharp, "right")

    # The trail picture is as tall as the logo and wider than it, so it is
    # placed by the logo's own box and grown from there. Its own pixels are
    # the source's, which the shrink above leaves the trail measured in.
    pi_scale = pi["height"] / (pi_trail.height * STREAK_SHRINK)
    cube_scale = cube["height"] / (cube_trail.height * STREAK_SHRINK)
    pi_trail_w = pi_trail.width * STREAK_SHRINK * pi_scale
    cube_trail_w = cube_trail.width * STREAK_SHRINK * cube_scale
    pi_logo_w = pi_trail_w - pi_reach * pi_scale
    cube_logo_w = cube_trail_w - cube_reach * cube_scale

    # Both logos close on the button by the same distance, measured from the
    # edge of what is drawn rather than from the corner of a picture, because
    # the trail carries a lot of empty room with it.
    pi["x"] = button["x"] - GAP - pi_logo_w
    cube["x"] = button["x"] + button["w"] + GAP

    black = cells_of(CURSOR, "#")
    white = cells_of(CURSOR, "O")
    tip_x, tip_y = tip_of(CURSOR, "#")

    # The tip sits under the r of the label, the third of its five letters,
    # which is where a pointer would be a moment after the press.
    r_middle = letter_middles(cells_of(BUTTON, "L"), len(BUTTON[0]))[2]
    cursor = {"x": button["x"] + r_middle * BUTTON_UNIT - tip_x * CURSOR_UNIT,
              "y": button["y"] + button["h"] - CURSOR_UNIT * 2 - tip_y * CURSOR_UNIT}

    # The picture is exactly as large as what stands in it, counting each trail
    # to where it has faded out and each shadow to where it has. Everything
    # then moves so the topmost and leftmost of them begin at nothing.
    #
    # data-ink-height goes on the root with the size, because the cursor's
    # shadow leaves a band at the bottom that is part of the picture and not
    # part of the drawing. Anything placing this file has to know where the
    # drawing ends, and og-image.py reads it from there rather than measuring
    # a picture it does not draw.
    left = pi["x"] - pi_reach * pi_scale
    top = min(pi["y"], cube["y"])
    width = cube["x"] + cube_trail_w - left
    drawn = [(pi["y"] + pi["height"], 0),
             (cube["y"] + cube["height"], 0),
             (button["y"] + button["h"], reach_of(BUTTON_SHADOW)),
             (cursor["y"] + len(CURSOR) * CURSOR_UNIT, reach_of(CURSOR_SHADOW))]
    height = max(bottom + shadow for bottom, shadow in drawn) - top
    ink = max(bottom for bottom, _ in drawn) - top
    for thing in (pi, cube, button, cursor):
        thing["x"] -= left
        thing["y"] -= top

    face = "\n    ".join(
        f'<path fill="{colour}" d="'
        + shape_of(cells_of(BUTTON, mark), BUTTON_UNIT, button["x"], button["y"])
        + '"/>'
        for mark, colour in BUTTON_INK.items())

    document = f"""<?xml version="1.0" encoding="UTF-8"?>
<!--
  Written by site/hero.py. Change that and run it again.
-->
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{width:g}" height="{height:g}" viewBox="0 0 {width:g} {height:g}"
     data-ink-height="{ink:g}">

  <defs>
    <!-- The shadow the button throws: offset, dark, barely spread, as the
         original has it. -->
    <filter id="thrown" x="-25%" y="-25%" width="170%" height="170%">
      <feDropShadow dx="{BUTTON_SHADOW['dx']}" dy="{BUTTON_SHADOW['dy']}"
                    stdDeviation="{BUTTON_SHADOW['blur']}"
                    flood-color="#000000" flood-opacity="{BUTTON_SHADOW['opacity']}"/>
    </filter>

    <!-- The cursor's, thrown further, because the cursor is above the button
         and its shadow falls on the button rather than beside it. At the
         button's own distance it hugs the arrow and reads as an edge. -->
    <filter id="thrown-far" x="-40%" y="-40%" width="200%" height="200%">
      <feDropShadow dx="{CURSOR_SHADOW['dx']}" dy="{CURSOR_SHADOW['dy']}"
                    stdDeviation="{CURSOR_SHADOW['blur']}"
                    flood-color="#000000" flood-opacity="{CURSOR_SHADOW['opacity']}"/>
    </filter>
  </defs>

  <!-- The π, arriving from the left, and the cube from the right, each as the
       trail it leaves. -->
  <image x="{pi['x'] - pi_reach * pi_scale:g}" y="{pi['y']:g}"
         width="{pi_trail_w:g}" height="{pi['height']}"
         opacity="{STREAK['opacity']}" xlink:href="{inline(pi_trail)}"/>
  <image x="{cube['x']:g}" y="{cube['y']:g}"
         width="{cube_trail_w:g}" height="{cube['height']}"
         opacity="{STREAK['opacity']}" xlink:href="{inline(cube_trail)}"/>

  <!-- and each logo itself, sharp, at the end of its own trail -->
  <image x="{pi['x']:g}" y="{pi['y']:g}"
         width="{pi_logo_w:g}" height="{pi['height']}"
         preserveAspectRatio="none"
         xlink:href="{inline(pi_sharp)}"/>
  <image x="{cube['x']:g}" y="{cube['y']:g}"
         width="{cube_logo_w:g}" height="{cube['height']}"
         preserveAspectRatio="none"
         xlink:href="{inline(cube_sharp)}"/>

  <!-- The button, pressed. A pressed button is recessed, so its bezel turns:
       the shadow falls on the top and the left, the light on the bottom and
       the right. -->
  <g filter="url(#thrown)">
    {face}
  </g>

  <!-- The cursor that pressed it. -->
  <g filter="url(#thrown-far)">
    <path fill="#ffffff" d="{shape_of(white, CURSOR_UNIT, cursor['x'], cursor['y'])}"/>
    <path fill="#000000" d="{shape_of(black, CURSOR_UNIT, cursor['x'], cursor['y'])}"/>
  </g>
</svg>
"""
    destination = HERE / "hero.svg"
    destination.write_text(document)
    print(f"{destination.name}, {width:.0f} by {height:.0f}, "
          f"{len(document) / 1024:.0f} KB.")


if __name__ == "__main__":
    main()
