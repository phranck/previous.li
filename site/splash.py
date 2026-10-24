#!/usr/bin/env python3
"""Draws the picture a Pi running Previously shows from power-on until
NeXTSTEP appears: the circuit board racing in from the left, on black.

    .venv/bin/python site/splash.py

It writes site/splash.png. Previously's design/mark.py fetches that file from
main, and its package build turns it into the TGA the kernel draws as its
fullscreen logo (phranck/previously#625).

The board and its trail are the hero's, out of board.py and hero.py, so the
picture and the page show one drawing.

The kernel draws the picture as it is: it never scales it, centres it where it
is smaller than the screen and clips it evenly on both sides where it is larger
(fb_set_logo_from_file in drivers/video/fbdev/core/fb_logo.c, raspberrypi/linux
rpi-6.18.y). So the board is drawn at a whole multiple of its 48 rows, and the
picture carries as much black on the right as the trail is long on the left,
which puts the board itself in the middle of every screen.

It needs what hero.py needs: numpy, Pillow, rsvg-convert and the network.
"""

import pathlib

import hero
from PIL import Image

HERE = pathlib.Path(__file__).parent
DESTINATION = HERE / "splash.png"

#: Screen pixels to each pixel of the board's drawing, which is 72 by 48. At 3
#: the board is 216 by 144, and the picture fits whole on any screen from 800
#: by 480 up.
UNIT = 3
BOARD_ROWS = 48

#: The most colours the picture may hold. The kernel keeps a palette of 224 and
#: draws a pixel past them in the first colour it met, and Raspberry Pi's
#: configure-splash refuses a picture that does not stay below that.
COLOURS = 223

#: How often a colour has to occur in the board to count as one of its own
#: rather than as an edge of the logo smoothed between two of them.
BOARD_COLOUR_PIXELS = 20

#: The colour the kernel fills the rest of the screen with is the picture's
#: first pixel, so that pixel has to be the black around the board.
BLACK = (0, 0, 0)


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
    """The picture in fewer colours than the kernel keeps.

    The board's own colours go into the palette exactly, so the board stays as
    sharp as its drawing, and the trail's gradient takes the rest of the
    palette, dithered.

    Args:
        picture: The RGB picture laid_out made.
        board: The board alone, whose colours are kept.

    Returns:
        The RGB picture, holding at most COLOURS colours.
    """
    own = [colour for count, colour in board.convert("RGB").getcolors(1 << 20)
           if count >= BOARD_COLOUR_PIXELS]
    left = COLOURS - len(own)
    rest = picture.quantize(colors=left, method=Image.Quantize.MEDIANCUT).getpalette()[:left * 3]
    palette = [value for colour in own for value in colour] + rest
    holder = Image.new("P", (1, 1))
    holder.putpalette(palette + [0] * (768 - len(palette)))
    return picture.quantize(palette=holder, dither=Image.Dither.FLOYDSTEINBERG).convert("RGB")


def main():
    picture, board = laid_out()
    logo = reduced(picture, board)
    colours = len(logo.getcolors(1 << 24))
    if colours > COLOURS:
        raise SystemExit(f"{colours} colours, and the kernel keeps {COLOURS + 1}.")
    if logo.getpixel((0, 0)) != BLACK:
        raise SystemExit(f"The first pixel is {logo.getpixel((0, 0))}, and the kernel would fill the screen with it.")

    logo.save(DESTINATION, optimize=True)
    print(f"{DESTINATION.name}: {logo.width} by {logo.height}, {colours} colours, "
          f"the board {board.width} by {board.height} in the middle.")


if __name__ == "__main__":
    main()
