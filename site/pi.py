"""The π that stands for the Raspberry Pi in the hero, in the mark and in the film.

Raspberry Pi Ltd allows its logo only beside the sale of its own products, so
none of these shows it. The π names the board instead. It is Nunito Black's own
glyph, which the SIL Open Font License allows in a logo, and it wears the
logo's colours in an arrangement of its own: the roof green, the legs red, and
a black joint between them as wide as the outline around it.

hero.py draws it with that outline and logo.py without, because on the cube's
black face the face itself is the outline. Both are this one drawing at two
sizes, so the π that arrives in the hero is the π that stands in the cube.

It is written as an SVG and rasterised with rsvg-convert, which draws the
glyph's curves and the outline's round joins exactly at any size.
"""

import functools
import io
import math
import pathlib
import subprocess

import numpy
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from PIL import Image

HERE = pathlib.Path(__file__).parent

FONT = HERE / "fonts" / "nunito-black.ttf"
GLYPH = 0x03C0

#: The Raspberry Pi logo's red and green, each moved ΔE2000 0.60 away from it,
#: and black for the outline and the joint.
LEGS = "#cf1f55"
ROOF = "#47ac4b"
LINE = "#000000"

#: How wide the outline and the joint are, as a share of the glyph's height.
#: It is the Raspberry Pi logo's own proportion: 13.4 pixels of outline around
#: 237 pixels of berry.
OUTLINE = 0.056

#: How far down the glyph the ink has to keep standing as two legs before the
#: roof counts as ended, as a share of the picture's height. Where the roof
#: curves into a leg, a row can split in two for a pixel and join again.
SETTLE = 0.05


@functools.cache
def glyph():
    """The font's glyph set, the π's name in it, and the π's box in font units."""
    font = TTFont(FONT)
    glyphs = font.getGlyphSet()
    name = font.getBestCmap()[GLYPH]
    bounds = BoundsPen(glyphs)
    glyphs[name].draw(bounds)
    return glyphs, name, bounds.bounds


def aspect():
    """The glyph's width against its height, outline left out."""
    _, _, (left, bottom, right, top) = glyph()
    return (right - left) / (top - bottom)


def outline_path(height, left, top):
    """The glyph as SVG path data.

    Args:
        height: How tall the glyph is drawn, in pixels.
        left: Where the left edge of its box lands.
        top: Where the top edge of its box lands. A font counts upwards and a
            picture downwards, so the glyph is turned over on the way.

    Returns:
        The path data, in the picture's pixels.
    """
    glyphs, name, (left_edge, bottom_edge, _, top_edge) = glyph()
    scale = height / (top_edge - bottom_edge)
    pen = SVGPathPen(glyphs)
    glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale,
                                         left - left_edge * scale, top + top_edge * scale)))
    return pen.getCommands()


def rasterise(width, height, body):
    """An SVG body drawn into a transparent picture of the given size."""
    document = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
                f'viewBox="0 0 {width} {height}">{body}</svg>')
    picture = subprocess.run(["rsvg-convert", "-"], input=document.encode(),
                             capture_output=True, check=True).stdout
    return Image.open(io.BytesIO(picture)).convert("RGBA")


def roof_bottom(path, width, height):
    """The first row in which the ink stands as two legs and keeps standing so.

    Read off the drawn glyph rather than off its points, because a font's
    points say where a curve begins and not where the roof ends.
    """
    ink = numpy.asarray(rasterise(width, height, f'<path d="{path}"/>'))[:, :, 3] > 127
    starts = (numpy.diff(ink.astype(int), axis=1, prepend=0) == 1).sum(axis=1)
    settle = max(1, round(SETTLE * height))
    for row in range(height):
        if (starts[row:row + settle] >= 2).all():
            return row
    raise ValueError("the glyph stands on no legs")


def draw(height, outlined):
    """The π as a picture `height` pixels tall, on nothing.

    Args:
        height: The picture's height in whole pixels, outline included where
            there is one.
        outlined: Whether the black outline runs around the glyph. The joint
            between roof and legs is there either way, so the glyph reads the
            same on a ground of any colour and on the cube's black.

    Returns:
        An RGBA picture as wide as the glyph and its outline, rounded up to
        a whole pixel.
    """
    glyph_height = height / (1 + 2 * OUTLINE) if outlined else height
    ring = OUTLINE * glyph_height
    margin = ring if outlined else 0
    width = math.ceil(aspect() * glyph_height + 2 * margin)
    path = outline_path(glyph_height, margin, margin)
    joint = roof_bottom(path, width, height)

    under = (f'<path d="{path}" fill="{LINE}" stroke="{LINE}" stroke-width="{2 * ring:g}" '
             f'stroke-linejoin="round"/>' if outlined else "")
    return rasterise(width, height, f"""
  <defs><clipPath id="glyph"><path d="{path}"/></clipPath></defs>
  {under}
  <g clip-path="url(#glyph)">
    <rect width="{width}" height="{joint}" fill="{ROOF}"/>
    <rect y="{joint + ring:g}" width="{width}" height="{height}" fill="{LEGS}"/>
  </g>""")
