#!/usr/bin/env bash
#
# build-windows.sh - build the Turbo Recorder Windows installer (NSIS).
#
# Usage:
#   packaging/build-windows.sh
#
# Downloads the pinned gyan.dev static FFmpeg Windows build (same binary and
# SHA-256 as the CI release pipeline), extracts ffmpeg.exe/ffprobe.exe, then
# runs makensis to produce:
#   dist/Turbo_Recorder-<version>-windows-x64-setup.exe
#
# The installer ships turborec.py plus the bundled FFmpeg binaries; a
# Python 3.8+ runtime (with Tk) is expected on the target machine, matching
# the .deb/.rpm dependency policy.
#
set -euo pipefail

# --- Locate the repository root (this script lives in <root>/packaging). -----
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd)"

# --- Version comes from the engine itself. -----------------------------------
VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "${REPO_ROOT}/turborec.py" | head -1)"
if [ -z "${VERSION}" ]; then
    echo "error: could not read VERSION from turborec.py" >&2
    exit 1
fi

# --- Pinned Windows FFmpeg (must match .github/workflows/release.yml). --------
FFMPEG_URL="https://github.com/GyanD/codexffmpeg/releases/download/8.1.2/ffmpeg-8.1.2-essentials_build.zip"
FFMPEG_SHA256="db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"

# --- Tool checks. -------------------------------------------------------------
command -v makensis >/dev/null 2>&1 || { echo "error: makensis (NSIS) not found" >&2; exit 1; }
command -v 7z >/dev/null 2>&1 || { echo "error: 7z not found" >&2; exit 1; }

# --- Working directories. -----------------------------------------------------
BUILD_DIR="${REPO_ROOT}/build"
DIST_DIR="${REPO_ROOT}/dist"
WIN_DIR="${BUILD_DIR}/win-bundle"
mkdir -p "${WIN_DIR}" "${DIST_DIR}"

# --- Fetch + verify the pinned FFmpeg build. ----------------------------------
ZIP="${BUILD_DIR}/ffmpeg-win.zip"
if [ ! -f "${ZIP}" ] || ! echo "${FFMPEG_SHA256}  ${ZIP}" | sha256sum -c - >/dev/null 2>&1; then
    echo "Downloading ${FFMPEG_URL} ..."
    curl -L --retry 3 -o "${ZIP}" "${FFMPEG_URL}"
    echo "${FFMPEG_SHA256}  ${ZIP}" | sha256sum -c -   # abort on tamper/mismatch
fi

if [ ! -f "${WIN_DIR}/ffmpeg.exe" ] || [ ! -f "${WIN_DIR}/ffprobe.exe" ]; then
    rm -rf "${BUILD_DIR}/ffmpeg-extract"
    mkdir -p "${BUILD_DIR}/ffmpeg-extract"
    7z x -y -o"${BUILD_DIR}/ffmpeg-extract" "${ZIP}" >/dev/null
    FF="$(find "${BUILD_DIR}/ffmpeg-extract" -type f -name ffmpeg.exe | head -1)"
    FP="$(find "${BUILD_DIR}/ffmpeg-extract" -type f -name ffprobe.exe | head -1)"
    [ -n "${FF}" ] && [ -n "${FP}" ] || { echo "error: ffmpeg.exe/ffprobe.exe not in archive" >&2; exit 1; }
    cp -p "${FF}" "${WIN_DIR}/ffmpeg.exe"
    cp -p "${FP}" "${WIN_DIR}/ffprobe.exe"
fi

# --- Build the installer. -----------------------------------------------------
echo "Building Turbo_Recorder-${VERSION}-windows-x64-setup.exe ..."
# -D (not /D): makensis on non-Windows hosts uses Unix-style switches.
makensis -DVERSION="${VERSION}" "${SCRIPT_DIR}/turborec.nsi" >/dev/null

if [ ! -s "${DIST_DIR}/Turbo_Recorder-${VERSION}-windows-x64-setup.exe" ]; then
    echo "error: makensis did not produce the installer" >&2
    exit 1
fi

echo
echo "Build complete. Installer:"
ls -l "${DIST_DIR}/Turbo_Recorder-${VERSION}-windows-x64-setup.exe"
