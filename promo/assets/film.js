/**
 * What every scene of the film shares: the cue sheet, a scene's timeline on
 * the film's clock, and the helpers more than one scene uses.
 *
 * Loaded in the head of index.html, after the cue sheet and before any scene
 * is mounted, so each scene's script finds it ready.
 */
window.CUES = JSON.parse(document.getElementById("cues").textContent);

window.FILM = {
  /**
   * A scene's timeline, and a way to place things on it by the film's clock.
   *
   * HyperFrames seeks each scene from the moment its slot starts, so the
   * scene's own timeline counts from zero there. The cue sheet counts from
   * the start of the film, which `at` converts.
   *
   * @param {string} id The scene, as it is named on the cue sheet and as its
   *   composition id.
   * @returns {{tl: object, at: function(number): number, rise: function}} The
   *   paused timeline to register once it is built, the converter from film
   *   time to scene time, and `rise` bound to both.
   */
  scene(id) {
    const tl = gsap.timeline({ paused: true });
    const start = window.CUES.scenes[id];
    if (start === undefined) console.error(`Scene ${id} is not on the cue sheet.`);
    const at = (filmTime) => filmTime - start;

    /**
     * Brings words or lines in from below and out of a blur, one after the
     * other when there are several.
     *
     * @param {string|Element|NodeList} targets What rises.
     * @param {number} filmTime When it starts, on the film's clock.
     * @param {number} [distance=50] How far below its place it starts, in
     *   pixels.
     */
    const rise = (targets, filmTime, distance = 50) => {
      tl.fromTo(
        targets,
        { y: distance, opacity: 0, filter: "blur(12px)" },
        { y: 0, opacity: 1, filter: "blur(0px)", duration: 0.4, ease: "expo.out", stagger: 0.04 },
        at(filmTime),
      );
    };

    return { tl, at, rise };
  },

  /**
   * Tells check about every slot in a container that starts or ends anywhere
   * else than the cue sheet says: the soundtrack is laid out from the cue
   * sheet, so a scene that starts elsewhere plays against the wrong sound, and
   * every scene of this film runs to its end.
   *
   * @param {Element} container Where the slots are mounted.
   */
  checkSlots(container) {
    container.querySelectorAll("[data-composition-src]").forEach((slot) => {
      const id = slot.dataset.compositionId;
      const start = window.CUES.scenes[id];
      const end = Number(slot.dataset.start) + Number(slot.dataset.duration);
      if (Number(slot.dataset.start) !== start) console.error(`Scene ${id} starts at ${slot.dataset.start} in the markup and at ${start} on the cue sheet.`);
      if (end !== window.CUES.length) console.error(`Scene ${id} ends at ${end} s, and the cue sheet says the film lasts ${window.CUES.length} s.`);
    });
  },

  /**
   * One of the page's design tokens from site/site.css, read once while a
   * scene is built, so a tween is handed the color itself rather than the
   * name of a custom property.
   *
   * @param {string} name The custom property, such as "--ink-soft".
   * @returns {string} Its value.
   */
  token(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  },

  /**
   * Splits a word into one span per letter, so the letters can rise in turn.
   *
   * @param {Element} element Holds nothing but the word.
   * @returns {Element[]} The letters, in reading order.
   */
  splitLetters(element) {
    const letters = [...element.textContent].map((letter) => {
      const span = document.createElement("span");
      span.className = "letter";
      span.textContent = letter;
      return span;
    });
    element.replaceChildren(...letters);
    return letters;
  },

  /**
   * Where the mark stands while it holds still, as the box its picture fills:
   * large under the merge, and small over the end card's name. The cube
   * stops in this box as the mark, and the mark's own picture takes over in
   * it, so both scenes read it from here.
   *
   * @param {"merge"|"end"} moment Which of the two.
   * @returns {{left: number, top: number, width: number, height: number}} The
   *   box in film pixels, centered across the picture.
   */
  markBox(moment) {
    const MARK_BOXES = { merge: { height: 420, top: 170 }, end: { height: 230, top: 252 } };
    const { height, top } = MARK_BOXES[moment];
    const width = (height * window.PARTS.mark.width) / window.PARTS.mark.height;
    return { left: 720 - width / 2, top, width, height };
  },

  /**
   * The shadow the cube casts on the workspace, in shares of the cube's edge,
   * so it grows and shrinks with the cube: how far below the cube it falls,
   * how soft it is as the standard deviation of its blur, and how dark it is.
   * The cube casts it from a black copy of itself, and the mark's picture
   * casts the same one wherever it stands in for the cube.
   */
  SHADOW: { drop: 0.1, blur: 0.05, opacity: 0.55 },

  /**
   * The shadow the mark's picture casts in one of its boxes, the same one the
   * cube casts as the mark in that box. In Chromium a drop shadow's length
   * is the standard deviation of its blur, as blur() takes it.
   *
   * @param {{height: number}} box The box the picture fills, as `markBox`
   *   gives it.
   * @returns {string} The CSS filter that casts it.
   */
  markShadow(box) {
    const edge = (2 * window.PARTS.markPose.halfEdge * box.height) / window.PARTS.mark.height;
    const { drop, blur, opacity } = this.SHADOW;
    return `drop-shadow(0 ${drop * edge}px ${blur * edge}px rgb(0 0 0 / ${opacity}))`;
  },

  /**
   * The admin's windows and its desk, as site/shot.py takes them: each
   * window's size in NeXTSTEP pixels, and how many image pixels a side each
   * NeXTSTEP pixel is drawn with, in a window's picture and in the desk's.
   */
  ADMIN: {
    windowPixels: 4,
    deskPixels: 2.5,
    windows: { files: [470, 480], info: [400, 259], pi: [360, 373] },
  },

  /**
   * Places one of the admin's windows by its size in NeXTSTEP pixels. A
   * picture retaken at another size would be placed by the wrong numbers, so
   * an img is decoded and check is told when its size differs.
   *
   * @param {Element} element The window's img, or a div showing its picture.
   * @param {"files"|"info"|"pi"} name The window, by the admin's name for it.
   * @param {number[]} corner Its top left in film pixels, inside its holder.
   * @param {number} scale Film pixels to a NeXTSTEP pixel.
   * @returns {{x: number, y: number, width: number, height: number}} What it
   *   covers, in film pixels.
   */
  placeWindow(element, name, corner, scale) {
    const [x, y] = corner;
    const [width, height] = this.ADMIN.windows[name];
    const box = { x, y, width: width * scale, height: height * scale };
    Object.assign(element.style, { left: `${box.x}px`, top: `${box.y}px`, width: `${box.width}px`, height: `${box.height}px` });
    if (element instanceof HTMLImageElement) {
      element
        .decode()
        .then(() => {
          const taken = [element.naturalWidth / this.ADMIN.windowPixels, element.naturalHeight / this.ADMIN.windowPixels];
          if (taken[0] !== width || taken[1] !== height) {
            console.error(`assets/admin/${name}.png is ${taken.join(" by ")} NeXTSTEP pixels, and the film places it as ${width} by ${height}.`);
          }
        })
        .catch(() => console.error(`assets/admin/${name}.png did not load.`));
    }
    return box;
  },

  /**
   * Opens a window as NeXTSTEP opens one, and as the admin does: eight
   * outlines growing from where it was asked for to where it will be, each
   * drawn for a moment, and then the window itself.
   *
   * @param {{tl: object, at: function(number): number}} scene The scene's
   *   timeline and its clock, as `scene` returns them.
   * @param {Element} holder Where the outlines are drawn: the window's own
   *   container.
   * @param {Element|string} target The window, or a selector for it, which
   *   appears after the outlines.
   * @param {{x: number, y: number, width: number, height: number}} from Where
   *   it was asked for.
   * @param {{x: number, y: number, width: number, height: number}} to Where it
   *   will be.
   * @param {number} filmTime When the first outline is drawn.
   */
  openWindow({ tl, at }, holder, target, from, to, filmTime) {
    const OUTLINES = 8;
    const OUTLINE_STEP = 0.03;
    const OUTLINE_LIFE = 0.06;
    for (let index = 1; index <= OUTLINES; index++) {
      const share = index / OUTLINES;
      const between = (key) => from[key] + (to[key] - from[key]) * share;
      const outline = document.createElement("div");
      outline.className = "outline";
      holder.append(outline);
      const shown = filmTime + (index - 1) * OUTLINE_STEP;
      tl.set(outline, { opacity: 1, left: between("x"), top: between("y"), width: between("width"), height: between("height") }, at(shown));
      tl.set(outline, { opacity: 0 }, at(shown + OUTLINE_LIFE));
    }
    tl.set(target, { opacity: 1 }, at(filmTime + OUTLINES * OUTLINE_STEP));
  },

  /**
   * A small rectangle in the middle of where a window will be, which is
   * where a window opened from nothing in particular starts.
   *
   * @param {{x: number, y: number, width: number, height: number}} box The
   *   window's rectangle.
   * @returns {{x: number, y: number, width: number, height: number}} A tenth
   *   of it, in its middle.
   */
  middleOf(box) {
    return { x: box.x + box.width * 0.45, y: box.y + box.height * 0.45, width: box.width * 0.1, height: box.height * 0.1 };
  },
};
