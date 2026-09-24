#!/usr/bin/env bash
#
# Turns a freshly imaged Raspberry Pi OS Lite (64 bit, Trixie) into a machine
# that boots straight into NeXTSTEP under the Previous emulator.
#
#   curl -fsSL https://previous.li/install.sh | bash
#
# And afterwards, to put the newest admin tool on a machine that already has
# one, which is the one part of this that changes often enough to be worth
# replacing by itself:
#
#   curl -fsSL https://previous.li/install.sh | bash -s -- --update-admin
#
# Written to run straight off the network, so it carries everything it needs
# and reads no file beside itself. Two details make that safe.
#
# All the work sits in functions and nothing runs until `main` is called on
# the last line, so a download cut short executes nothing at all.
#
# And nothing in here reads from stdin, which is where the script itself
# arrives when it is piped in. A program that did would swallow the rest of
# the script. That is why apt runs with DEBIAN_FRONTEND set: a package asking
# a configuration question would otherwise reach for stdin. sudo is not a
# concern, because it reads the password from the terminal device rather than
# from stdin unless told otherwise with -S.
#
# Interrupting it is safe. Every step records how to undo exactly what it
# changed, and Ctrl+C or a failure walks that record backwards. Untouched is
# the one thing that cannot sensibly be reversed and does no harm: the package
# lists that `apt-get update` refreshed.
#
# Safe to run more than once: every step checks whether it has already been
# done and skips itself rather than duplicating its effect. A step that skips
# records nothing, so a later interrupt never removes what it found in place.

set -euo pipefail

# Where this script is, so it can find the files that ship beside it. Resolved
# rather than taken from $0, because the script is meant to be runnable from
# anywhere and through a symlink.
#
# Run through a pipe there is no file to resolve, which is how the line on the
# Previously page runs it: BASH_SOURCE is unset, and under `set -u` reading it
# ends the script before its first line of work. The fallback is the current
# directory, where nothing will be found, and everything that looks beside the
# script is written to take that as an answer.
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]:-.}")" 2>/dev/null && pwd -P || pwd -P)"
readonly SCRIPT_DIR

export DEBIAN_FRONTEND=noninteractive

readonly REPO_HOST="wmlive.rumbero.org"
readonly REPO_URL="https://${REPO_HOST}/repo"
readonly REPO_SUITE="wmlive-trixie"
readonly REPO_KEY="/etc/apt/keyrings/wmlive.asc"
readonly REPO_SOURCE="/etc/apt/sources.list.d/wmlive.sources"
readonly REPO_PREFS="/etc/apt/preferences.d/wmlive"

readonly DISK_ARCHIVE="Nextstep 3.3 HD Image With Previous.7z"
readonly DISK_ARCHIVE_URL="https://archive.org/download/nextstep-3.3-hd-image-with-previous.-7z/Nextstep%203.3%20HD%20Image%20With%20Previous.7z"

# The admin tool, for a run that has no checkout beside it. The name carries no
# version, so this address is the latest release whatever that is, and the
# version is in the package where dpkg can report it.
readonly PACKAGE_FILE="previously_all.deb"
readonly PACKAGE_URL="https://github.com/phranck/previously/releases/latest/download/${PACKAGE_FILE}"

readonly NEXTSTEP_DIR="${HOME}/nextstep"
readonly CONFIG_DIR="${HOME}/.config/previous"
readonly CONFIG_FILE="${CONFIG_DIR}/previous.cfg"

# Where the emulator runs, and therefore where it writes what it is asked to
# write. Previous puts a screen grab in its working directory under a name of
# its own choosing, and the admin tool reads that picture and takes the file
# away again, which it can only do somewhere it is allowed to write. Started in
# the home directory instead, the grabs pile up there and nothing removes them.
readonly WORK_DIR="${HOME}/.cache/previously"

# The real part of the Previously tree, which the admin tool shows as
# /Documents. A screenshot is kept in Documents/Pictures under it. In the
# emulator owner's home because that is the user the admin runs as, and it is
# the only part of the tree that is on the card at all.
readonly DOCUMENTS_DIR="${HOME}/Previously"
readonly PICTURES_DIR="${DOCUMENTS_DIR}/Documents/Pictures"
# ~/.profile and not ~/.bash_profile. Bash reads only the first of the login
# files that exists, and on Raspberry Pi OS that is ~/.profile, which pulls in
# ~/.bashrc. Creating ~/.bash_profile would switch both off, including for SSH
# sessions, which are the way back into a machine whose screen is taken.
readonly PROFILE="${HOME}/.profile"

# The admin tool holds the emulator down by creating this file, and the
# console's autostart below waits on it. On a tmpfs, so a board that has just
# started runs its emulator whoever switched it off before the last shutdown.
readonly HOLD_FILE="/run/previously/hold"

# What login looks for before printing the message of the day.
readonly HUSHLOGIN="${HOME}/.hushlogin"
readonly CMDLINE="/boot/firmware/cmdline.txt"
readonly CONFIG_TXT="/boot/firmware/config.txt"
readonly AUTOLOGIN="/etc/systemd/system/getty@tty1.service.d/autologin.conf"
readonly WIREPLUMBER_CONF="/etc/wireplumber/wireplumber.conf.d/50-nextstep.conf"
# What a speaker is set to the first time it is seen. WirePlumber ships 0.064,
# which is 40 per cent on a linear scale, and NeXTSTEP's own sounds peak at
# about a third of full scale on top of that: together, inaudible. This is 85
# per cent linear, cubed, because that is the scale the setting takes.
readonly AUDIO_VOLUME="0.614"

readonly AUTOSTART_MARKER="# >>> nextstep-rpi >>>"
readonly AUTOSTART_END="# <<< nextstep-rpi <<<"

# The smallest file in the archive that can still be a NeXTSTEP system. Anything
# below this is a ROM file or the bundled Windows binary rather than the disk.
readonly MIN_DISK_IMAGE_MB=512

info()  { printf '\033[1m==>\033[0m %s\n' "$1"; }
skip()  { printf '    %s\n' "$1"; }
abort() { printf '\033[1;31m==>\033[0m %s\n' "$1" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Undo record
#
# Two parallel arrays rather than one of "description|command", because a
# command holding the separator would be cut in half. Commands are assembled
# with printf %q so that a path with spaces, and the disk archive has several,
# survives being stored as text and evaluated later.
# ---------------------------------------------------------------------------

declare -a UNDO_WHAT=()
declare -a UNDO_HOW=()
COMPLETED=false

undo() {
  UNDO_WHAT+=("$1")
  UNDO_HOW+=("$2")
}

rollback() {
  if [[ ${#UNDO_HOW[@]} -eq 0 ]]; then
    info "Nothing had been changed yet"
    return
  fi

  info "Undoing what this run changed"
  # Backwards, so each step is reversed in a world that still looks the way it
  # did when that step ran.
  local index
  for (( index = ${#UNDO_HOW[@]} - 1; index >= 0; index-- )); do
    printf '    %s\n' "${UNDO_WHAT[index]}"
    eval "${UNDO_HOW[index]}" > /dev/null 2>&1 || \
      printf '\033[1;31m    failed, do this by hand:\033[0m %s\n' "${UNDO_HOW[index]}" >&2
  done
}

on_exit() {
  local code=$?
  [[ "$COMPLETED" == true ]] && return 0

  printf '\n'
  if [[ $code -eq 130 ]]; then
    info "Interrupted"
  else
    info "Stopped after an error"
  fi
  rollback
  exit "$code"
}

on_interrupt() {
  # Leave through the exit handler with the conventional code for SIGINT
  # rather than doing the work twice.
  exit 130
}

# Called from an undo entry. A function rather than an inline `sed -i`, because
# in-place editing is spelled differently on different systems and an undo step
# that fails silently is worse than no undo step at all.
remove_autostart_block() {
  local file="$1" scratch
  [[ -f "$file" ]] || return 0
  scratch="$(mktemp)"
  sed "/${AUTOSTART_MARKER}/,/${AUTOSTART_END}/d" "$file" > "$scratch"
  mv -f "$scratch" "$file"
}

trap on_exit EXIT
trap on_interrupt INT TERM

# ---------------------------------------------------------------------------
# 1  Refuse to run anywhere the Previous package would not fit.
# ---------------------------------------------------------------------------

check_host() {
  info "Checking host"

  [[ $EUID -ne 0 ]] || abort "Run this as your normal user, not as root. It uses sudo where it needs to."

  local architecture
  architecture="$(dpkg --print-architecture)"
  [[ "$architecture" == "arm64" ]] || abort "This needs arm64, found ${architecture}. Use the 64 bit image of Raspberry Pi OS."

  local codename
  codename="$(. /etc/os-release && echo "${VERSION_CODENAME:-}")"
  [[ "$codename" == "trixie" ]] || abort "This needs Raspberry Pi OS based on Debian trixie, found '${codename:-unknown}'. Older releases carry no SDL3."

  skip "arm64, ${codename}"
}

# ---------------------------------------------------------------------------
# 2  Kiosk compositor, the unpacker for the disk archive, and the two tools the
#    admin uses to reach the emulator: xdotool presses its keys and
#    ImageMagick reads its screen, which is the only way to tell a machine that
#    booted from one that did not.
# ---------------------------------------------------------------------------

install_packages() {
  info "Installing cage, 7zip, xdotool and imagemagick"

  local wanted=(cage 7zip xdotool imagemagick) missing=() package
  for package in "${wanted[@]}"; do
    dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "ok installed" || missing+=("$package")
  done

  if [[ ${#missing[@]} -eq 0 ]]; then
    skip "already installed"
    return
  fi

  sudo apt-get update -qq
  sudo apt-get install -y -qq "${missing[@]}"
  undo "remove ${missing[*]}" "sudo apt-get remove -y -qq ${missing[*]}"
}

# ---------------------------------------------------------------------------
# 3  The Window Maker Live archive, pinned so that only Previous comes from it.
# ---------------------------------------------------------------------------

add_repository() {
  info "Adding the ${REPO_HOST} archive"

  if [[ ! -f "$REPO_KEY" ]]; then
    sudo install -m 0755 -d /etc/apt/keyrings
    sudo wget -qO "$REPO_KEY" "${REPO_URL}/${REPO_HOST}.asc"
    undo "remove the archive key" "sudo rm -f $(printf '%q' "$REPO_KEY")"
  fi

  if [[ ! -f "$REPO_SOURCE" ]]; then
    sudo tee "$REPO_SOURCE" > /dev/null <<EOF
Types: deb
URIs: ${REPO_URL}
Suites: ${REPO_SUITE}
Components: main
Signed-By: ${REPO_KEY}
EOF
    undo "remove the archive source" "sudo rm -f $(printf '%q' "$REPO_SOURCE")"
  fi

  if [[ ! -f "$REPO_PREFS" ]]; then
    # The archive carries more than Previous, and without this it could replace
    # packages that belong to Debian. -1 blocks everything, previous is let back
    # in at the ordinary priority.
    sudo tee "$REPO_PREFS" > /dev/null <<EOF
Package: *
Pin: origin ${REPO_HOST}
Pin-Priority: -1

Package: previous
Pin: origin ${REPO_HOST}
Pin-Priority: 500
EOF
    undo "remove the archive pin" "sudo rm -f $(printf '%q' "$REPO_PREFS")"
  fi
}

# ---------------------------------------------------------------------------
# 4  Previous itself.
# ---------------------------------------------------------------------------

install_previous() {
  info "Installing Previous"

  if dpkg-query -W -f='${Status}' previous 2>/dev/null | grep -q "ok installed"; then
    skip "already installed"
    return
  fi

  sudo apt-get update -qq
  sudo apt-get install -y previous
  undo "remove previous" "sudo apt-get remove -y -qq previous"
}

# ---------------------------------------------------------------------------
# 5  The disk image. Skipped entirely when one is already present, which is
#    what lets somebody install from the original media instead.
# ---------------------------------------------------------------------------

find_disk_image() {
  find "$NEXTSTEP_DIR" -maxdepth 2 -type f \
       \( -iname '*.img' -o -iname '*.dd' -o -iname '*.raw' \) \
       -size +${MIN_DISK_IMAGE_MB}M \
       -print 2>/dev/null | head -n 1 | grep . || return 1
}

fetch_disk_image() {
  info "Providing the NeXTSTEP disk image"

  if [[ ! -d "$NEXTSTEP_DIR" ]]; then
    mkdir -p "$NEXTSTEP_DIR"
    undo "remove ${NEXTSTEP_DIR}" "rmdir $(printf '%q' "$NEXTSTEP_DIR")"
  fi

  if find_disk_image > /dev/null; then
    skip "found $(basename "$(find_disk_image)")"
    return
  fi

  # What the archive adds is worked out by comparing the directory before and
  # after, so the undo removes those files and nothing that was already here.
  local before after
  before="$(mktemp)"
  after="$(mktemp)"
  find "$NEXTSTEP_DIR" -maxdepth 1 -type f | sort > "$before"

  local archive="${NEXTSTEP_DIR}/${DISK_ARCHIVE}"
  [[ -f "$archive" ]] || wget -q --show-progress -O "$archive" "$DISK_ARCHIVE_URL"
  7z x -y -o"$NEXTSTEP_DIR" "$archive" > /dev/null

  find "$NEXTSTEP_DIR" -maxdepth 1 -type f | sort > "$after"

  local added=() line
  while IFS= read -r line; do
    [[ -n "$line" ]] && added+=("$(printf '%q' "$line")")
  done < <(comm -13 "$before" "$after")
  rm -f "$before" "$after"

  [[ ${#added[@]} -gt 0 ]] && undo "remove the fetched disk image" "rm -f ${added[*]}"

  find_disk_image > /dev/null || abort "No disk image in the archive. Look inside ${NEXTSTEP_DIR} yourself."
}

# ---------------------------------------------------------------------------
# 6  Configuration, with the image path filled in from this machine.
# ---------------------------------------------------------------------------

make_documents() {
  info "Making ${PICTURES_DIR}"

  if [[ -d "$PICTURES_DIR" ]]; then
    skip "already present"
    return
  fi

  mkdir -p "$PICTURES_DIR"
  # Only the directories this run created, and rmdir rather than rm, so a
  # folder somebody has put pictures in is left where it is.
  undo "remove ${DOCUMENTS_DIR} if it is empty" \
       "rmdir -p $(printf '%q' "$PICTURES_DIR") 2>/dev/null || true"
}

write_config() {
  info "Writing ${CONFIG_FILE}"

  if [[ -f "$CONFIG_FILE" ]]; then
    skip "already present, left untouched"
    return
  fi

  local image
  image="$(find_disk_image)" || abort "No disk image to point the configuration at."

  if [[ ! -d "$CONFIG_DIR" ]]; then
    mkdir -p "$CONFIG_DIR"
    undo "remove ${CONFIG_DIR}" "rmdir $(printf '%q' "$CONFIG_DIR")"
  fi

  # Only the keys that differ from what Previous writes by default. Everything
  # else it fills in itself the first time it exits, including the path to the
  # ROM of a Turbo Cube.
  cat > "$CONFIG_FILE" <<EOF
[ConfigDialog]
bShowConfigDialogAtStartup = FALSE

[Screen]
bFullScreen = TRUE
bShowStatusbar = FALSE
bShowTitlebar = FALSE

[Boot]
nBootDevice = 1
bVisible = FALSE

[HardDisk]
szImageName0 = ${image}
nDeviceType0 = 1
bDiskInserted0 = TRUE
bWriteProtected0 = FALSE

[System]
nMachineType = 1
nCpuLevel = 4
bTurbo = TRUE
nCpuFreq = 33
EOF

  undo "remove the Previous configuration" "rm -f $(printf '%q' "$CONFIG_FILE")"
  skip "disk image: ${image}"
}

# ---------------------------------------------------------------------------
# 7  Log in on the text console without being asked.
# ---------------------------------------------------------------------------

enable_autologin() {
  info "Enabling console autologin"

  if [[ -f "$AUTOLOGIN" ]]; then
    skip "already enabled"
    return
  fi

  local previous_target
  previous_target="$(systemctl get-default)"

  sudo raspi-config nonint do_boot_behaviour B2
  undo "restore the previous boot behaviour" \
       "sudo rm -f $(printf '%q' "$AUTOLOGIN"); sudo systemctl --quiet set-default $(printf '%q' "$previous_target")"
}

# ---------------------------------------------------------------------------
# 8  Silence all five things that draw on the screen before NeXTSTEP does: the
#    firmware splash, the kernel logo and its messages, systemd's status list,
#    the blinking cursor of the text console, and the login banner.
#
#    The banner is the one that outlasts the boot. Since the console waits for
#    the emulator rather than exiting, nothing overwrites what login printed,
#    so it stays on screen for as long as the machine is switched off.
# ---------------------------------------------------------------------------

quieten_boot() {
  info "Silencing the boot"

  if ! grep -q '^disable_splash=1' "$CONFIG_TXT"; then
    sudo cp "$CONFIG_TXT" "${CONFIG_TXT}.nextstep-rpi.backup"
    echo 'disable_splash=1' | sudo tee -a "$CONFIG_TXT" > /dev/null
    undo "restore ${CONFIG_TXT}" \
         "sudo mv -f $(printf '%q' "${CONFIG_TXT}.nextstep-rpi.backup") $(printf '%q' "$CONFIG_TXT")"
  fi

  if grep -q 'logo.nologo' "$CMDLINE"; then
    skip "cmdline already set"
    return
  fi

  sudo cp "$CMDLINE" "${CMDLINE}.nextstep-rpi.backup"
  undo "restore ${CMDLINE}" \
       "sudo mv -f $(printf '%q' "${CMDLINE}.nextstep-rpi.backup") $(printf '%q' "$CMDLINE")"

  # The console is moved rather than added: two console= arguments would leave
  # the kernel writing to tty1 as well, which is the one on screen.
  if grep -q 'console=tty1' "$CMDLINE"; then
    sudo sed -i 's/console=tty1/console=tty3/' "$CMDLINE"
  elif ! grep -q 'console=tty' "$CMDLINE"; then
    sudo sed -i '1s/^/console=tty3 /' "$CMDLINE"
  fi

  sudo sed -i '1s/$/ quiet loglevel=0 logo.nologo vt.global_cursor_default=0 systemd.show_status=false/' "$CMDLINE"

  quieten_login
}

# /etc/issue and /etc/motd, which agetty and login print before ~/.profile ever
# runs. Stopped at the source rather than cleared afterwards, so there is no
# flash of text to erase.
quieten_login() {
  if [[ ! -f "$HUSHLOGIN" ]]; then
    touch "$HUSHLOGIN"
    undo "let login print the message of the day again" \
         "rm -f $(printf '%q' "$HUSHLOGIN")"
  fi

  if [[ -f "$AUTOLOGIN" ]] && ! grep -q -- '--noissue' "$AUTOLOGIN"; then
    sudo sed -i 's/agetty --autologin/agetty --noissue --autologin/' "$AUTOLOGIN"
    sudo systemctl daemon-reload
  fi
}

# ---------------------------------------------------------------------------
# 8b  Let the browser restart and switch off the Pi, without giving the admin
#     tool any privileges.
#
#     Only root may power a machine down, and the admin tool runs as an
#     ordinary user with NoNewPrivileges set, which is what stops sudo working
#     there and is worth keeping. So the tool does not run the command. It
#     leaves a file in its own runtime directory, and a systemd path unit
#     running as root does the one thing that file means.
#
#     The name of the file is the whole of the request. Nothing is passed and
#     there is no shell to pass it through, so these units cannot be talked
#     into doing anything but the one command each names.
#
#     All of that arrives with the package: the service, its configuration and
#     the four units. The steps here build that package out of the checkout and
#     let apt install it, so there is one place the tool comes from and one
#     command that takes it away again.
#
#     Two of them, because the tool outlives the installation. install_admin
#     puts it on a machine that has none, and update_admin replaces the one a
#     machine already has, which is what a person does whenever this repository
#     has moved on and their Pi has not.
# ---------------------------------------------------------------------------

# Where fetch_admin_package left the package. A variable rather than something
# printed, because the two callers below also print as they go and a function
# that answers through stdout could only do one or the other.
ADMIN_PACKAGE=""

# The version dpkg has, or nothing at all where the tool is absent.
admin_version() {
  dpkg-query -W -f='${Version}' previously 2>/dev/null || true
}

admin_is_installed() {
  dpkg-query -W -f='${Status}' previously 2>/dev/null | grep -q "ok installed"
}

# Two ways in, because this script arrives two ways. Run out of a checkout it
# builds the package from what is already beside it, which is a second and
# always matches that checkout. Run from the web, through the line on the
# Previously page, there is nothing beside it and it takes the package from the
# latest release.
fetch_admin_package() {
  local packaging="${SCRIPT_DIR}/admin/packaging"
  if [[ -f "${packaging}/build.py" ]]; then
    ADMIN_PACKAGE="$(python3 "${packaging}/build.py" | awk '{print $2}')" \
      || abort "Could not build the admin package."
  else
    ADMIN_PACKAGE="$(mktemp -d)/${PACKAGE_FILE}"
    curl -fsSL -o "$ADMIN_PACKAGE" "$PACKAGE_URL" \
      || abort "Could not fetch ${PACKAGE_URL}."
    undo "remove the downloaded package" "rm -f $(printf '%q' "$ADMIN_PACKAGE")"
  fi
}

install_admin() {
  info "Installing the admin tool"

  if admin_is_installed; then
    skip "already installed, $(admin_version). --update-admin replaces it."
    return
  fi

  fetch_admin_package

  # apt rather than dpkg, so the dependencies it declares are resolved. The
  # package enables and starts the service and both path units itself.
  sudo apt-get install -y -qq "$ADMIN_PACKAGE" \
    || abort "Could not install ${ADMIN_PACKAGE}."

  undo "remove the admin tool" "sudo apt-get purge -y -qq previously"
}

# The admin tool on its own, for a machine that already has everything else.
# It is the one part that changes often enough to be worth replacing by itself,
# and the only one a person watches through a browser, where a stale copy looks
# exactly like a current one.
#
# Nothing here is written to the undo record. A run that fails half way leaves
# the tool that was already installed, and rolling that back would take away a
# working one to answer for a replacement that never happened.
update_admin() {
  info "Updating the admin tool"

  local before
  before="$(admin_version)"
  [[ -n "$before" ]] || abort "The admin tool is not installed. Run this without --update-admin."

  fetch_admin_package

  # --reinstall because a package built from a checkout carries the version in
  # server.py, which is the last release's until the next one is cut. Without
  # it apt calls an identically numbered package the newest one it has and does
  # nothing, silently. --allow-downgrades is for the other direction, which is
  # somebody going back to a release from a checkout that ran ahead of it.
  sudo apt-get install -y -qq --reinstall --allow-downgrades "$ADMIN_PACKAGE" \
    || abort "Could not install ${ADMIN_PACKAGE}."

  local after
  after="$(admin_version)"
  if [[ "$before" == "$after" ]]; then
    skip "${after}, put in place again"
  else
    skip "${before} replaced by ${after}"
  fi
  skip "The service is restarted by the package, so the browser has it on the next load."
}

# ---------------------------------------------------------------------------
# 9  Start Previous on the first console only, so SSH stays usable as the way
#    back into a machine whose screen now belongs to NeXTSTEP.
# ---------------------------------------------------------------------------

install_autostart() {
  info "Installing the autostart"

  if [[ -f "$PROFILE" ]] && grep -qF "$AUTOSTART_MARKER" "$PROFILE"; then
    skip "already present"
    return
  fi

  # Fenced by markers so the undo removes exactly this block and leaves
  # whatever else the file holds.
  cat >> "$PROFILE" <<EOF

${AUTOSTART_MARKER}
# Hand the first console to Previous. XDG_VTNR carries the number of the text
# console and is set only where one is actually behind the login, so an SSH
# session falls through and stays the way in once the screen is taken.
#
# The wait is how the admin tool stops and starts the emulator without any
# privileges at all: it creates ${HOLD_FILE} to hold it down and removes the
# file to let it come back. Waiting rather than exiting matters twice. It keeps
# the console from falling through to a shell prompt while the emulator is
# held, and it avoids the race that stopping through systemd would have, since
# this unit restarts itself the moment a session ends and would bring a fresh
# emulator up underneath whatever stopped the last one.
#
# The file is on a tmpfs, so a board that has just booted never finds one and
# always starts its emulator.
#
# The directory it runs in is where it writes a screen grab, and the admin tool
# reads those and removes them. Its own rather than the home directory, so the
# tool needs write access to that one directory and to nothing else of yours.
if [ "\$XDG_VTNR" = 1 ] && [ -z "\$WAYLAND_DISPLAY" ]; then
  clear
  while [ -f ${HOLD_FILE} ]; do sleep 2; done
  mkdir -p ${WORK_DIR}
  cd ${WORK_DIR}
  exec cage -- /usr/bin/previous
fi
${AUTOSTART_END}
EOF

  undo "remove the autostart from ${PROFILE}" \
       "remove_autostart_block $(printf '%q' "$PROFILE")"
}

# ---------------------------------------------------------------------------
# 10  Send sound to a speaker rather than to HDMI.
#
#     Raspberry Pi OS sets no audio default, so ALSA falls back to card 0, and
#     on a Pi that is the first HDMI output. Anything plugged into USB stays
#     silent. The emulator picks its output device once, through SDL, when it
#     starts, and never asks again: unplugging a speaker therefore silences it
#     until the emulator is restarted, even after plugging it back in.
#
#     A sound server answers both at once. PipeWire connects a client to itself
#     rather than to a card, so it can move a stream when a device appears or
#     goes away, and WirePlumber ranks a USB card above HDMI on its own, at
#     priority 1009 against 1000. The emulator needs no configuration for this:
#     SDL3 here is built with a PipeWire backend and prefers it when a server is
#     running.
#
#     What is left to set is the volume a speaker starts at, because the stock
#     value is too quiet to hear NeXTSTEP's own sounds through.
# ---------------------------------------------------------------------------

install_audio() {
  info "Sending sound to a speaker"

  local wanted=(pipewire wireplumber pipewire-alsa) missing=() package
  for package in "${wanted[@]}"; do
    dpkg-query -W -f='${Status}' "$package" 2>/dev/null | grep -q "ok installed" || missing+=("$package")
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    sudo apt-get install -y -qq "${missing[@]}"
    undo "remove ${missing[*]}" "sudo apt-get remove -y -qq ${missing[*]}"
  else
    skip "pipewire already installed"
  fi

  if [[ -f "$WIREPLUMBER_CONF" ]]; then
    skip "volume already configured"
    return
  fi

  sudo install -m 0755 -d "$(dirname "$WIREPLUMBER_CONF")"
  sudo tee "$WIREPLUMBER_CONF" >/dev/null <<EOF
# A speaker plugged into this machine starts loud enough to be heard.
#
# The stock value is 0.064, which is 40 per cent on a linear scale, and
# NeXTSTEP's own sounds peak at about a third of full scale on top of that. The
# two together are inaudible on a small speaker.
#
# This applies the first time a device is seen. After that the volume that was
# set is remembered per device in ~/.local/state/wireplumber/default-routes.

wireplumber.settings = {
  device.routes.default-sink-volume = ${AUDIO_VOLUME}
}
EOF
  undo "remove ${WIREPLUMBER_CONF}" "sudo rm -f $(printf '%q' "$WIREPLUMBER_CONF")"
}

usage() {
  cat <<'EOF'
Usage: install.sh [--update-admin]

With no arguments it sets a Raspberry Pi up from nothing, and skips every step
it finds already done.

  --update-admin   Replace the admin tool with the newest one and touch nothing
                   else. Built from the checkout this script sits in, or taken
                   from the latest release where there is no checkout.
EOF
}

main() {
  case "${1:-}" in
    --update-admin)
      check_host
      update_admin
      COMPLETED=true
      return
      ;;
    --help | -h)
      usage
      COMPLETED=true
      return
      ;;
    "") ;;
    *) abort "Unknown option: ${1}. Try --help." ;;
  esac

  check_host
  install_packages
  add_repository
  install_previous
  fetch_disk_image
  make_documents
  write_config
  enable_autologin
  quieten_boot
  install_admin
  install_autostart
  install_audio

  COMPLETED=true
  local image
  image="$(find_disk_image || echo 'none')"

  info "Done."
  skip "disk image:   ${image}"
  skip "config:       ${CONFIG_FILE}"
  skip "cmdline saved as ${CMDLINE}.nextstep-rpi.backup"
  skip "sound:        through PipeWire, to a USB speaker where one is plugged in"
  skip ""
  if dpkg-query -W -f='${Status}' previously 2>/dev/null | grep -q "ok installed"; then
    # The one thing somebody needs after this finishes, and the reason they
    # ran it. The name rather than the address, because a Pi answers to
    # <hostname>.local on the network it is on and its address may not last.
    info "The admin tool is at http://$(hostname).local:8810"
    skip "Its token, which the browser asks for once:"
    skip "  sudo cat /var/lib/previously/token"
    skip ""
  fi
  skip "Log in at the Pi's own keyboard to check it before rebooting."
  skip "NeXTSTEP account: me, no password."
}

main "$@"
