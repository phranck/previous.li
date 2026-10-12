"""The circuit board that stands for the Raspberry Pi in the hero, in the bar, in the mark and in the film.

Raspberry Pi Ltd allows its logo only beside the sale of its own products, so
none of these shows it. The board names the Pi instead. It is the Raspberry Pi
5 the admin's Info window wears, drawn in phranck/previously as
admin/web/parts/board-pi5.svg, and it is fetched from there on every run, the
way the page's install.sh fetches its one source. The page, the film and the
admin therefore show one drawing, and a change to it reaches the page once
these scripts run again.

The board is drawn on a grid of 72 by 48 pixels and every edge but the NeXT
logo's falls between two of them, so at a height that is a whole multiple of
48 every pixel of it comes out as a square of one colour. The logo on its
processor is a vector, so it is drawn sharp at whatever size the board is
rendered at. That is why every picture here is rendered from the drawing at
its own size rather than enlarged from a small one.

The film also takes the NeXT logo out of the drawing, so the letters it sticks
on a black cube are the same vector the board carries.

It needs rsvg-convert to render the drawing, and the network to fetch it.
"""

import functools
import io
import re
import subprocess
import urllib.request

from PIL import Image

SOURCE = "https://raw.githubusercontent.com/phranck/previously/main/admin/web/parts/board-pi5.svg"

#: The NeXT logo inside the drawing, by the id board-pi5.svg keeps for it, and the
#: black of the cube its letters stand on.
NEXT_LOGO = "next-logo"
NEXT_BODY = "#000000"


@functools.cache
def drawing():
    """The board's SVG document, as the admin serves it."""
    with urllib.request.urlopen(SOURCE) as answer:
        return answer.read().decode("utf-8")


def size():
    """The board's own width and height, in the pixels it is drawn on."""
    root = re.search(r"<svg\b[^>]*>", drawing()).group(0)
    return tuple(int(re.search(rf'\b{side}="(\d+)"', root).group(1)) for side in ("width", "height"))


def aspect():
    """The board's width against its height."""
    width, height = size()
    return width / height


def inner():
    """Everything the drawing holds, without the svg element around it.

    For placing the board inside another drawing, which gives it an svg
    element of its own with the place and size it stands at there.
    """
    return re.search(r"<svg\b[^>]*>(.*)</svg>", drawing(), re.DOTALL).group(1)


def render(document, height):
    """An SVG document as a picture `height` pixels tall, on nothing.

    Args:
        document: The SVG document, as text.
        height: The picture's height in whole pixels.

    Returns:
        An RGBA picture as wide as the document's own proportions make it.
    """
    picture = subprocess.run(["rsvg-convert", "--height", str(height), "-"], input=document.encode("utf-8"),
                             capture_output=True, check=True).stdout
    return Image.open(io.BytesIO(picture)).convert("RGBA")


def draw(height):
    """The board as a picture `height` pixels tall, on nothing."""
    return render(drawing(), height)


def next_logo():
    """The NeXT logo on the board's processor, as its three kinds of path.

    The logo draws the cube's black faces first and its coloured letters over
    them, and the black it draws after the letters is the hole in the e. Every
    coordinate is absolute and in the logo's own units, which are far finer
    than the board's.

    Returns:
        The path data of the cube's faces, the letters as pairs of fill and
        path data, and the path data of the holes in the letters.
    """
    logo = re.search(rf'<g id="{NEXT_LOGO}"[^>]*>(.*?)</g>', drawing(), re.DOTALL).group(1)
    paths = re.findall(r'<path fill="(#[0-9a-fA-F]+)" d="([^"]+)"/>', logo)
    first = next(index for index, (fill, _) in enumerate(paths) if fill.lower() != NEXT_BODY)
    faces = [data for _, data in paths[:first]]
    letters = [(fill, data) for fill, data in paths[first:] if fill.lower() != NEXT_BODY]
    holes = [data for fill, data in paths[first:] if fill.lower() == NEXT_BODY]
    return faces, letters, holes
