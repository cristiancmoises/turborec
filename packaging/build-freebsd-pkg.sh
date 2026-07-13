#!/bin/sh
# =============================================================================
#  build-freebsd-pkg.sh — build dist/turborec-<version>.pkg (native FreeBSD)
#
#  Produces a real FreeBSD binary package installable with:
#      pkg add ./turborec-<version>.pkg
#
#  Turbo Recorder is architecture-independent (pure Python stdlib + a POSIX
#  shell front-end), so the package installs the engine under ${PREFIX}/bin and
#  the desktop assets under ${PREFIX}/share.  Runtime prerequisites (python3,
#  ffmpeg, and optionally wf-recorder for Wayland) are intentionally NOT hard
#  dependencies so the package installs cleanly from a local file on any
#  FreeBSD release; they are listed in the description and printed by pkg.
#
#  Must run on FreeBSD (needs pkg-create(8)).  License: GPL-3.0.
# =============================================================================
set -eu

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd -P)"
DIST_DIR="${REPO_ROOT}/dist"
PREFIX="${PREFIX:-/usr/local}"

log() { printf '[build-freebsd-pkg] %s\n' "$*" >&2; }
die() { printf '[build-freebsd-pkg] ERROR: %s\n' "$*" >&2; exit 1; }

command -v pkg >/dev/null 2>&1 || die "pkg(8) not found — this script must run on FreeBSD"
[ -f "${REPO_ROOT}/turborec.py" ]   || die "missing ${REPO_ROOT}/turborec.py"
[ -f "${REPO_ROOT}/turborecorder" ] || die "missing ${REPO_ROOT}/turborecorder"

PKG_VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "${REPO_ROOT}/turborec.py" | head -1)"
[ -n "${PKG_VERSION}" ] || die "could not read VERSION from turborec.py"

log "building turborec-${PKG_VERSION}.pkg (prefix ${PREFIX})"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/turborec-pkg.XXXXXX")"
trap 'rm -rf -- "${WORK}"' EXIT INT HUP TERM
STAGE="${WORK}/stage"

# ---- stage the install layout under ${PREFIX} -------------------------------
mkdir -p "${STAGE}${PREFIX}/bin" \
         "${STAGE}${PREFIX}/share/applications" \
         "${STAGE}${PREFIX}/share/icons/hicolor/scalable/apps" \
         "${STAGE}${PREFIX}/share/doc/turborec"

install -m 0755 "${REPO_ROOT}/turborec.py"   "${STAGE}${PREFIX}/bin/turborec"
install -m 0755 "${REPO_ROOT}/turborecorder" "${STAGE}${PREFIX}/bin/turborecorder"

[ -f "${SCRIPT_DIR}/turborec.desktop" ] && install -m 0644 "${SCRIPT_DIR}/turborec.desktop" \
    "${STAGE}${PREFIX}/share/applications/turborec.desktop"
[ -f "${SCRIPT_DIR}/turborec.svg" ] && install -m 0644 "${SCRIPT_DIR}/turborec.svg" \
    "${STAGE}${PREFIX}/share/icons/hicolor/scalable/apps/turborec.svg"
for doc in README.md CHANGELOG.md LICENSE; do
    [ -f "${REPO_ROOT}/${doc}" ] && install -m 0644 "${REPO_ROOT}/${doc}" \
        "${STAGE}${PREFIX}/share/doc/turborec/${doc}"
done

# ---- plist: every staged file, path relative to PREFIX ----------------------
PLIST="${WORK}/pkg-plist"
( cd "${STAGE}${PREFIX}" && find . -type f | sed 's|^\./||' | LC_ALL=C sort ) > "${PLIST}"
log "plist entries:"; sed 's/^/  /' "${PLIST}" >&2

# ---- +MANIFEST (UCL metadata) ----------------------------------------------
# ABI is intentionally left for pkg to stamp from the build host; the package
# is noarch in practice, so `pkg add -f` installs it across FreeBSD releases.
MANIFEST="${WORK}/+MANIFEST"
cat > "${MANIFEST}" <<EOF
name: turborec
version: "${PKG_VERSION}"
origin: multimedia/turborec
comment: "State-of-the-art hardware-accelerated screen and audio recorder"
www: https://github.com/cristiancmoises/turborec
maintainer: ethicalhacker@riseup.net
prefix: ${PREFIX}
categories: [multimedia]
licenselogic: single
licenses: [GPLv3]
desc: <<EOD
Turbo Recorder captures your screen and audio at the best quality your
hardware can deliver.  It probes the machine and configures everything
automatically: OS, display server, CPU/GPU, the best hardware video encoder
(NVENC, QSV, VAAPI, AMF, VideoToolbox, or x264), resolution, and the
microphone / system-audio sources, then records or live-streams (OBS-style
RTMP to YouTube) with a quality-first FFmpeg pipeline.

Two front-ends share one engine:
  * turborec      - cross-platform CLI + GUI (Python, stdlib only)
  * turborecorder - fast, dependency-light shell CLI for X11

Runtime prerequisites (install separately):
  pkg install python3 ffmpeg        # required
  pkg install wf-recorder           # optional, for Wayland/wlroots capture
  py39-tkinter (or matching)        # optional, for the GUI
EOD
EOF

# ---- build ------------------------------------------------------------------
mkdir -p "${DIST_DIR}"
log "running pkg create"
pkg create -o "${DIST_DIR}" -r "${STAGE}" -M "${MANIFEST}" -p "${PLIST}"

# pkg create writes turborec-<version>.pkg (or .txz on older pkg defaults).
OUT=""
for cand in "${DIST_DIR}/turborec-${PKG_VERSION}.pkg" "${DIST_DIR}/turborec-${PKG_VERSION}.txz"; do
    [ -f "${cand}" ] && OUT="${cand}" && break
done
[ -n "${OUT}" ] || die "pkg create did not produce an artifact"
log "built: ${OUT}"
printf '%s\n' "${OUT}"
