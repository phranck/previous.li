# previous.li

The page at [previous.li](https://previous.li/), which is where [Previously](https://github.com/phranck/previously) is explained and where its install script is served from. Previously turns a Raspberry Pi into a machine that boots straight into NeXTSTEP under the Previous emulator.

The page does not reproduce NeXTSTEP, because the admin tool already does that. The top of `site/site.css` says which three things on it are allusions to the original. It is dark and only dark, it sets no cookie of its own, and the one thing it fetches from elsewhere is [Umami](https://umami.layered.work/) on our own server, which stores nothing that identifies a reader.

## What is in it

| Path | What it is |
|---|---|
| `index.html` | the page, and the only one |
| `site/site.css`, `site/site.js` | its styles and the little script it runs |
| `site/icons.svg` | every icon on the page, as one sprite |
| `site/icons.py` | fetches those icons at a pinned version and writes that sprite |
| `site/fonts/` | Inter, with its licence beside it |
| `site/og-image.svg` | the source of the link preview |
| `site/og.html` | holds that source at exactly 1200 by 630, to be screenshotted |
| `site/shots/` | the pictures the page shows |
| `CNAME`, `robots.txt`, `sitemap.xml` | what the host and the crawlers read |
| `install.sh` | written here by the release workflow of `phranck/previously`, never by hand |

It needs no build step. Open `index.html` and it is the page.

## Where the pictures come from

`site/shots/og.png` is what a link to the page unfolds into elsewhere. Its source is `site/og-image.svg`, where the gradient, the arrow, the shadows and the two lines of text are all editable, and where both pictures are embedded so the file stands on its own. Change that, then render it at exactly 1200 by 630: `site/og.html` holds it at that size for the purpose, so a screenshot of that page's viewport is the new `og.png`. The text is set in Helvetica, which macOS carries, with the two lines under the name in Helvetica Neue Medium, because Helvetica itself holds only Regular and Bold.

The same picture with its corners rounded to 33 pixels is the hero of the admin tool's own README, and it lives in that repository as `docs/readme-hero.png`. The radius is the site's own 24 point card radius at the width the README shows it. GitHub strips `style` out of the HTML in a Markdown file, so a rounded corner has to be in the file itself, and the social preview here stays square because a service that puts it on its own background would show the cut corners.

`site/shots/workspace.png` is a screenshot of the admin tool running on a Pi, taken at twice the size it is shown at so a Retina display gets one picture pixel per device pixel.

## The third-party material

The interface icons are [Phosphor](https://phosphoricons.com/) in its duotone weight, under MIT, and the GitHub mark is [Simple Icons](https://simpleicons.org/), under CC0 1.0. `site/icons.py` fetches both at a pinned version and writes `site/icons.svg`, so add a glyph there and run it rather than editing that file. The face is [Inter](https://rsms.me/inter/), under the SIL Open Font License, whose text sits beside the font in `site/fonts/`.

## install.sh

The script this page serves as `https://previous.li/install.sh` is not written here. Its source is `install.sh` in [phranck/previously](https://github.com/phranck/previously), where the thing it installs also lives, and that repository's release workflow writes it into this one. Editing the copy here would put a second version of it in the world, and the one people run would be the one that drifted.

## Licence

MIT, as [phranck/previously](https://github.com/phranck/previously) is.
