#!/usr/bin/env bash
#
# build-windows.sh - build the Turbo Recorder Windows installer (NSIS).
#
# Usage:
#   packaging/build-windows.sh
#
# Downloads and verifies the pinned gyan.dev static FFmpeg Windows build (same
# binary and SHA-256 as the CI release pipeline) and the pinned python.org
# Python 3.12 Windows installer, extracts ffmpeg.exe/ffprobe.exe, then runs
# makensis to produce:
#   dist/Turbo_Recorder-<version>-windows-x64-setup.exe
#
# The installer ships turborec.py, the bundled FFmpeg binaries AND the Python
# 3.12 installer (run silently during install unless a Python 3.8+ with Tk is
# already present), so the target machine needs NO prerequisites.
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
FFMPEG_URL="https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-essentials_build.zip"
FFMPEG_SHA256="60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"

# --- Pinned Python 3.12 installer (bundled so the app needs no prerequisites).
# The newest 3.12.x with Windows binaries (3.12.11+ are source-only); 3.13+
# drops Windows 8.1 support. SHA-256 verified; the file also matches the MD5
# published on the python.org release page (5eddb0b6f12c852725de071ae681dde4).
PYTHON_URL="https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
PYTHON_SHA256="67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb"

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

# Re-extract every build: existing executables are not evidence that the
# verified ZIP was their source (especially after updating the pinned version).
EXTRACT_DIR="$(mktemp -d "${BUILD_DIR}/ffmpeg-extract.XXXXXX")"
trap 'rm -rf -- "${EXTRACT_DIR}"' EXIT
7z x -y -o"${EXTRACT_DIR}" "${ZIP}" >/dev/null
FF="$(find "${EXTRACT_DIR}" -type f -name ffmpeg.exe | head -1)"
FP="$(find "${EXTRACT_DIR}" -type f -name ffprobe.exe | head -1)"
if [ -z "${FF}" ] || [ -z "${FP}" ]; then
    echo "error: ffmpeg.exe/ffprobe.exe not in archive" >&2
    exit 1
fi
cp -p "${FF}" "${WIN_DIR}/ffmpeg.exe"
cp -p "${FP}" "${WIN_DIR}/ffprobe.exe"

# --- Fetch + verify the pinned Python installer. ------------------------------
PYEXE="${BUILD_DIR}/python-3.12.10-amd64.exe"
if [ ! -f "${PYEXE}" ] || ! echo "${PYTHON_SHA256}  ${PYEXE}" | sha256sum -c - >/dev/null 2>&1; then
    echo "Downloading ${PYTHON_URL} ..."
    curl -L --retry 3 -o "${PYEXE}" "${PYTHON_URL}"
    echo "${PYTHON_SHA256}  ${PYEXE}" | sha256sum -c -   # abort on tamper/mismatch
fi

# --- Build the installer. -----------------------------------------------------
echo "Building Turbo_Recorder-${VERSION}-windows-x64-setup.exe ..."
# -D (not /D): makensis on non-Windows hosts uses Unix-style switches.
makensis -DVERSION="${VERSION}" \
    -DPYTHON_INSTALLER="..\\build\\python-3.12.10-amd64.exe" \
    "${SCRIPT_DIR}/turborec.nsi" >/dev/null

if [ ! -s "${DIST_DIR}/Turbo_Recorder-${VERSION}-windows-x64-setup.exe" ]; then
    echo "error: makensis did not produce the installer" >&2
    exit 1
fi

echo
echo "Build complete. Installer (bundles Python 3.12 + FFmpeg):"
ls -l "${DIST_DIR}/Turbo_Recorder-${VERSION}-windows-x64-setup.exe"
