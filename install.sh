#!/usr/bin/env bash
#
# The line on previous.li. A pointer, not the installer.
#
# The installer lives beside the thing it installs, in phranck/previously, next
# to the packaging and the systemd units whose paths it knows. It is fetched
# here rather than copied here, so there is one of it and nothing that can fall
# behind it.
#
# Read it at https://github.com/phranck/previously/blob/main/install.sh
#
#   curl -fsSL https://previous.li/install.sh | bash
#   curl -fsSL https://previous.li/install.sh | bash -s -- --update-admin

set -euo pipefail

readonly INSTALLER="https://raw.githubusercontent.com/phranck/previously/main/install.sh"

installer="$(mktemp)"
trap 'rm -f "${installer}"' EXIT

curl -fsSL -o "${installer}" "${INSTALLER}" || {
  printf 'Could not fetch %s\n' "${INSTALLER}" >&2
  exit 1
}

# Empty or truncated is worse than a failed download, because the next line
# runs whatever arrived.
[[ -s "${installer}" ]] || {
  printf 'Nothing came back from %s\n' "${INSTALLER}" >&2
  exit 1
}
head -n 1 "${installer}" | grep -q '^#!/usr/bin/env bash' || {
  printf 'What came back from %s is not the installer\n' "${INSTALLER}" >&2
  exit 1
}

# Run through with whatever arguments this was given, so --update-admin and
# --help reach the installer. Its stdin is closed because this script is itself
# piped into bash, which leaves the rest of it sitting there: the installer
# reads none, and this is what makes that true rather than intended.
bash "${installer}" "$@" < /dev/null
