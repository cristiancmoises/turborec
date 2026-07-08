#!/usr/bin/env bash
# =============================================================================
#  build-appimage.sh — package Turbo Recorder as a relocatable AppImage
#
#  Output: dist/Turbo_Recorder-3.1.0-x86_64.AppImage
#
#  WHAT THIS PRODUCES
#  ------------------
#  A *thin* AppImage that bundles only the Turbo Recorder scripts, the desktop
#  entry and the icons. It deliberately does NOT bundle a Python interpreter,
#  Tk, or FFmpeg. At runtime the AppRun execs the HOST python3:
#
#      python3 $APPDIR/usr/bin/turborec "$@"
#
#  so the program uses the host's python3 (>= 3.8), python3-tk (for the GUI)
#  and ffmpeg (the recording engine, with its real hardware encoders). See the
#  comments in packaging/AppRun for the full rationale.
#
#  USAGE
#  -----
#      packaging/build-appimage.sh
#
#  Honored environment variables:
#      APPIMAGETOOL   path to an existing appimagetool (skips the download)
#      ARCH           target arch tag (default: x86_64)
#      NO_DOWNLOAD=1  fail instead of downloading appimagetool
# =============================================================================
set -euo pipefail

# ---------------------------------------------------------------------------
# Package metadata
# ---------------------------------------------------------------------------
APP_NAME="turborec"
APP_PRETTY="Turbo Recorder"
VERSION="3.1.0"
MAINTAINER="Cristian Cezar Moises <ethicalhacker@riseup.net>"
HOMEPAGE="https://github.com/cristiancmoises/turborec"
LICENSE="GPL-3.0"
ARCH="${ARCH:-x86_64}"

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

BUILD_DIR="${REPO_ROOT}/build"
APPDIR="${BUILD_DIR}/${APP_PRETTY// /_}.AppDir"
DIST_DIR="${REPO_ROOT}/dist"
TOOLS_DIR="${BUILD_DIR}/tools"

OUTPUT="${DIST_DIR}/${APP_PRETTY// /_}-${VERSION}-${ARCH}.AppImage"

# Source assets
SRC_PY="${REPO_ROOT}/turborec.py"
SRC_BASH="${REPO_ROOT}/turborecorder"
SRC_README="${REPO_ROOT}/README.md"
SRC_DESKTOP="${SCRIPT_DIR}/${APP_NAME}.desktop"
SRC_SVG="${SCRIPT_DIR}/${APP_NAME}.svg"
SRC_APPRUN="${SCRIPT_DIR}/AppRun"

# appimagetool (release tag is pinned so the URL is reproducible).
APPIMAGETOOL_TAG="continuous"
APPIMAGETOOL_URL="https://github.com/AppImage/appimagetool/releases/download/${APPIMAGETOOL_TAG}/appimagetool-${ARCH}.AppImage"
# NOTE on integrity: appimagetool's "continuous" build is rolling, so a single
# hard-coded SHA-256 would go stale. We therefore (a) honor an externally
# supplied APPIMAGETOOL binary, (b) print the SHA-256 of whatever we download so
# it can be recorded/audited, and (c) let you pin one via APPIMAGETOOL_SHA256.
APPIMAGETOOL_SHA256="${APPIMAGETOOL_SHA256:-}"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33mwarning:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31merror:\033[0m %s\n' "$*" >&2; exit 1; }

need_file() {
    [ -f "$1" ] || die "required source file not found: $1"
}

# ---------------------------------------------------------------------------
# Pre-flight: verify source files exist
# ---------------------------------------------------------------------------
log "Turbo Recorder ${VERSION} (${ARCH}) — AppImage build"
log "maintainer: ${MAINTAINER}"
log "homepage:   ${HOMEPAGE}"
log "license:    ${LICENSE}"

need_file "${SRC_PY}"
need_file "${SRC_BASH}"
need_file "${SRC_README}"
need_file "${SRC_DESKTOP}"
need_file "${SRC_SVG}"
need_file "${SRC_APPRUN}"

# Sanity-check the python script shebang the layout promises.
head -n 1 "${SRC_PY}" | grep -q '^#!/usr/bin/env python3' \
    || warn "turborec.py first line is not '#!/usr/bin/env python3'"

# ---------------------------------------------------------------------------
# Locate an SVG -> PNG rasterizer (for the 256x256 hicolor icon)
# ---------------------------------------------------------------------------
rasterize_png() {
    # rasterize_png <svg> <png> <size>
    local svg="$1" png="$2" size="$3"
    if command -v rsvg-convert >/dev/null 2>&1; then
        rsvg-convert -w "${size}" -h "${size}" -o "${png}" "${svg}"
    elif command -v inkscape >/dev/null 2>&1; then
        inkscape "${svg}" --export-type=png --export-filename="${png}" \
            -w "${size}" -h "${size}" >/dev/null 2>&1
    elif command -v magick >/dev/null 2>&1; then
        magick -background none -density 256 "${svg}" \
            -resize "${size}x${size}" "${png}"
    elif command -v convert >/dev/null 2>&1; then
        convert -background none -density 256 "${svg}" \
            -resize "${size}x${size}" "${png}"
    else
        return 1
    fi
}

# ---------------------------------------------------------------------------
# Clean & create the AppDir skeleton
# ---------------------------------------------------------------------------
log "preparing AppDir at ${APPDIR}"
rm -rf "${APPDIR}"
mkdir -p \
    "${APPDIR}/usr/bin" \
    "${APPDIR}/usr/share/applications" \
    "${APPDIR}/usr/share/doc/${APP_NAME}" \
    "${APPDIR}/usr/share/icons/hicolor/scalable/apps" \
    "${APPDIR}/usr/share/icons/hicolor/256x256/apps" \
    "${DIST_DIR}" \
    "${TOOLS_DIR}"

# ---------------------------------------------------------------------------
# Install payload — matches the canonical install layout exactly:
#   /usr/bin/turborec                            (turborec.py, 0755)
#   /usr/bin/turborecorder                       (bash script, 0755)
#   /usr/share/applications/turborec.desktop
#   /usr/share/icons/hicolor/scalable/apps/turborec.svg
#   /usr/share/icons/hicolor/256x256/apps/turborec.png
#   /usr/share/doc/turborec/README.md
# ---------------------------------------------------------------------------
log "installing scripts into usr/bin"
install -m 0755 "${SRC_PY}"   "${APPDIR}/usr/bin/turborec"
install -m 0755 "${SRC_BASH}" "${APPDIR}/usr/bin/turborecorder"

log "installing desktop entry"
install -m 0644 "${SRC_DESKTOP}" \
    "${APPDIR}/usr/share/applications/${APP_NAME}.desktop"

log "installing documentation"
install -m 0644 "${SRC_README}" "${APPDIR}/usr/share/doc/${APP_NAME}/README.md"

log "installing scalable icon"
install -m 0644 "${SRC_SVG}" \
    "${APPDIR}/usr/share/icons/hicolor/scalable/apps/${APP_NAME}.svg"

log "rasterizing 256x256 icon from svg"
if rasterize_png "${SRC_SVG}" \
        "${APPDIR}/usr/share/icons/hicolor/256x256/apps/${APP_NAME}.png" 256; then
    chmod 0644 "${APPDIR}/usr/share/icons/hicolor/256x256/apps/${APP_NAME}.png"
else
    die "no SVG rasterizer found (need one of: rsvg-convert, inkscape, magick, convert).
         Install librsvg2-bin / inkscape / imagemagick and re-run."
fi

# ---------------------------------------------------------------------------
# AppDir-root requirements for AppImage:
#   * AppRun           (the entry point)
#   * <app>.desktop    (a copy must sit at the AppDir root)
#   * <app>.svg        (top-level icon, name must match the desktop Icon=)
#   * .DirIcon         (icon shown by file managers)
# ---------------------------------------------------------------------------
log "installing AppRun"
install -m 0755 "${SRC_APPRUN}" "${APPDIR}/AppRun"

log "placing top-level desktop entry + icons"
install -m 0644 "${SRC_DESKTOP}" "${APPDIR}/${APP_NAME}.desktop"
install -m 0644 "${SRC_SVG}"     "${APPDIR}/${APP_NAME}.svg"
# .DirIcon is conventionally the raster icon; reuse the 256x256 PNG.
install -m 0644 \
    "${APPDIR}/usr/share/icons/hicolor/256x256/apps/${APP_NAME}.png" \
    "${APPDIR}/.DirIcon"

# ---------------------------------------------------------------------------
# Obtain appimagetool
# ---------------------------------------------------------------------------
fetch() {
    # fetch <url> <dest>
    local url="$1" dest="$2"
    if command -v curl >/dev/null 2>&1; then
        curl -fL --retry 3 -o "${dest}" "${url}"
    elif command -v wget >/dev/null 2>&1; then
        wget -O "${dest}" "${url}"
    else
        die "neither curl nor wget is available to download appimagetool"
    fi
}

resolve_appimagetool() {
    # 1) explicit override
    if [ -n "${APPIMAGETOOL:-}" ]; then
        [ -x "${APPIMAGETOOL}" ] || die "APPIMAGETOOL='${APPIMAGETOOL}' is not executable"
        printf '%s' "${APPIMAGETOOL}"
        return 0
    fi
    # 2) already on PATH
    if command -v appimagetool >/dev/null 2>&1; then
        command -v appimagetool
        return 0
    fi
    # 3) previously downloaded into the build tree
    local cached="${TOOLS_DIR}/appimagetool-${ARCH}.AppImage"
    if [ -x "${cached}" ]; then
        printf '%s' "${cached}"
        return 0
    fi
    # 4) download
    [ "${NO_DOWNLOAD:-0}" = "1" ] && \
        die "appimagetool not found and NO_DOWNLOAD=1 (set APPIMAGETOOL=/path/to/appimagetool)"
    log "downloading appimagetool from ${APPIMAGETOOL_URL}" >&2
    fetch "${APPIMAGETOOL_URL}" "${cached}"
    chmod +x "${cached}"

    # Integrity: report the digest; verify it if a pin was supplied.
    if command -v sha256sum >/dev/null 2>&1; then
        local got
        got="$(sha256sum "${cached}" | awk '{print $1}')"
        log "appimagetool sha256: ${got}" >&2
        if [ -n "${APPIMAGETOOL_SHA256}" ] && [ "${got}" != "${APPIMAGETOOL_SHA256}" ]; then
            rm -f "${cached}"
            die "appimagetool checksum mismatch (expected ${APPIMAGETOOL_SHA256}, got ${got})"
        fi
    else
        warn "sha256sum unavailable — cannot verify appimagetool integrity"
    fi
    printf '%s' "${cached}"
}

APPIMAGETOOL_BIN="$(resolve_appimagetool)"
log "using appimagetool: ${APPIMAGETOOL_BIN}"

# ---------------------------------------------------------------------------
# Build the AppImage
# ---------------------------------------------------------------------------
log "building ${OUTPUT}"
rm -f "${OUTPUT}"

# ARCH must be exported for appimagetool to embed the right arch metadata.
# Many CI containers lack FUSE; --appimage-extract-and-run lets the tool run
# without it. We also try a plain invocation as a fallback.
export ARCH
run_tool() {
    if "${APPIMAGETOOL_BIN}" --appimage-extract-and-run "${APPDIR}" "${OUTPUT}"; then
        return 0
    fi
    warn "extract-and-run invocation failed; retrying without it (needs FUSE)"
    "${APPIMAGETOOL_BIN}" "${APPDIR}" "${OUTPUT}"
}

if ! run_tool; then
    die "appimagetool failed to build the AppImage"
fi

chmod +x "${OUTPUT}"

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
log "build complete"
printf '    %s\n' "${OUTPUT}"
if command -v sha256sum >/dev/null 2>&1; then
    ( cd "${DIST_DIR}" && sha256sum "$(basename "${OUTPUT}")" )
fi
cat <<EOF

Runtime requirements (provided by the HOST, NOT bundled):
  * python3 (>= 3.8)
  * tkinter        — Debian/Ubuntu: python3-tk   Fedora/RHEL: python3-tkinter
  * ffmpeg
Run it with:  ./$(basename "${OUTPUT}")        (launches the GUI)
              ./$(basename "${OUTPUT}") record  (CLI, see 'record -h')
EOF
