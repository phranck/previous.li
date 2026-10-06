#!/usr/bin/env python3
"""Builds the Previously mark and every icon the page links to.

The mark is the NeXT cube with the π standing where the N of its wordmark
stood. It is the π that pi.py draws for the hero, without the outer outline,
because the black face is that outline already. It lies in the plane of the
face the wordmark sits on, so it leans with the remaining letters instead of
floating in front of them.

    python3 logo.py

It writes logo.svg, logo.png, logo-mark.png, favicon.ico, apple-touch-icon.png,
icon-192.png, icon-512.png and site.webmanifest beside itself. Nothing here is
edited by hand: change a number in this file and run it.

The cube is read as a picture rather than as geometry. next-cube.png holds its
three faces as three separate shapes with transparent gaps between them, so the
face this needs is found by walking the file rather than by being measured once
and written down.
"""

import base64
import io
import math
import pathlib

import numpy
from pi import aspect as pi_aspect
from pi import draw as draw_pi
from PIL import Image

HERE = pathlib.Path(__file__).parent

# How much larger than the finished mark everything is composed, so a warped
# edge comes back down as a gradient rather than as a staircase.
SCALE = 8

# The N, read off next-cube.png. It is the one letter that goes.
LETTER_N = (250, 21, 22)

# Where the N stood on its face, in that face's own coordinates. The π fills
# the slot as far as its proportions let it and hangs from the slot's upper
# left corner, so it keeps the margins the N kept to the cube's edge and to
# the e beside it.
SLOT_U = (0.073, 0.460)
SLOT_V = (0.063, 0.464)

# The workspace colour NeXTSTEP drew behind its windows, which is what every
# picture of this project lies on. An icon that a system puts on a ground of
# its own choosing gets this one instead, because a black cube on an unknown
# ground is a black square.
GROUND = (85, 85, 119)

# How much of an icon's square is left empty around the mark. A home screen
# rounds the corners off, so the mark keeps clear of them.
MARGIN = 0.08

MASTER_HEIGHT = 1024
# The mark beside the wordmark in the bar stands about 24 pixels tall, so this
# covers it on a display with four device pixels to the point. It is a picture
# of its own rather than logo.svg, which carries both sources embedded and
# would put about 48kB on the first paint for a mark this size.
BAR_HEIGHT = 96
FAVICON_SIZES = (16, 32, 48, 64)
TOUCH_SIZE = 180
MANIFEST_SIZES = (192, 512)

# What the manifest says about the page it belongs to. The theme colour is the
# page's own, and index.html names it a second time in its theme-color meta;
# change one and change the other.
MANIFEST_NAME = "Previously"
MANIFEST_DESCRIPTION = "A Raspberry Pi that boots directly into NeXTSTEP."
MANIFEST_BACKGROUND = "#121218"
MANIFEST_THEME = "#121218"


# --- reading the two sources ------------------------------------------------

def shapes(image):
    """Every connected run of ink in the image, largest first.

    Iterative rather than recursive: the cube's own face is 27362 pixels and a
    recursive walk of it hits Python's stack limit.
    """
    alpha = image.getchannel("A").load()
    width, height = image.size
    seen = [[False] * height for _ in range(width)]
    found = []
    for start_x in range(width):
        for start_y in range(height):
            if seen[start_x][start_y] or alpha[start_x, start_y] < 128:
                continue
            stack = [(start_x, start_y)]
            seen[start_x][start_y] = True
            pixels = []
            while stack:
                x, y = stack.pop()
                pixels.append((x, y))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < width and 0 <= ny < height and not seen[nx][ny] and alpha[nx, ny] >= 128:
                        seen[nx][ny] = True
                        stack.append((nx, ny))
            found.append(pixels)
    found.sort(key=len, reverse=True)
    return found


def hull(points):
    """The convex hull of a set of pixels, by monotone chain."""
    points = sorted(set(points))
    if len(points) < 3:
        return points

    def build(ordered):
        chain = []
        for point in ordered:
            while len(chain) >= 2:
                (ax, ay), (bx, by) = chain[-2], chain[-1]
                if (bx - ax) * (point[1] - ay) - (by - ay) * (point[0] - ax) > 0:
                    break
                chain.pop()
            chain.append(point)
        return chain[:-1]

    return build(points) + build(points[::-1])


def face_frame(pixels):
    """A face of the cube, as a corner and the two vectors along its sides.

    Each face projects as a parallelogram, so its corners are where its four
    supporting lines cross. Taking the extreme pixel in each direction instead
    fails on the two foreshortened faces, where the topmost pixel and the
    rightmost pixel are the same corner and two of the four come out equal.
    """
    polygon = hull(pixels)

    # The two directions the sides run in, found by the length that runs in
    # each, so a few stray boundary pixels cannot outvote a whole side.
    groups = []
    for index, start in enumerate(polygon):
        end = polygon[(index + 1) % len(polygon)]
        vector = (end[0] - start[0], end[1] - start[1])
        length = math.hypot(*vector)
        if length < 2:
            continue
        angle = math.atan2(vector[1], vector[0]) % math.pi
        for group in groups:
            gap = abs(angle - group["angle"])
            if min(gap, math.pi - gap) < 0.09:
                group["length"] += length
                break
        else:
            groups.append({"angle": angle, "length": length})
    groups.sort(key=lambda group: group["length"], reverse=True)

    array = numpy.array(pixels, dtype=float)
    lines = []
    for group in groups[:2]:
        normal = numpy.array([-math.sin(group["angle"]), math.cos(group["angle"])])
        reach = array @ normal
        lines.append((normal, reach.max()))
        lines.append((-normal, (-reach).max()))

    found = []
    for one in lines[:2]:
        for other in lines[2:]:
            found.append(numpy.linalg.solve(numpy.array([one[0], other[0]]),
                                            numpy.array([one[1], other[1]])))

    centre = sum(found) / len(found)
    found.sort(key=lambda point: math.atan2(point[1] - centre[1], point[0] - centre[0]))
    start = min(range(len(found)), key=lambda index: found[index][1])
    quad = found[start:] + found[:start]
    # Anticlockwise from the topmost corner, so the fourth is the one the face
    # hangs from and anything placed on it stands upright.
    return quad[3], quad[0] - quad[3], quad[2] - quad[3]


def letter_to_black(image, colour):
    """Takes one letter back to the black it sits on.

    Matched by the direction of the colour rather than by its value, because a
    letter is antialiased against black: its edge pixels keep the hue and lose
    only the brightness, so a match on the value leaves the outline standing.
    """
    values = numpy.array(image).astype(float)
    rgb = values[:, :, 0:3]
    length = numpy.linalg.norm(rgb, axis=2)
    lit = length > 12
    direction = rgb / numpy.where(lit, length, 1)[:, :, None]
    wanted = numpy.array(colour, dtype=float)
    wanted /= numpy.linalg.norm(wanted)
    values[((direction @ wanted) > 0.985) & lit, 0:3] = 0
    return Image.fromarray(values.astype("uint8"))


# --- putting the mark together ----------------------------------------------

def slot_fit(aspect):
    """How much of the N's slot a shape of the given proportions fills.

    As much as it can without leaving the slot, in the face's own units, as a
    pair of its extent across and down the face.
    """
    room_u, room_v = SLOT_U[1] - SLOT_U[0], SLOT_V[1] - SLOT_V[0]
    if aspect >= room_u / room_v:
        return room_u, room_u / aspect
    return room_v * aspect, room_v


def glyph_placement(size, origin, across, down):
    """Where the π's own pixel grid lands on the face.

    Returns the point its first pixel sits at and one step along each of its
    axes, all in the cube picture's coordinates. The face is a square in space,
    so the π's own proportions apply to it directly rather than to the
    foreshortened shape on screen.
    """
    width, height = size
    used = slot_fit(width / height)
    at = origin + SLOT_U[0] * across + SLOT_V[0] * down
    return at, used[0] / width * across, used[1] / height * down


def build():
    """Returns the finished mark at SCALE times its own size, and its box."""
    cube = Image.open(HERE / "next-cube.png").convert("RGBA")
    origin, across, down = face_frame(shapes(cube)[0])

    # Drawn at about the size it lands at on the composed canvas, so the warp
    # below moves its pixels rather than enlarging them.
    _, used_v = slot_fit(pi_aspect())
    glyph = draw_pi(round(used_v * numpy.linalg.norm(down) * SCALE), outlined=False)
    at, step_x, step_y = glyph_placement(glyph.size, origin, across, down)

    forward = numpy.array([[step_x[0] * SCALE, step_y[0] * SCALE, at[0] * SCALE],
                           [step_x[1] * SCALE, step_y[1] * SCALE, at[1] * SCALE],
                           [0.0, 0.0, 1.0]])
    # PIL's affine maps output coordinates back to input ones.
    inverse = numpy.linalg.inv(forward)
    plate = letter_to_black(cube, LETTER_N)
    canvas = plate.resize((cube.size[0] * SCALE, cube.size[1] * SCALE), Image.LANCZOS)
    canvas.alpha_composite(glyph.transform(canvas.size, Image.AFFINE,
                                           tuple(inverse[0]) + tuple(inverse[1]),
                                           resample=Image.BICUBIC))

    box = tuple(value / SCALE for value in canvas.getbbox())
    return canvas, box, plate, glyph, (at, step_x, step_y)


# --- what comes out of it ---------------------------------------------------

def square(mark, size, ground=None, margin=MARGIN):
    """The mark centred in a square of the given size.

    The mark is taller than it is wide, so it is fitted to the height and the
    width follows. A ground of None leaves the square transparent.
    """
    room = round(size * (1 - 2 * margin))
    scaled = mark.copy()
    scaled.thumbnail((room, room), Image.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (ground or (0, 0, 0)) + (255 if ground else 0,))
    canvas.alpha_composite(scaled, ((size - scaled.size[0]) // 2, (size - scaled.size[1]) // 2))
    return canvas


def embedded(image):
    """One picture as a data URL, so the SVG stands on its own."""
    buffer = io.BytesIO()
    image.save(buffer, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def write_svg(box, plate, glyph, placement):
    """Writes the mark as the two pictures it is made of, and the map between.

    The π's matrix is the same one the raster build uses, so the file and the
    icons cannot drift apart: both come out of this script in one run.
    """
    at, step_x, step_y = placement
    left, top, right, bottom = box
    matrix = " ".join(f"{value:.6f}" for value in
                      (step_x[0], step_x[1], step_y[0], step_y[1], at[0], at[1]))

    document = f"""<?xml version="1.0" encoding="UTF-8"?>
<!--
  The Previously mark: the NeXT cube with the π standing where the N of its
  wordmark stood.

  Generated by logo.py. Do not edit: change a number there and run it, which
  writes this file and every icon beside it in the same pass.

  The cube below is next-cube.png with its N taken back to black, and the π is
  the one pi.py draws for the hero, without its outer outline, laid into the
  plane of the face the wordmark sits on. Both are embedded, so this file
  stands on its own.
-->
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{right - left:.0f}" height="{bottom - top:.0f}"
     viewBox="{left:.2f} {top:.2f} {right - left:.2f} {bottom - top:.2f}">

  <image x="0" y="0" width="{plate.size[0]}" height="{plate.size[1]}"
         xlink:href="{embedded(plate)}"/>

  <g transform="matrix({matrix})">
    <image x="0" y="0" width="{glyph.size[0]}" height="{glyph.size[1]}"
           xlink:href="{embedded(glyph)}"/>
  </g>
</svg>
"""
    (HERE / "logo.svg").write_text(document)
    return len(document)


def write_manifest():
    """Writes the manifest that names the two icons a home screen reaches for.

    It is written here rather than kept by hand, so the sizes it lists are the
    sizes that were actually produced.
    """
    icons = ",\n".join(
        f'    {{ "src": "icon-{size}.png", "sizes": "{size}x{size}", "type": "image/png" }}'
        for size in MANIFEST_SIZES
    )
    document = f"""{{
  "name": "{MANIFEST_NAME}",
  "short_name": "{MANIFEST_NAME}",
  "description": "{MANIFEST_DESCRIPTION}",
  "start_url": "/",
  "background_color": "{MANIFEST_BACKGROUND}",
  "theme_color": "{MANIFEST_THEME}",
  "icons": [
{icons}
  ]
}}
"""
    (HERE / "site.webmanifest").write_text(document)


def main():
    canvas, box, plate, glyph, placement = build()

    mark = canvas.crop(canvas.getbbox())
    width = round(mark.size[0] * MASTER_HEIGHT / mark.size[1])
    mark = mark.resize((width, MASTER_HEIGHT), Image.LANCZOS)
    mark.save(HERE / "logo.png", optimize=True)

    bar = mark.resize((round(mark.size[0] * BAR_HEIGHT / mark.size[1]), BAR_HEIGHT), Image.LANCZOS)
    bar.save(HERE / "logo-mark.png", optimize=True)

    # Transparent, because a browser puts a tab strip of its own colour behind
    # it and the cube's edges are gaps that then take that colour.
    square(mark, max(FAVICON_SIZES) * 4, margin=0.02).resize(
        (max(FAVICON_SIZES), max(FAVICON_SIZES)), Image.LANCZOS
    ).save(HERE / "favicon.ico", sizes=[(size, size) for size in FAVICON_SIZES])

    square(mark, TOUCH_SIZE * 4, GROUND).resize((TOUCH_SIZE, TOUCH_SIZE), Image.LANCZOS) \
        .save(HERE / "apple-touch-icon.png", optimize=True)

    for size in MANIFEST_SIZES:
        square(mark, size * 2, GROUND).resize((size, size), Image.LANCZOS) \
            .save(HERE / f"icon-{size}.png", optimize=True)

    write_manifest()
    characters = write_svg(box, plate, glyph, placement)
    print(f"logo.png {mark.size[0]}x{mark.size[1]}, logo-mark.png {bar.size[0]}x{bar.size[1]}, "
          f"favicon.ico {FAVICON_SIZES}, "
          f"apple-touch-icon.png {TOUCH_SIZE}, icons {MANIFEST_SIZES}, "
          f"site.webmanifest, logo.svg {characters} bytes")


if __name__ == "__main__":
    main()
