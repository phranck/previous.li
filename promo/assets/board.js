/**
 * The split-flap board the film is staged on: its modules, what each one
 * shows over the film, and how a flap falls.
 *
 * A module is a static upper half, a static lower half and a flap. The flap
 * carries the top of what the module showed on its front and the bottom of
 * what it turns to on its back, and it falls from the upper half over the
 * hinge onto the lower one, while the upper half already shows the top of the
 * new content. That is how a Solari board turns, and it is what makes a word
 * arrive in pieces.
 *
 * What the halves show comes from custom properties on the module: what it
 * turns from and what it turns to, each as a letter, its color, a background
 * for a part of a picture, and how that picture is scaled. A flip sets those
 * once and turns the flap once, so the board is set by the timeline alone,
 * and every change is worked out before anything is drawn, the passing
 * letters of each flutter drawn from a seeded sequence, so every frame comes
 * out the same however the film is sought.
 *
 * Loaded in the head of index.html, before the board's scene is mounted.
 */
window.BOARD = (() => {
  /** How long one flap takes to fall, in seconds. */
  const FLIP = 0.08;

  /** The letters a module passes through on its way to what it is set to. */
  const PASSING = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

  const BLANK = { kind: "blank" };

  /** A content that keeps whatever the module shows, for a flutter that lands where it started. */
  const KEEP = { kind: "keep" };

  /**
   * A generator of numbers between zero and one that gives the same sequence
   * on every run, so every render draws the same flutter.
   *
   * @param {number} seed Any whole number.
   * @returns {function(): number} The next number of the sequence.
   */
  function sequence(seed) {
    let state = seed;
    return () => {
      state = (state * 16807) % 2147483647;
      return state / 2147483647;
    };
  }

  /**
   * Whether two contents look the same, so a module set to what it already
   * shows does not turn.
   *
   * @param {object} first One content: a glyph, a tile, or BLANK.
   * @param {object} second The other.
   * @returns {boolean} Whether both draw the same face.
   */
  function same(first, second) {
    if (first.kind !== second.kind) return false;
    if (first.kind === "glyph") return first.character === second.character && first.color === second.color;
    if (first.kind === "tile") return first.picture === second.picture;
    return true;
  }

  /**
   * A board on a scene's timeline.
   *
   * @param {{tl: object, at: function(number): number}} scene The scene's
   *   timeline and its clock, as FILM.scene returns them.
   * @param {Element} holder Where the modules are drawn.
   * @param {object[]} grids The board's grids of modules: each with its
   *   name, its top left, its columns and rows, a module's width and height,
   *   the gaps between modules, and the size of its letters.
   * @param {string} ink The color of the letters.
   * @returns {object} The board's rows by grid name, and the ways to set what
   *   its modules show: `text`, `picture`, `flutter` and `tile`, and `build`,
   *   which draws the board once everything is set.
   */
  function create({ tl, at }, holder, grids, ink) {
    const random = sequence(1993);
    const modules = [];
    const rows = {};
    for (const grid of grids) {
      rows[grid.name] = Array.from({ length: grid.rows }, (_line, row) =>
        Array.from({ length: grid.columns }, (_place, column) => {
          const module = {
            grid,
            x: grid.x + column * (grid.width + grid.gapX),
            y: grid.y + row * (grid.height + grid.gapY),
            changes: [],
          };
          modules.push(module);
          return module;
        }),
      );
    }

    /**
     * Sets one module to a content from a moment on.
     *
     * @param {object} module The module.
     * @param {object} content What it shows once it has turned.
     * @param {number} start When it starts to turn, on the film's clock.
     * @param {number} passing How many letters it passes through first.
     */
    function set(module, content, start, passing) {
      module.changes.push({ start, content, passing });
    }

    /**
     * What a module shows of a picture: the part of it that lies under the
     * module.
     *
     * @param {object} image The picture, as `picture` takes it.
     * @returns {object} A content that `text`, `picture` and `flutter` can
     *   set a module to.
     */
    function tile(image) {
      return { kind: "tile", picture: image };
    }

    /**
     * Sets a line of modules to a text, a character to a module, and blanks
     * the rest of the line. The characters land one after another, a step
     * apart from the first, or each at its own moment.
     *
     * @param {object[]} line The modules of one row.
     * @param {string} words What the line says.
     * @param {object} options When and how: `start`, the moment the first
     *   character lands, and `step` between them, in seconds, or `landAt`, a
     *   function from a character's place in the text to the moment it lands;
     *   `align` "center" or "left", `from` the first column for a left aligned
     *   text, `passing` the letters each passes through on the way, and
     *   `color` for the text, or a function giving it by a character's place.
     */
    function text(line, words, { start = 0, step = 0.03, landAt, align = "center", from = 0, passing = 2, color } = {}) {
      const characters = [...words];
      const offset = align === "center" ? Math.floor((line.length - characters.length) / 2) : from;
      line.forEach((module, column) => {
        const place = column - offset;
        const character = characters[place];
        if (character === undefined || character === " ") {
          set(module, BLANK, start + Math.max(place, 0) * step - FLIP, 0);
          return;
        }
        const tint = typeof color === "function" ? color(place) : color;
        const lands = landAt ? landAt(place) : start + place * step;
        set(module, { kind: "glyph", character, color: tint }, lands - (passing + 1) * FLIP, passing);
      });
    }

    /**
     * Sets a block of modules to a picture, each module showing the part of
     * it that lies under it. They turn in a wave that runs from one side of
     * the block to the other over the given time.
     *
     * @param {object[][]} block The modules, by row and column.
     * @param {object} image What the block shows: its `color`, its `layers`
     *   from the top down, each an `image` or a `gradient` with its `x`, `y`,
     *   `width` and `height` on the grid, and whether it is `pixelated`.
     * @param {object} options `start` and `end` of the wave, `from` the side
     *   it runs from, "left", "right", "top" or "middle", and `only`, a
     *   rectangle on the grid outside which nothing turns.
     */
    function picture(block, image, { start, end, from = "left", only } = {}) {
      const cells = block.flat();
      const left = Math.min(...cells.map((module) => module.x));
      const right = Math.max(...cells.map((module) => module.x));
      const top = Math.min(...cells.map((module) => module.y));
      const bottom = Math.max(...cells.map((module) => module.y));
      const middle = [(left + right) / 2, (top + bottom) / 2];
      const reach = { left: right - left, right: right - left, top: bottom - top, middle: Math.hypot(right - middle[0], bottom - middle[1]) };
      const distance = (module) => ({
        left: module.x - left,
        right: right - module.x,
        top: module.y - top,
        middle: Math.hypot(module.x - middle[0], module.y - middle[1]),
      })[from];
      const content = tile(image);
      for (const module of cells) {
        const { grid } = module;
        if (only) {
          const across = module.x - grid.x;
          const down = module.y - grid.y;
          if (across + grid.width < only.x || across > only.x + only.width || down + grid.height < only.y || down > only.y + only.height) continue;
        }
        const share = reach[from] ? distance(module) / reach[from] : 0;
        set(module, content, start + share * (end - start - FLIP), 0);
      }
    }

    /**
     * Sets modules to a content after passing through a few letters, each
     * starting at a random moment so that all have landed by the end. With
     * no letters to pass, a module that already shows the content stays as
     * it is, which is how a flutter clears only what is showing.
     *
     * @param {object[]} cells The modules.
     * @param {object} options `start` and `end` of the flutter, `passing` the
     *   letters each passes through, `content`: BLANK, KEEP, a tile, or a
     *   function giving a module its content, and `share`, the part of the
     *   modules that take part, drawn at random.
     */
    function flutter(cells, { start, end, passing = 3, content = BLANK, share = 1 }) {
      const latest = end - (passing + 1) * FLIP;
      for (const module of cells) {
        if (share < 1 && random() > share) continue;
        const target = typeof content === "function" ? content(module) : content;
        set(module, target, start + random() * Math.max(latest - start, 0), passing);
      }
    }

    /**
     * The custom properties a module shows a content through. Every property
     * is set for every content, so a module that turns from a picture to a
     * letter loses the picture.
     *
     * @param {object} module The module.
     * @param {object} content What it shows: a glyph, a tile, or BLANK.
     * @param {"from"|"to"} prefix "from" for what it turns from, "to" for
     *   what it turns to.
     * @returns {Object<string, string>} The properties by name, with their
     *   values.
     */
    function look(module, content, prefix) {
      const glyph = content.kind === "glyph" ? JSON.stringify(content.character) : '""';
      const color = (content.kind === "glyph" && content.color) || ink;
      let background = "transparent";
      let rendering = "auto";
      if (content.kind === "tile") {
        const { grid } = module;
        const across = module.x - grid.x;
        const down = module.y - grid.y;
        const { layers, color: fill, pixelated } = content.picture;
        const parts = layers.map((layer) => `${layer.image ? `url("${layer.image}")` : layer.gradient} ${layer.x - across}px ${layer.y - down}px / ${layer.width}px ${layer.height}px no-repeat`);
        background = [...parts.slice(0, -1), `${parts[parts.length - 1]} ${fill || "transparent"}`].join(", ");
        rendering = pixelated ? "pixelated" : "auto";
      }
      return { [`--${prefix}-glyph`]: glyph, [`--${prefix}-color`]: color, [`--${prefix}-background`]: background, [`--${prefix}-rendering`]: rendering };
    }

    /**
     * Draws every module and lays its flips on the timeline. Each module's
     * changes are taken in order: one that starts before the last has
     * finished waits for it, a change to what the module already shows is
     * dropped unless it passes through letters, and the letters passed are
     * drawn from the seeded sequence, module by module, so they never vary.
     */
    function build() {
      for (const module of modules) {
        const { grid } = module;
        const element = document.createElement("div");
        element.className = `module ${grid.name}`;
        Object.assign(element.style, { left: `${module.x}px`, top: `${module.y}px`, width: `${grid.width}px`, height: `${grid.height}px`, fontSize: `${grid.letters}px` });
        element.style.setProperty("--face", `${grid.height}px`);
        const part = (className, ...children) => {
          const piece = document.createElement("div");
          piece.className = className;
          piece.append(...children);
          return piece;
        };
        const flap = part("flap", part("side front", part("face")), part("side back", part("face")));
        element.append(part("half upper", part("face")), part("half lower", part("face")), flap);
        holder.append(element);
        const resting = { ...look(module, BLANK, "from"), ...look(module, BLANK, "to") };
        for (const [property, value] of Object.entries(resting)) element.style.setProperty(property, value);
        tl.set(flap, { rotationX: -180 }, 0);

        let shown = BLANK;
        let free = 0;
        for (const change of module.changes.sort((first, second) => first.start - second.start)) {
          const target = change.content === KEEP ? shown : change.content;
          if (same(target, shown) && !change.passing) continue;
          let moment = Math.max(change.start, free);
          const steps = [];
          for (let letter = 0; letter < change.passing; letter++) steps.push({ kind: "glyph", character: PASSING[Math.floor(random() * PASSING.length)] });
          steps.push(target);
          for (const next of steps) {
            tl.set(element, { ...look(module, shown, "from"), ...look(module, next, "to") }, at(moment));
            tl.fromTo(flap, { rotationX: 0 }, { rotationX: -180, duration: FLIP, ease: "power1.in", immediateRender: false }, at(moment));
            shown = next;
            moment += FLIP;
          }
          free = moment;
        }
      }
    }

    return { rows, text, picture, flutter, tile, build };
  }

  return { FLIP, BLANK, KEEP, create };
})();
