"""The circuit board that stands for the Raspberry Pi in the hero, in the mark and in the film.

Raspberry Pi Ltd allows its logo only beside the sale of its own products, so
none of these shows it. The board names the Pi instead. It is the one the
admin's Info window wears, drawn in phranck/previously as design/board.svg,
and it is fetched from there on every run, the way the page's install.sh
fetches its one source. The page, the film and the admin therefore show one
drawing, and a change to it reaches the page once these scripts run again.

The drawing is made on the grid of pixels the Info window shows it at, 60 by
48, and every edge in it falls between two pixels. It is rendered at that size
and enlarged here pixel by pixel, so each pixel it was drawn with becomes a
square of one colour. A height that is a whole multiple of 48 makes every one
of those squares the same size.

It needs rsvg-convert to render the drawing, and the network to fetch it.
"""

import functools
import io
import subprocess
import urllib.request

from PIL import Image

SOURCE = "https://raw.githubusercontent.com/phranck/previously/main/design/board.svg"


@functools.cache
def pixels():
    """The board at the size it is drawn at, one picture pixel to each of its own.

    Returns:
        An RGBA picture in which every pixel is a colour the drawing names or
        is transparent, because nothing on its grid is smoothed.
    """
    with urllib.request.urlopen(SOURCE) as answer:
        drawing = answer.read()
    picture = subprocess.run(["rsvg-convert", "-"], input=drawing,
                             capture_output=True, check=True).stdout
    return Image.open(io.BytesIO(picture)).convert("RGBA")


def aspect():
    """The board's width against its height."""
    width, height = pixels().size
    return width / height


def draw(height):
    """The board as a picture `height` pixels tall, on nothing.

    Every pixel of the drawing is enlarged to a block of one colour rather than
    blended with its neighbours, so the board stays as sharp as it was drawn.

    Args:
        height: The picture's height in whole pixels.

    Returns:
        An RGBA picture as wide as the board's own proportions make it.
    """
    return pixels().resize((round(aspect() * height), height), Image.Resampling.NEAREST)
