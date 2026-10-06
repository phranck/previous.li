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
};
