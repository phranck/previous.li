#!/usr/bin/env python3
"""Draws the link preview: the hero, the name, and what the name is.

    python3 site/og-image.py

It writes site/og-image.svg. Render that to the picture a social network or a
chat window actually shows:

    cd site && rsvg-convert -w 1200 og-image.svg -o shots/og.png && \\
        oxipng -o 4 --strip safe shots/og.png

og.html beside it holds the same thing at that size in a browser, for looking
at rather than for rendering.

The picture at the top is hero.svg, which site/hero.py draws and index.html
shows as the page's own opening. It is placed rather than copied, so a link to
the page unfolds into what the page opens on and the two cannot come apart.

Everything vertical is worked out here rather than written down. The three
blocks are stacked by the gaps between what is actually drawn, which is ink
against ink rather than box against box, and the stack is then centred in the
picture. Changing a type size or a gap moves everything below it.
"""

import pathlib
from xml.etree import ElementTree

HERE = pathlib.Path(__file__).parent

WIDTH, HEIGHT = 1200, 630

#: The workspace colour NeXTSTEP drew behind its windows, sinking towards the
#: bottom edge.
GROUND = ("#555577", "#3f3f5a")

#: Where Helvetica puts its ink, as shares of the type size. A capital reaches
#: this far above the baseline and a descender this far below it, so a line of
#: type can be stacked by what it draws rather than by the box it sits in.
CAP = 0.717
DESCENDER = 0.207

#: The hero, and how wide it stands here. Its shape is read out of the file
#: rather than stated, by hero_shape below.
HERO = {"file": "hero.svg", "width": 940}

#: The name, in the face NeXTSTEP set its whole interface in. It is the one
#: thing here in full white, so it is what the eye lands on.
NAME = {"text": "Previously", "size": 78, "tracking": -2.3, "ink": "#ffffff",
        "family": "Helvetica, Arial, sans-serif", "weight": "bold"}

#: And what the name is, with the word it nearly said struck through. It sits
#: a step under the name and the struck word a step under that, so the three
#: are read in the order they are meant in.
#:
#: Helvetica Neue rather than Helvetica for these two lines, because Helvetica
#: holds only Regular and Bold: asking it for a weight between the two lands on
#: Bold. Neue carries Medium, which is the semibold this wants.
CLAIM = {
    "lines": ["A Raspberry Pi that {struck}… ", "boots directly into NeXTSTEP"],
    "struck": "boosts",
    "size": 42,
    "leading": 1.21,
    "ink": "#d3d3e2",
    "struck_ink": "#b0b0c6",
    "family": "Helvetica Neue, Helvetica, Arial, sans-serif",
    "weight": "500",
}

#: What stands between one block of ink and the next.
GAP_HERO_NAME = 18
GAP_NAME_CLAIM = 36


def hero_shape():
    """How tall the hero is for a given width, and how much of that is drawn.

    Both are read off hero.svg, which records them, because the cursor's
    shadow leaves a band at the bottom that belongs to the picture and not to
    the drawing. Stacking against the picture's edge would leave a gap nobody
    can see, and stating the numbers here would put a measurement of hero.py's
    work in a file that does not do it.
    """
    root = ElementTree.parse(HERE / HERO["file"]).getroot()
    height = float(root.get("height"))
    return height / float(root.get("width")), float(root.get("data-ink-height")) / height


def main():
    ratio, drawn = hero_shape()
    hero_height = HERO["width"] * ratio
    hero_ink = hero_height * drawn

    # Every offset below is measured from the top of the hero, which is the top
    # of the group's ink. The group is placed afterwards, in one line.
    name_base = hero_ink + GAP_HERO_NAME + NAME["size"] * CAP
    claim_base = (name_base + NAME["size"] * DESCENDER
                  + GAP_NAME_CLAIM + CLAIM["size"] * CAP)
    claim_last = claim_base + CLAIM["size"] * CLAIM["leading"] * (len(CLAIM["lines"]) - 1)
    group = claim_last + CLAIM["size"] * DESCENDER

    top = (HEIGHT - group) / 2
    struck = (f'<tspan font-style="italic" fill="{CLAIM["struck_ink"]}"'
              f' text-decoration="line-through">{CLAIM["struck"]}</tspan>')
    lines = "\n".join(
        f'  <text x="{WIDTH / 2:g}" y="{top + claim_base + CLAIM["size"] * CLAIM["leading"] * number:g}"'
        f' filter="url(#lift-soft)"\n'
        f'        font-family="{CLAIM["family"]}" font-weight="{CLAIM["weight"]}"'
        f' font-size="{CLAIM["size"]}"\n'
        f'        fill="{CLAIM["ink"]}" text-anchor="middle">{line.format(struck=struck)}</text>'
        for number, line in enumerate(CLAIM["lines"]))

    document = f"""<?xml version="1.0" encoding="UTF-8"?>
<!--
  Written by site/og-image.py. Change that and run it again.
-->
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"
     width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">

  <defs>
    <linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="{GROUND[0]}"/>
      <stop offset="1" stop-color="{GROUND[1]}"/>
    </linearGradient>

    <!-- The name and the claim lift off the ground the same way: a tight
         shadow that sets the letters off it and a wide one that gives them
         somewhere to sit. The claim takes the softer of the two, because it
         is the quieter line. The colour is a deeper version of the ground
         rather than black, and the picture above them carries its own. -->
    <filter id="lift" x="-20%" y="-20%" width="140%" height="160%">
      <feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#10101c" flood-opacity="0.55"/>
      <feDropShadow dx="0" dy="8" stdDeviation="11" flood-color="#10101c" flood-opacity="0.6"/>
    </filter>

    <filter id="lift-soft" x="-20%" y="-20%" width="140%" height="160%">
      <feDropShadow dx="0" dy="2" stdDeviation="2" flood-color="#10101c" flood-opacity="0.28"/>
      <feDropShadow dx="0" dy="6" stdDeviation="8" flood-color="#10101c" flood-opacity="0.3"/>
    </filter>
  </defs>

  <rect width="{WIDTH}" height="{HEIGHT}" fill="url(#ground)"/>

  <!-- One machine turning into another, which is the whole of what this
       project does. The Pi is on the left because that is what somebody starts
       with. -->
  <image x="{(WIDTH - HERO['width']) / 2:g}" y="{top:g}"
         width="{HERO['width']}" height="{hero_height:g}" xlink:href="{HERO['file']}"/>

  <text x="{WIDTH / 2:g}" y="{top + name_base:g}" filter="url(#lift)"
        font-family="{NAME['family']}" font-weight="{NAME['weight']}" font-size="{NAME['size']}"
        letter-spacing="{NAME['tracking']}" fill="{NAME['ink']}" text-anchor="middle">{NAME['text']}</text>

{lines}
</svg>
"""
    destination = HERE / "og-image.svg"
    destination.write_text(document)
    print(f"{destination.name}: the group is {group:.0f} tall in {HEIGHT}, "
          f"so it starts at {top:.0f} and ends at {top + group:.0f}.")


if __name__ == "__main__":
    main()
