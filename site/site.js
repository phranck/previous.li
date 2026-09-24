/* The one thing on this page that does anything: copying the install line.
   Everything else the page does is layout and a link. */

const copyButton = document.getElementById("copy");
const copyLabel = document.getElementById("copy-label");
const copyIcon = document.getElementById("copy-icon").querySelector("use");
const commandLine = document.getElementById("command");

const RESTING_LABEL = copyLabel.textContent;
const CONFIRMATION_MILLISECONDS = 1600;

let confirmationTimer = 0;

/**
 * Says the line has been taken, for a moment.
 *
 * The button keeps its own resting label rather than a constant written here,
 * so the two cannot disagree when the markup changes.
 *
 * @param {string} label What the button says whilst confirming.
 * @param {string} glyph The symbol id in site/icons.svg to show with it.
 */
function confirm_(label, glyph) {
  copyLabel.textContent = label;
  copyIcon.setAttribute("href", `site/icons.svg#${glyph}`);
  copyButton.classList.add("button--copied");

  clearTimeout(confirmationTimer);
  confirmationTimer = setTimeout(() => {
    copyLabel.textContent = RESTING_LABEL;
    copyIcon.setAttribute("href", "site/icons.svg#copy");
    copyButton.classList.remove("button--copied");
  }, CONFIRMATION_MILLISECONDS);
}

copyButton.addEventListener("click", async () => {
  const line = commandLine.textContent.trim();

  try {
    await navigator.clipboard.writeText(line);
    confirm_("Copied", "check");
  } catch {
    // Every browser refuses the clipboard outside a secure context, and this
    // page is also opened from a checkout over file://. Selecting the line
    // leaves the reader one keystroke away from the same result.
    const range = document.createRange();
    range.selectNodeContents(commandLine);
    getSelection().removeAllRanges();
    getSelection().addRange(range);
    confirm_("Selected", "check");
  }
});
