#!/usr/bin/env python3
"""Draws the pictures a Pi running Previously shows while it starts and while
it shuts down: the circuit board racing in from the left, on black, with
"Retroforming..." under it in the one and "Shutting down..." in the other.

    .venv/bin/python site/splash.py

It writes site/splash.png and site/splash-shutdown.png. Previously's
design/mark.py fetches both from main, and its package build turns them into
the pictures it draws onto the screen (phranck/previously#625, #636 and #641).

The board and its trail are the hero's, out of board.py and hero.py, so the
pictures and the page show one drawing.

Previously draws a picture as it is: it never scales it, centres it where it is
smaller than the screen and clips it evenly on both sides where it is larger
(admin/previously/splash.py). So the board is drawn at a whole multiple of its
48 rows, and the picture carries as much black on the right as the trail is
long on the left, which puts the board itself in the middle of every screen.
Each picture carries as much black above the board as its line takes below,
and the line takes the same room in both, so the board stands at the same
place while the Pi starts and while it shuts down.

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

#: What the pictures say under the board: while the Pi starts, a play on
#: transforming into a retro machine, and while it shuts down. In the site's
#: face and in its softer ink, `--ink-soft` in site.css, at the size the page
#: sets a large line in, `--text-lg`.
BOOT_TEXT = "Retroforming..."
SHUTDOWN_TEXT = "Shutting down..."
FACE = HERE / "fonts" / "inter-variable-latin.woff2"
INK_SOFT = (0xA6, 0xA6, 0xB4)
TEXT_SIZE = 21

#: How far below the board the line stands.
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


def with_a_line(logo, text):
    """The board with one line centred under it.

    The room the line takes is the face's whole line, its ascent and its
    descent, rather than what one text reaches, so every line takes the same
    room and the board stands at the same place in every picture. The line is
    set on its baseline.

    Args:
        logo: The board and its trail, whose middle is the board's middle.
        text: What the line says.

    Returns:
        The RGB picture, as wide as the logo and taller by the line and its gap
        twice over, once below the board and once above it as black.
    """
    face = ImageFont.truetype(str(FACE), TEXT_SIZE)
    ascent, descent = face.getmetrics()
    band = TEXT_GAP + ascent + descent
    picture = Image.new("RGB", (logo.width, logo.height + 2 * band), BLACK)
    picture.paste(logo, (0, band))
    ImageDraw.Draw(picture).text(
        (logo.width / 2, band + logo.height + TEXT_GAP + ascent), text,
        font=face, fill=INK_SOFT, anchor="ms")
    return picture


def main():
    picture, board = laid_out()
    logo = reduced(picture, board)
    colours = len(logo.getcolors(1 << 24))
    if colours > COLOURS:
        raise SystemExit(f"{colours} colours, and the board and its trail take {COLOURS}.")
    for destination, text in ((DESTINATION, BOOT_TEXT), (SHUTDOWN_DESTINATION, SHUTDOWN_TEXT)):
        drawn = with_a_line(logo, text)
        drawn.save(destination, optimize=True)
        print(f"{destination.name}: {drawn.width} by {drawn.height}, with {text!r} "
              f"under the board {board.width} by {board.height} in the middle.")


if __name__ == "__main__":
    main()
