/**
 * What the film and its scenes share: the cue sheet, a scene's timeline on
 * the film's clock, and the helpers both of them use.
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
   * @returns {{tl: object, at: function(number): number}} The paused timeline
   *   to register once it is built, and the converter from film time to scene
   *   time.
   */
  scene(id) {
    const tl = gsap.timeline({ paused: true });
    const start = window.CUES.scenes[id];
    if (start === undefined) console.error(`Scene ${id} is not on the cue sheet.`);
    const at = (filmTime) => filmTime - start;
    return { tl, at };
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
   * The admin's windows and its desk, as site/shot.py takes them: the size of
   * each in NeXTSTEP pixels, and how many image pixels a side a window's
   * picture has to each of them.
   */
  ADMIN: {
    windowPixels: 4,
    windows: { files: [470, 480], info: [400, 259], pi: [360, 373] },
    desk: [896, 665.6],
  },

  /**
   * Tells check when a window's picture was taken at another size than ADMIN
   * states, because the film would place it by the wrong numbers.
   *
   * @param {"files"|"info"|"pi"} name The window, by the admin's name for it.
   */
  checkWindow(name) {
    const [width, height] = this.ADMIN.windows[name];
    const picture = new Image();
    picture.src = `assets/admin/${name}.png`;
    picture
      .decode()
      .then(() => {
        const taken = [picture.naturalWidth / this.ADMIN.windowPixels, picture.naturalHeight / this.ADMIN.windowPixels];
        if (taken[0] !== width || taken[1] !== height) {
          console.error(`assets/admin/${name}.png is ${taken.join(" by ")} NeXTSTEP pixels, and the film places it as ${width} by ${height}.`);
        }
      })
      .catch(() => console.error(`assets/admin/${name}.png did not load.`));
  },
};
