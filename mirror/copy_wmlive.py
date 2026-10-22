#!/usr/bin/env python3
"""Copies the part of the Window Maker Live archive that installing Previous needs.

Previously installs the emulator from wmlive.rumbero.org, and some networks
cannot reach that server. Previously falls back to this copy for them. Its
index files are byte-identical to the archive's, so the archive's own signature
covers them and apt accepts the copy as the same archive. Only the emulator's
packages are copied, because Previously pins everything else in the archive
away.

Run from the repository root; the copy goes to apt/wmlive unless a target is
given as the only argument.
"""

import hashlib
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.request

ARCHIVE_URL = "https://wmlive.rumbero.org/repo"
SUITE = "wmlive-trixie"
ARCHITECTURE = "arm64"
PACKAGE = "previous"

#: The key that signs the archive, as `gpg --verify` names it for its
#: InRelease. A signature by any other key is refused.
SIGNING_FINGERPRINT = "C40423E642122B755120F8CC963E4C2E2B830BAD"
KEY_FILE = pathlib.Path(__file__).with_name("wmlive.rumbero.org.asc")

#: The signed files of the suite. InRelease is the index with its signature
#: inline, Release with Release.gpg the same index with a detached one; apt
#: uses either, so the copy carries both.
SIGNED_FILES = ("InRelease", "Release", "Release.gpg")

DEFAULT_TARGET = pathlib.Path("apt/wmlive")
FETCH_ATTEMPTS = 3
FETCH_TIMEOUT_SECONDS = 60
RETRY_PAUSE_SECONDS = 10


def fetched(url):
    """Downloads one file of the archive.

    @param url - The file's address.
    @returns bytes, the file's content.

    A request that fails is tried again a few times before the run gives up,
    so that one dropped connection does not leave the copy a run behind.
    """
    for attempt in range(1, FETCH_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=FETCH_TIMEOUT_SECONDS) as response:
                return response.read()
        except OSError as error:
            if attempt == FETCH_ATTEMPTS:
                raise SystemExit(f"Cannot fetch {url}: {error}")
            time.sleep(RETRY_PAUSE_SECONDS)


def digest_of(content):
    """The SHA-256 of content as lowercase hex, the form the archive's index uses."""
    return hashlib.sha256(content).hexdigest()


def checked(content, size, digest, name):
    """Returns content once its size and SHA-256 match what the index says.

    @param content - The downloaded bytes.
    @param size - The size in bytes the index gives.
    @param digest - The SHA-256 the index gives.
    @param name - The file's path in the archive, for the error message.
    @returns bytes, content unchanged.
    """
    if len(content) != size or digest_of(content) != digest:
        raise SystemExit(f"{name} does not match the archive's index")
    return content


def signed_by_archive(keyring, *files):
    """Whether gpgv finds a valid signature by the archive's key.

    @param keyring - A keyring holding only the archive's key.
    @param files - The signed file alone, or a detached signature and its file.
    @returns bool.

    gpgv's exit status says only that some key in the keyring signed. The
    status line names the key, which is what pins the signature to
    SIGNING_FINGERPRINT.
    """
    # A bad signature is an answer here, not an error, so the exit status is read below.
    result = subprocess.run(
        ["gpgv", "--status-fd", "1", "--keyring", str(keyring), *(str(path) for path in files)],
        capture_output=True, text=True, check=False)
    valid = f"[GNUPG:] VALIDSIG {SIGNING_FINGERPRINT} "
    return result.returncode == 0 and any(line.startswith(valid) for line in result.stdout.splitlines())


def listed_files(release_text):
    """The index files a Release lists under SHA256.

    @param release_text - The Release file as text.
    @returns list of (path, size, digest), with path relative to the suite.
    """
    entries = []
    in_section = False
    for line in release_text.splitlines():
        if not line.startswith(" "):
            in_section = line.rstrip() == "SHA256:"
            continue
        if in_section:
            digest, size, path = line.split()
            entries.append((path, int(size), digest))
    return entries


def package_stanzas(packages_text, name):
    """The stanzas of a Packages index that describe one package.

    @param packages_text - The Packages index as text.
    @param name - The package's name.
    @returns list of dict, one per version, from field name to value.
    """
    stanzas = []
    for block in packages_text.split("\n\n"):
        fields = {}
        for line in block.splitlines():
            if line[:1] in (" ", "\t") or ":" not in line:
                continue
            field, value = line.split(":", 1)
            fields[field] = value.strip()
        if fields.get("Package") == name:
            stanzas.append(fields)
    return stanzas


def written(path, content):
    """Writes content to path through a temporary file, so a reader never sees half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".part")
    temporary.write_bytes(content)
    temporary.replace(path)


def pruned(directory, kept):
    """Removes every file under directory that is not in kept, and returns the removed paths."""
    removed = []
    if directory.exists():
        for path in sorted(directory.rglob("*")):
            if path.is_file() and path not in kept:
                path.unlink()
                removed.append(path)
    return removed


def fetched_suite(keyring):
    """Downloads and verifies the suite's signed files and every index file they list.

    @param keyring - A keyring holding only the archive's key.
    @returns dict from path relative to the suite to its bytes.
    """
    suite_url = f"{ARCHIVE_URL}/dists/{SUITE}"
    files = {name: fetched(f"{suite_url}/{name}") for name in SIGNED_FILES}
    with tempfile.TemporaryDirectory() as scratch:
        directory = pathlib.Path(scratch)
        for name, content in files.items():
            (directory / name).write_bytes(content)
        inline = signed_by_archive(keyring, directory / "InRelease")
        detached = signed_by_archive(keyring, directory / "Release.gpg", directory / "Release")
    if not (inline and detached):
        raise SystemExit(f"The archive's index is not signed by {SIGNING_FINGERPRINT}")
    for path, size, digest in listed_files(files["Release"].decode("utf-8")):
        files[path] = checked(fetched(f"{suite_url}/{path}"), size, digest, path)
    return files


def fetched_packages(packages_text, target):
    """Downloads every version of the emulator the index names that the copy does not hold yet.

    @param packages_text - The suite's Packages index for ARCHITECTURE.
    @param target - The copy's root, where existing packages are looked for.
    @returns (dict, set): the new packages by their path in the archive, and
      the paths of every package the index names.
    """
    stanzas = package_stanzas(packages_text, PACKAGE)
    if not stanzas:
        raise SystemExit(f"The archive's index names no {PACKAGE}")
    new = {}
    named = set()
    for stanza in stanzas:
        filename, digest, size = stanza["Filename"], stanza["SHA256"], int(stanza["Size"])
        named.add(filename)
        existing = target / filename
        if existing.exists() and digest_of(existing.read_bytes()) == digest:
            continue
        new[filename] = checked(fetched(f"{ARCHIVE_URL}/{filename}"), size, digest, filename)
    return new, named


def main(argv):
    """Brings the copy up to date with the archive.

    @param argv - The command line; an optional single argument names the
      copy's root.
    @returns int, the exit status.

    Everything is downloaded and verified before the first file is written,
    so a run that fails leaves the copy as it was.
    """
    target = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT_TARGET
    with tempfile.TemporaryDirectory() as scratch:
        keyring = pathlib.Path(scratch) / "archive.gpg"
        subprocess.run(["gpg", "--batch", "--dearmor", "--output", str(keyring), str(KEY_FILE)], check=True)
        suite = fetched_suite(keyring)

    packages_path = f"main/binary-{ARCHITECTURE}/Packages"
    if packages_path not in suite:
        raise SystemExit(f"The archive's index lists no {packages_path}")
    packages, named = fetched_packages(suite[packages_path].decode("utf-8"), target)

    # Packages first and the signed files last, so that a reader of a half
    # written copy never finds an index that names a missing package.
    for filename, content in packages.items():
        written(target / filename, content)
    suite_directory = target / "dists" / SUITE
    for path in sorted(suite, key=lambda name: name in SIGNED_FILES):
        written(suite_directory / path, suite[path])

    removed = pruned(target / "pool", {target / filename for filename in named})
    removed += pruned(suite_directory, {suite_directory / path for path in suite})
    print(f"{SUITE} {PACKAGE}: {len(packages)} packages new, {len(removed)} files removed")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
