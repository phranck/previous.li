"""The promo film as the page plays it, made out of the render.

The render, promo/renders/previously.mp4, stays out of the repository and runs
at 7.7 Mbit/s. This writes the copy the page plays: H.264 and AAC, which every
browser plays, at a constant quality that keeps the scanlines and the
lettering, with the index at the front of the file so a browser starts playing
before the rest has arrived. Beside it goes the picture the page shows until
somebody presses play.

Run it after every render. It needs ffmpeg.
"""

import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
RENDER = HERE.parent / "promo" / "renders" / "previously.mp4"
FILM = HERE / "film" / "previously.mp4"
POSTER = HERE / "film" / "poster.jpg"

#: x264's constant quality. At 22 the copy of the 32 second film is about 5 MB
#: against the render's 31, measures 0.988 SSIM against it, and a crop of the
#: lettering at full size shows no difference.
QUALITY = 22
AUDIO_BITRATE = "128k"

#: Where the poster is taken: the black cube over the name, the first picture
#: the film holds still for.
POSTER_SECONDS = 2


def ffmpeg(*arguments):
    """Runs ffmpeg quietly, overwriting what it writes, and stops on an error."""
    subprocess.run(["ffmpeg", "-v", "error", "-y", *arguments], check=True)


def main():
    if not RENDER.exists():
        raise SystemExit(f"{RENDER} is not there: render the film first with npm --prefix promo run render")
    FILM.parent.mkdir(exist_ok=True)
    ffmpeg("-i", str(RENDER), "-c:v", "libx264", "-preset", "slow", "-crf", str(QUALITY),
           "-profile:v", "high", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", AUDIO_BITRATE,
           "-movflags", "+faststart", str(FILM))
    ffmpeg("-ss", str(POSTER_SECONDS), "-i", str(RENDER), "-frames:v", "1", "-q:v", "3", str(POSTER))
    for path in (FILM, POSTER):
        print(f"wrote {path.relative_to(HERE.parent)} ({path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
