#!/usr/bin/env python3
"""Names every file the page loads with a stamp of what is in it.

Each local address in index.html, and each one in a stylesheet, ends in `?v=`
and the first eight hex digits of the SHA-256 of the file it names. The address
changes exactly when the file does, so a browser fetches a changed file at once
and keeps one that has not changed.

    python3 site/stamp.py            writes the stamps
    python3 site/stamp.py --check    writes nothing, and fails where one is stale

The stylesheets go first. The page preloads the font a stylesheet loads, under
the same address, and a stylesheet's own stamp is taken from it as it reads
once its addresses are stamped.
"""

import hashlib
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
PAGE = ROOT / "index.html"
STYLESHEETS = (HERE / "site.css", HERE / "motion.css")

#: How many hex digits of the digest a stamp keeps.
STAMP_LENGTH = 8

#: An address in the page, as an href, a src or a video's poster names it,
#: split into what stands before it, the address, and the closing quote.
PAGE_ADDRESS = re.compile(r'((?<![\w-])(?:href|src|poster)=")([^"]*)(")')

#: An address in a stylesheet, split the same way.
STYLESHEET_ADDRESS = re.compile(r'(url\(")([^"]*)("\))')

#: An address that names something other than a file of this site: another
#: host, a scheme such as mailto or data, or a place on the page itself.
NOT_A_FILE_HERE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|//|#)", re.IGNORECASE)

#: A stamp an address carries already, which the new one replaces.
STAMP = re.compile(r"\?v=[0-9a-f]*")


def stamp_of(path):
    """@returns str - The stamp of one file: the first STAMP_LENGTH hex digits
    of the SHA-256 of its bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:STAMP_LENGTH]


def stamped(address, base):
    """One address with the stamp of the file it names.

    @param address - What the attribute or the url() says, with or without a
      stamp and a fragment.
    @param base - pathlib.Path of the folder the address is relative to.
    @returns str, the address with a current stamp before any fragment, or
      unchanged where it names no file of this site.
    @raises FileNotFoundError where it names a file that is not there, because
      that is a broken page rather than an address to leave as it is.
    """
    if not address or NOT_A_FILE_HERE.match(address):
        return address
    path, hash_sign, fragment = address.partition("#")
    path = STAMP.sub("", path)
    return f"{path}?v={stamp_of(base / path)}{hash_sign}{fragment}"


def with_stamps(text, pattern, base):
    """@returns str - The text with every address the pattern finds stamped,
    relative to base, and everything else as it was."""
    return pattern.sub(
        lambda match: match.group(1) + stamped(match.group(2), base) + match.group(3),
        text,
    )


def main():
    """Stamps the stylesheets and then the page, or with --check reports which
    of them would change and exits 1 where any would."""
    checking = "--check" in sys.argv[1:]
    stale = []

    for path, pattern in (
        *((sheet, STYLESHEET_ADDRESS) for sheet in STYLESHEETS),
        (PAGE, PAGE_ADDRESS),
    ):
        before = path.read_text()
        after = with_stamps(before, pattern, path.parent)
        if after == before:
            continue
        name = path.relative_to(ROOT)
        if checking:
            stale.append(name)
        else:
            path.write_text(after)
            print(f"{name}: stamped")

    if stale:
        names = ", ".join(str(name) for name in stale)
        print(
            f"Stale stamps in {names}. Run python3 site/stamp.py and commit what it changes."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
