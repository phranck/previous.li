# The film

A 30 second promo film for Previously, with sound. It is a [HyperFrames](https://github.com/heygen-com/hyperframes) project: the film is written as HTML, and HyperFrames renders it to MP4 in headless Chrome.

## Making it

HyperFrames needs Node 22 or later and FFmpeg. The two Python scripts need the environment `site/hero.py` uses, with SciPy added for the sound:

```bash
python3 -m venv .venv && .venv/bin/pip install numpy pillow scipy
```

From the repository root, draw the parts, compose the sound, check the film and the television, and render:

```bash
.venv/bin/python promo/parts.py
.venv/bin/python promo/soundtrack.py
npm --prefix promo run check
npm --prefix promo run render
```

The render runs in two stages. The first renders the film itself into `promo/tv/film.mp4`. The second plays that on a CRT television and writes the result to `promo/renders/previously.mp4`, which is the film as it goes out.

`npm --prefix promo run dev` opens the film in the HyperFrames Studio, where it plays and every part of it can be edited. `npm --prefix promo run dev:tv` opens the television, which shows whatever the last render put into `promo/tv/film.mp4`.

## How it is put together

- `index.html` is the film. It holds the cue sheet, the ground every scene stands on, the screen switching on and off, and the two sound tracks.
- `tv/` is a second HyperFrames project, the television. It plays the rendered film with the HyperFrames CRT treatment on it: curvature, scanlines, a slight channel separation, bloom, vignette and grain, set in `data-color-grading` on its video. Over that it draws what the treatment has no control for, which is the phosphor stripes, the light on the glass and the hum bar rolling through the picture. The film's sound plays from the video, so it is defined only in the film.
- `compositions/` holds one file per scene, in the order they play.
- The cue sheet in `index.html` is the one place where a moment that a picture and a sound share is written down. The scenes read it through `assets/film.js`, and `soundtrack.py` reads it out of `index.html`.
- `parts.py` draws the Merge button, the cursor and the two smeared logos with the code in `site/hero.py`, so the film and the page draw them the same way.
- `soundtrack.py` synthesizes all of the music and mixes it with the effects into `assets/music.flac` and `assets/effects.flac`.
- `site` links to `../site`, because HyperFrames serves only the project's own folder, and the film uses the page's stylesheet, type, mark, icons and screenshot.

## What belongs to somebody else

- Inconsolata in `assets/fonts/` is under the SIL Open Font License, which `OFL.txt` beside it carries.
- The five recorded effects in `assets/sfx/` are under the Pixabay Content License, as `CREDITS.md` there says.
- The two window buttons in `assets/next/` are cut out of a screenshot of NeXTSTEP 3.3 by the admin's `design/extract.py`, and are not covered by this repository's license.
- GSAP is loaded from jsDelivr when the film plays or renders, and comes under [GSAP's standard license](https://gsap.com/standard-license).

NeXT, NeXTSTEP, OPENSTEP and the NeXT cube logo are registered trademarks of Apple Computer, Inc. The Raspberry Pi mark belongs to Raspberry Pi Ltd.
