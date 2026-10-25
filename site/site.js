/* The three things on this page that do anything: copying a command, the
   film's player, and saying which release the download fetches. Everything
   else the page does is layout and a link. */

/** How long a button shows the check mark after the command has been taken. */
const CONFIRMATION_MILLISECONDS = 1600;

/**
 * Puts a command on the clipboard, or selects it where the clipboard is refused.
 *
 * Every browser refuses the clipboard outside a secure context, and this page
 * is also opened from a checkout over file://. Selecting the command leaves the
 * reader one keystroke away from the same result.
 *
 * @param {Element} element The element whose text is the command.
 * @returns {Promise<"copied" | "selected">} Which of the two happened.
 */
async function take(element) {
  const command = element.textContent.trim();
  try {
    await navigator.clipboard.writeText(command);
    return "copied";
  } catch {
    const range = document.createRange();
    range.selectNodeContents(element);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    return "selected";
  }
}

/* A code box carries its button inside itself, at the right, with no label:
   the glyph alone says that the command has been taken. data-copy names the
   element that holds the command, which leaves a prompt beside it out. */
for (const button of document.querySelectorAll("[data-copy]")) {
  const code = document.getElementById(button.dataset.copy);
  const glyph = button.querySelector("use");
  let timer = 0;

  button.addEventListener("click", async () => {
    await take(code);
    glyph.setAttribute("href", "site/icons.svg#check");
    button.classList.add("codebox__copy--copied");

    clearTimeout(timer);
    timer = setTimeout(() => {
      glyph.setAttribute("href", "site/icons.svg#copy");
      button.classList.remove("codebox__copy--copied");
    }, CONFIRMATION_MILLISECONDS);
  });
}

/* --- the film's player ----------------------------------------------------

   The film carries the page's own controls, because the browser's cannot be
   kept off the poster everywhere: Safari shows its own whatever a stylesheet
   says. They are swapped in here, so without the script the browser's stay. */

const player = document.getElementById("player");
const film = player.querySelector(".film__video");
const playerBar = player.querySelector(".player__bar");
const playButton = document.getElementById("player-play");
const timeline = document.getElementById("player-timeline");
const timeText = document.getElementById("player-time");
const soundButton = document.getElementById("player-sound");
const screenButton = document.getElementById("player-screen");

/** How long the pointer may rest on a playing film before the controls leave it. */
const IDLE_MILLISECONDS = 2500;

/** What Umami counts the film's first start in a page view as. */
const PLAY_EVENT = "Play film";

let idleTimer = 0;

/**
 * A number of seconds as the player shows it.
 *
 * @param {number} seconds Any number; one that is not finite reads as none.
 * @returns {string} Minutes and two digits of seconds, such as "0:32".
 */
function clockOf(seconds) {
  const whole = Number.isFinite(seconds) ? Math.floor(seconds) : 0;
  return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, "0")}`;
}

/**
 * Shows another glyph on a button and says what the button now does.
 *
 * @param {HTMLButtonElement} button The button to change.
 * @param {string} glyph The symbol id in site/icons.svg.
 * @param {string} label What pressing it does, for whoever cannot see the glyph.
 */
function setButton(button, glyph, label) {
  button.querySelector("use").setAttribute("href", `site/icons.svg#${glyph}`);
  button.setAttribute("aria-label", label);
}

/** The play button offers what the film is not doing. */
function showPlaying() {
  setButton(playButton, film.paused ? "play" : "pause", film.paused ? "Play" : "Pause");
}

/** The timeline and the clock follow the film, and learn its length from it. */
function showPosition() {
  const now = clockOf(film.currentTime);
  const length = clockOf(film.duration);
  timeline.max = Number.isFinite(film.duration) ? film.duration : 0;
  timeline.value = film.currentTime;
  timeline.setAttribute("aria-valuetext", `${now} of ${length}`);
  timeText.textContent = `${now} / ${length}`;
}

/** The sound button offers the opposite of what is on. */
function showSound() {
  setButton(soundButton, film.muted ? "speaker-slash" : "speaker-high",
            film.muted ? "Sound on" : "Sound off");
}

/** @returns {Element | null} What has the whole screen, in either engine's word for it. */
function wholeScreenElement() {
  return document.fullscreenElement ?? document.webkitFullscreenElement ?? null;
}

/** The screen button offers the way back once the player has the whole screen. */
function showScreen() {
  const whole = wholeScreenElement() === player;
  setButton(screenButton, whole ? "corners-in" : "corners-out",
            whole ? "Leave full screen" : "Full screen");
}

/** Starts a paused film and stops a playing one. */
function togglePlaying() {
  if (film.paused) {
    film.play();
  } else {
    film.pause();
  }
}

/**
 * Gives the player the whole screen, or takes it back.
 *
 * The player rather than the film, so the page's controls come along. An
 * iPhone gives the whole screen to a video alone, and with its own controls.
 */
function toggleScreen() {
  if (wholeScreenElement()) {
    (document.exitFullscreen ?? document.webkitExitFullscreen).call(document);
    return;
  }
  const request = player.requestFullscreen ?? player.webkitRequestFullscreen;
  if (request) {
    request.call(player);
  } else {
    film.webkitEnterFullscreen();
  }
}

/** Keeps the controls on a playing film whilst the pointer moves, and takes them off once it rests. */
function wake() {
  player.classList.remove("player--idle");
  clearTimeout(idleTimer);
  if (!film.paused) {
    idleTimer = setTimeout(() => player.classList.add("player--idle"), IDLE_MILLISECONDS);
  }
}

film.controls = false;
playerBar.hidden = false;

playButton.addEventListener("click", togglePlaying);
film.addEventListener("click", togglePlaying);
soundButton.addEventListener("click", () => {
  film.muted = !film.muted;
});
screenButton.addEventListener("click", toggleScreen);
timeline.addEventListener("input", () => {
  film.currentTime = Number(timeline.value);
});

for (const change of ["play", "pause"]) {
  film.addEventListener(change, () => {
    showPlaying();
    wake();
  });
}
for (const change of ["loadedmetadata", "durationchange", "timeupdate", "emptied"]) {
  film.addEventListener(change, showPosition);
}
film.addEventListener("volumechange", showSound);

/* Umami counts how many visitors start the film, so only the first start of a
   page view is sent: a pause and a second start are the same visitor. The
   Copy buttons and the download are counted by their data-umami-event
   attribute, which Umami's script reads on every click. Its script loads deferred and a blocker may
   keep it away, so a missing umami sends nothing. */
film.addEventListener("play", () => window.umami?.track(PLAY_EVENT), { once: true });
document.addEventListener("fullscreenchange", showScreen);
document.addEventListener("webkitfullscreenchange", showScreen);
player.addEventListener("pointermove", wake);

/* At its end the film would stand on its last frame, the television switched
   off. Loading it again shows the poster, paused at the start, which is how a
   reload finds it. */
film.addEventListener("ended", () => film.load());

showPlaying();
showPosition();
showSound();
showScreen();

/* --- the newest release ---------------------------------------------------

   The download points at the newest release by an address that never changes,
   so it works without any of this. What the script adds beside it is which
   release that is, how large its image is and when it came out, read from the
   endpoint the admin asks about releases as well. */

/** The newest release of Previously, as GitHub's API describes it. */
const RELEASE_API = "https://api.github.com/repos/phranck/previously/releases/latest";

/** What a release calls the image Raspberry Pi Imager writes. */
const IMAGE_ASSET = "previously-raspberry-pi.img.xz";

/** Bytes in the megabyte a download is measured in, as browsers count it. */
const BYTES_PER_MEGABYTE = 1000 * 1000;

/**
 * Says which release the download fetches, beside the button that fetches it.
 *
 * Left hidden where GitHub does not answer, answers with something else, or
 * the release carries no image, because the download works either way.
 *
 * @returns {Promise<void>}
 */
async function showRelease() {
  const line = document.getElementById("release");
  try {
    const answer = await fetch(RELEASE_API, { headers: { Accept: "application/vnd.github+json" } });
    if (!answer.ok) {
      return;
    }
    const release = await answer.json();
    const image = release.assets.find((asset) => asset.name === IMAGE_ASSET);
    if (!image) {
      return;
    }
    const megabytes = Math.round(image.size / BYTES_PER_MEGABYTE);
    const published = new Date(release.published_at).toLocaleDateString("en-GB", {
      day: "numeric", month: "short", year: "numeric",
    });
    line.textContent = `Previously ${release.tag_name.replace(/^v/, "")} · ${megabytes} MB · ${published}`;
    line.hidden = false;
  } catch {
    // No network or no GitHub: the line stays away and the link stays.
  }
}

showRelease();
