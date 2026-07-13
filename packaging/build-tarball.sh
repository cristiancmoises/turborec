#!/bin/sh
# =============================================================================
#  build-tarball.sh — build dist/turborec-<version>.tar.gz
#
#  A portable, architecture-independent binary release that installs on any
#  Unix with a POSIX shell and Python 3: FreeBSD, OpenBSD, NetBSD, DragonFly,
#  Linux, illumos, macOS.  Turbo Recorder is pure Python (stdlib only) plus a
#  POSIX shell front-end, so a single tarball runs everywhere unchanged.
#
#  The archive expands to a self-contained tree with an install.sh /
#  uninstall.sh pair that honours PREFIX and DESTDIR (BSD default PREFIX is
#  /usr/local, matching pkg conventions):
#
#      turborec-<version>/
#        turborec               (the CLI/GUI engine, run as `turborec`)
#        turborecorder          (the Bash X11 front-end)
#        install.sh uninstall.sh
#        README.md CHANGELOG.md LICENSE
#        share/applications/turborec.desktop
#        share/icons/hicolor/scalable/apps/turborec.svg
#
#  Written in strict POSIX sh (no bashisms) so it also runs under the base
#  /bin/sh on the BSDs.  License: GPL-3.0 (same as the project).
# =============================================================================
set -eu

# ---- resolve paths ----------------------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd -P)"
DIST_DIR="${REPO_ROOT}/dist"

log() { printf '[build-tarball] %s\n' "$*" >&2; }
die() { printf '[build-tarball] ERROR: %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "required tool not found: $1"; }

need tar
need gzip

[ -f "${REPO_ROOT}/turborec.py" ]   || die "missing ${REPO_ROOT}/turborec.py"
[ -f "${REPO_ROOT}/turborecorder" ] || die "missing ${REPO_ROOT}/turborecorder"

# ---- derive the version straight from the source of truth -------------------
PKG_VERSION="$(sed -n 's/^VERSION = "\(.*\)"/\1/p' "${REPO_ROOT}/turborec.py" | head -1)"
[ -n "${PKG_VERSION}" ] || die "could not read VERSION from turborec.py"
PKG_NAME="turborec"
TOP="${PKG_NAME}-${PKG_VERSION}"

log "packaging ${TOP}"

# ---- scratch build area -----------------------------------------------------
BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/turborec-tar.XXXXXX")"
trap 'rm -rf -- "${BUILD_DIR}"' EXIT INT HUP TERM
STAGE="${BUILD_DIR}/${TOP}"

install_file() {  # src dst mode
    dir="$(dirname -- "$2")"
    [ -d "${dir}" ] || mkdir -p -- "${dir}"
    cp -- "$1" "$2"
    chmod "$3" "$2"
}

mkdir -p -- "${STAGE}"

# executables (installed without the .py extension, exactly like the .deb/.rpm)
install_file "${REPO_ROOT}/turborec.py"   "${STAGE}/turborec"      0755
install_file "${REPO_ROOT}/turborecorder" "${STAGE}/turborecorder" 0755

# docs (only what exists)
for doc in README.md CHANGELOG.md LICENSE; do
    [ -f "${REPO_ROOT}/${doc}" ] && install_file "${REPO_ROOT}/${doc}" "${STAGE}/${doc}" 0644
done

# desktop entry + scalable icon (used by the optional desktop integration)
[ -f "${SCRIPT_DIR}/turborec.desktop" ] && \
    install_file "${SCRIPT_DIR}/turborec.desktop" \
        "${STAGE}/share/applications/turborec.desktop" 0644
[ -f "${SCRIPT_DIR}/turborec.svg" ] && \
    install_file "${SCRIPT_DIR}/turborec.svg" \
        "${STAGE}/share/icons/hicolor/scalable/apps/turborec.svg" 0644

# =============================================================================
#  install.sh / uninstall.sh — POSIX, PREFIX/DESTDIR aware
# =============================================================================
cat > "${STAGE}/install.sh" <<'INSTALL_EOF'
#!/bin/sh
# Install Turbo Recorder.  Honours PREFIX (default /usr/local — the BSD
# convention) and DESTDIR (staging root for packagers).  Usage:
#     ./install.sh                 # -> /usr/local
#     PREFIX=$HOME/.local ./install.sh
#     sudo ./install.sh            # system-wide
set -eu

PREFIX="${PREFIX:-/usr/local}"
DESTDIR="${DESTDIR:-}"
HERE="$(cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd -P)"

BIN="${DESTDIR}${PREFIX}/bin"
APPS="${DESTDIR}${PREFIX}/share/applications"
ICONS="${DESTDIR}${PREFIX}/share/icons/hicolor/scalable/apps"
DOCS="${DESTDIR}${PREFIX}/share/doc/turborec"

echo "Installing Turbo Recorder to ${PREFIX} ..."

mkdir -p "${BIN}" "${DOCS}"
cp "${HERE}/turborec"      "${BIN}/turborec"
cp "${HERE}/turborecorder" "${BIN}/turborecorder"
chmod 0755 "${BIN}/turborec" "${BIN}/turborecorder"

for doc in README.md CHANGELOG.md LICENSE; do
    [ -f "${HERE}/${doc}" ] && cp "${HERE}/${doc}" "${DOCS}/${doc}"
done

if [ -f "${HERE}/share/applications/turborec.desktop" ]; then
    mkdir -p "${APPS}"
    cp "${HERE}/share/applications/turborec.desktop" "${APPS}/turborec.desktop"
fi
if [ -f "${HERE}/share/icons/hicolor/scalable/apps/turborec.svg" ]; then
    mkdir -p "${ICONS}"
    cp "${HERE}/share/icons/hicolor/scalable/apps/turborec.svg" "${ICONS}/turborec.svg"
fi

echo "Done.  Installed:"
echo "  ${BIN}/turborec"
echo "  ${BIN}/turborecorder"
echo

# Runtime prerequisites (informational — not installed by this script).
missing=""
command -v python3 >/dev/null 2>&1 || missing="${missing} python3"
command -v ffmpeg  >/dev/null 2>&1 || missing="${missing} ffmpeg"
if [ -n "${missing}" ]; then
    echo "NOTE: install the runtime prerequisites for your system:${missing}"
    echo "  FreeBSD:  pkg install python3 ffmpeg     (Wayland: pkg install wf-recorder)"
    echo "  OpenBSD:  pkg_add python3 ffmpeg"
    echo "  Linux:    use your package manager (apt/dnf/pacman): python3 ffmpeg"
fi
echo "Run 'turborec gui' or 'turborec --help' to get started."
INSTALL_EOF
chmod 0755 "${STAGE}/install.sh"

cat > "${STAGE}/uninstall.sh" <<'UNINSTALL_EOF'
#!/bin/sh
# Remove a Turbo Recorder install created by install.sh.  Honours the same
# PREFIX/DESTDIR variables.
set -eu
PREFIX="${PREFIX:-/usr/local}"
DESTDIR="${DESTDIR:-}"
echo "Removing Turbo Recorder from ${PREFIX} ..."
rm -f "${DESTDIR}${PREFIX}/bin/turborec" \
      "${DESTDIR}${PREFIX}/bin/turborecorder" \
      "${DESTDIR}${PREFIX}/share/applications/turborec.desktop" \
      "${DESTDIR}${PREFIX}/share/icons/hicolor/scalable/apps/turborec.svg"
rm -rf "${DESTDIR}${PREFIX}/share/doc/turborec"
echo "Done."
UNINSTALL_EOF
chmod 0755 "${STAGE}/uninstall.sh"

# =============================================================================
#  Assemble the tarball (deterministic where the tar supports it)
# =============================================================================
mkdir -p -- "${DIST_DIR}"
TARBALL="${DIST_DIR}/${TOP}.tar.gz"
rm -f -- "${TARBALL}"

# GNU tar accepts reproducibility flags; BSD/base tar does not — detect and adapt.
if tar --version 2>/dev/null | grep -qi 'gnu tar'; then
    SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(date +%s)}"
    tar --owner=0 --group=0 --numeric-owner \
        --mtime="@${SOURCE_DATE_EPOCH}" --sort=name --format=gnu \
        -C "${BUILD_DIR}" -cf - "${TOP}" | gzip -9 -n > "${TARBALL}"
else
    ( cd "${BUILD_DIR}" && tar -cf - "${TOP}" ) | gzip -9 > "${TARBALL}"
fi

log "built: ${TARBALL}"
printf '%s\n' "${TARBALL}"
