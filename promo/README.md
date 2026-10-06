# The film

A 32 second promo film for Previously, with sound. It is a [HyperFrames](https://github.com/heygen-com/hyperframes) project: the film is written as HTML, and HyperFrames renders it to MP4 in headless Chrome.

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

The render runs in two stages. The first, `npm --prefix promo run film`, renders the film itself into `promo/tv/film.mp4`. The second plays that on a CRT television and writes the result to `promo/renders/previously.mp4`, which is the film as it goes out. The check runs the first stage too, between checking the film and checking the television, because the television can only be checked with the film it plays.

The first stage encodes at CRF 4, close to lossless, and the second reads its frames as PNG, because whatever either of them loses is lost again in the final encode. The final encode is CRF 12. It keeps the grain and the scanlines, and gives a platform that encodes the video again a better original to start from.

`npm --prefix promo run dev` opens the film in the HyperFrames Studio, where it plays and every part of it can be edited. `npm --prefix promo run dev:tv` opens the television, which shows whatever the last render put into `promo/tv/film.mp4`.

## Taking the admin's windows

The admin on the board is made of windows taken out of a running admin, one at a time, and of its desk with no window on it. `site/shot.py` opens its own Chrome on the admin and takes them. It needs websocket-client:

```bash
.venv/bin/pip install websocket-client
.venv/bin/python site/shot.py open http://next.local:8810/
```

In that Chrome, open the File Viewer's Apps folder. Then take the three windows and the desk:

```bash
for name in files info pi; do .venv/bin/python site/shot.py window "$name" "promo/assets/admin/$name.png"; done
.venv/bin/python site/shot.py desk promo/assets/admin/desk.png
oxipng -o 4 --strip safe promo/assets/admin/*.png
```

A window comes out with four image pixels to each of NeXTSTEP's, which is what lets the film go close enough to show them. The board places each window by its size in NeXTSTEP pixels, and the check reports a picture whose size no longer matches.

## How it is put together

- `index.html` is the film. It holds the cue sheet, the screen switching on and off, and the two sound tracks.
- `tv/` is a second HyperFrames project, the television. It plays the rendered film with the HyperFrames CRT treatment on it: curvature, scanlines, a slight channel separation, bloom, vignette and grain, set in `data-color-grading` on its video. Over that it draws what the treatment has no control for, which is the phosphor stripes, the light on the glass, the hum bar rolling through the picture, and the set's bezel, whose opening gives the glass its round corners. The film's sound plays from the video, so it is defined only in the film.
- Both are 4:3, at 1440 by 1080, as a television of the time was. The board fills the glass, so the curve bends its sides as it would any picture that fills the screen. Its outer modules end just inside the opening in the bezel.
- `compositions/board.html` is the film's one scene, a split-flap board, and says what the board shows when. `assets/board.js` is the board itself: its modules, how a flap falls, and how a text, a picture or a flutter becomes the flips that show it.
- The cue sheet in `index.html` is the one place where a moment that a picture and a sound share is written down. The board reads it through `assets/film.js`, and `soundtrack.py` reads it out of `index.html`. Each turn of the board is on it, either under a cue of its own, such as the keystrokes of the install line, or among the flips. A flip also says how much of the board turns, which decides how loud its flaps clatter.
- `parts.py` draws the π and the NeXT cube with the code in `site/hero.py`, so the film and the page draw them the same way. It writes their sizes into `assets/parts.js`.
- `soundtrack.py` synthesizes all of the music and all of the effects, the clatter of the board's flaps among them, into `assets/music.flac` and `assets/effects.flac`.
- `assets/admin/` holds the admin's windows and its desk, as `site/shot.py` takes them.
- `site` links to `../site`, because HyperFrames serves only the project's own folder, and the film uses the page's stylesheet, type and mark.

## What belongs to somebody else

- The windows in `assets/admin/` show the admin's icons, which are the original files out of a NeXTSTEP 3.3 disk image, and are not covered by this repository's license.
- GSAP is loaded from jsDelivr when the film plays or renders, and comes under [GSAP's standard license](https://gsap.com/standard-license).

NeXT, NeXTSTEP, OPENSTEP and the NeXT cube logo are registered trademarks of Apple Computer, Inc. Raspberry Pi is a trademark of Raspberry Pi Ltd.
