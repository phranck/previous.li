#!/usr/bin/env python3
"""Draws the pictures a Pi running Previously shows while it starts and while
it shuts down: the circuit board racing in from the left, on black, and the
same with "Shutting down..." under it.

    .venv/bin/python site/splash.py

It writes site/splash.png and site/splash-shutdown.png. Previously's
design/mark.py fetches both from main, and its package build turns them into
the pictures it draws onto the screen (phranck/previously#625 and #636).

The board and its trail are the hero's, out of board.py and hero.py, so the
pictures and the page show one drawing.

Previously draws a picture as it is: it never scales it, centres it where it is
smaller than the screen and clips it evenly on both sides where it is larger
(admin/previously/splash.py). So the board is drawn at a whole multiple of its
48 rows, and the picture carries as much black on the right as the trail is
long on the left, which puts the board itself in the middle of every screen.
The shutdown picture carries as much black above the board as its text takes
below, so the board stands where it stood at boot.

It needs what hero.py needs: numpy, Pillow, rsvg-convert and the network.
"""

import pathlib

import hero
from PIL import Image, ImageDraw, ImageFont

HERE = pathlib.Path(__file__).parent
DESTINATION = HERE / "splash.png"
SHUTDOWN_DESTINATION = HERE / "splash-shutdown.png"

#: Screen pixels to each pixel of the board's drawing, which is 72 by 48. At 3
#: the board is 216 by 144, and the picture fits whole on any screen from 800
#: by 480 up.
UNIT = 3
BOARD_ROWS = 48

#: The most colours the board and its trail are drawn in: the board's own
#: exactly and the trail's gradient dithered into the rest, which is the look
#: phranck/previously#625 settled on.
COLOURS = 223

#: How often a colour has to occur in the board to count as one of its own
#: rather than as an edge of the logo smoothed between two of them.
BOARD_COLOUR_PIXELS = 20

BLACK = (0, 0, 0)

#: What the shutdown picture says under the board, in the site's face and in
#: its softer ink, `--ink-soft` in site.css, at the size the page sets a large
#: line in, `--text-lg`.
SHUTDOWN_TEXT = "Shutting down..."
FACE = HERE / "fonts" / "inter-variable-latin.woff2"
INK_SOFT = (0xA6, 0xA6, 0xB4)
TEXT_SIZE = 21

#: How far below the board the text stands.
TEXT_GAP = 24


def laid_out():
    """The board and its trail on black, before the colours are counted.

    Returns:
        The RGB picture, and the board alone at the size it stands in it.
    """
    height = UNIT * BOARD_ROWS
    sharp = hero.pi_picture()
    trail, reach = hero.smear(sharp, "left")
    scale = height / sharp.height
    board = sharp.resize((round(sharp.width * scale), height), Image.NEAREST)
    trail = trail.resize((round(trail.width * hero.STREAK_SHRINK * scale), height), Image.LANCZOS)
    offset = round(reach * scale)

    picture = Image.new("RGBA", (2 * offset + board.width, height), BLACK + (255,))
    picture.alpha_composite(trail)
    picture.alpha_composite(board, (offset, 0))
    return picture.convert("RGB"), board


def reduced(picture, board):
    """The picture in COLOURS colours or fewer.

    The board's own colours go into the palette exactly, so the board stays as
    sharp as its drawing, and the trail's gradient takes the rest of the
    palette, dithered.

    Args:
        picture: The RGB picture laid_out made.
        board: The board alone, whose colours are kept.

    Returns:
        The RGB picture.
    """
    own = [colour for count, colour in board.convert("RGB").getcolors(1 << 20)
           if count >= BOARD_COLOUR_PIXELS]
    left = COLOURS - len(own)
    rest = picture.quantize(colors=left, method=Image.Quantize.MEDIANCUT).getpalette()[:left * 3]
    palette = [value for colour in own for value in colour] + rest
    holder = Image.new("P", (1, 1))
    holder.putpalette(palette + [0] * (768 - len(palette)))
    return picture.quantize(palette=holder, dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")


def shutting_down(logo):
    """The boot picture with SHUTDOWN_TEXT centred under the board.

    Args:
        logo: The boot picture, whose middle is the board's middle.

    Returns:
        The RGB picture, as wide as the boot picture and taller by the text and
        its gap twice over, once below the board and once above it as black.
    """
    face = ImageFont.truetype(str(FACE), TEXT_SIZE)
    left, top, right, bottom = face.getbbox(SHUTDOWN_TEXT)
    band = TEXT_GAP + (bottom - top)
    picture = Image.new("RGB", (logo.width, logo.height + 2 * band), BLACK)
    picture.paste(logo, (0, band))
    ImageDraw.Draw(picture).text(
        ((logo.width - (right - left)) / 2 - left, band + logo.height + TEXT_GAP - top),
        SHUTDOWN_TEXT, font=face, fill=INK_SOFT)
    return picture


def main():
    picture, board = laid_out()
    logo = reduced(picture, board)
    colours = len(logo.getcolors(1 << 24))
    if colours > COLOURS:
        raise SystemExit(f"{colours} colours, and the board and its trail take {COLOURS}.")
    logo.save(DESTINATION, optimize=True)
    print(f"{DESTINATION.name}: {logo.width} by {logo.height}, {colours} colours, "
          f"the board {board.width} by {board.height} in the middle.")

    shutdown = shutting_down(logo)
    shutdown.save(SHUTDOWN_DESTINATION, optimize=True)
    print(f"{SHUTDOWN_DESTINATION.name}: {shutdown.width} by {shutdown.height}, "
          f"with {SHUTDOWN_TEXT!r} under the board.")


if __name__ == "__main__":
    main()
