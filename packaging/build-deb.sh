#!/usr/bin/env bash
# =============================================================================
#  build-deb.sh — build dist/turborec_2.2.0_all.deb
#
#  Stages the install layout from the repository and assembles a Debian
#  package.  Uses dpkg-deb when available; otherwise falls back to a portable
#  pure-userland assembly using only `ar`, `tar`, `gzip` and `xz`.
#
#  Portable .deb layout (ar members, in this exact order):
#      1. debian-binary       ("2.0\n")
#      2. control.tar.gz      (control, md5sums, maintainer scripts)
#      3. data.tar.xz         (the staged filesystem tree)
#
#  License: GPL-3.0 (same as the project).
# =============================================================================
set -euo pipefail

# ---- package metadata -------------------------------------------------------
PKG_NAME="turborec"
PKG_VERSION="2.2.0"
PKG_ARCH="all"

# ---- resolve paths ----------------------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd -P)"
DEBIAN_DIR="${SCRIPT_DIR}/debian"
ASSETS_DIR="${SCRIPT_DIR}"
DESKTOP_FILE="${SCRIPT_DIR}/turborec.desktop"
DIST_DIR="${REPO_ROOT}/dist"

DEB_FILE="${DIST_DIR}/${PKG_NAME}_${PKG_VERSION}_${PKG_ARCH}.deb"

# ---- scratch build area -----------------------------------------------------
BUILD_DIR="$(mktemp -d "${TMPDIR:-/tmp}/turborec-deb.XXXXXX")"
STAGE_DIR="${BUILD_DIR}/stage"          # the data tree (filesystem root)
CTRL_DIR="${BUILD_DIR}/control"         # the control tree

cleanup() {
    rm -rf -- "${BUILD_DIR}"
}
trap cleanup EXIT

log() {
    printf '[build-deb] %s\n' "$*" >&2
}

die() {
    printf '[build-deb] ERROR: %s\n' "$*" >&2
    exit 1
}

need() {
    command -v "$1" >/dev/null 2>&1 || die "required tool not found: $1"
}

# ---- sanity checks ----------------------------------------------------------
need tar
need gzip

[ -f "${REPO_ROOT}/turborec.py" ]        || die "missing ${REPO_ROOT}/turborec.py"
[ -f "${REPO_ROOT}/turborecorder" ]      || die "missing ${REPO_ROOT}/turborecorder"
[ -f "${REPO_ROOT}/README.md" ]          || die "missing ${REPO_ROOT}/README.md"
[ -f "${DEBIAN_DIR}/control" ]           || die "missing ${DEBIAN_DIR}/control"
[ -f "${DESKTOP_FILE}" ]                 || die "missing ${DESKTOP_FILE}"
[ -f "${ASSETS_DIR}/turborec.svg" ]      || die "missing ${ASSETS_DIR}/turborec.svg"

# =============================================================================
#  1. Stage the data tree (the install layout)
# =============================================================================
log "staging install layout"

install -d -m 0755 "${STAGE_DIR}/usr/bin"
install -d -m 0755 "${STAGE_DIR}/usr/share/applications"
install -d -m 0755 "${STAGE_DIR}/usr/share/icons/hicolor/scalable/apps"
install -d -m 0755 "${STAGE_DIR}/usr/share/icons/hicolor/256x256/apps"
install -d -m 0755 "${STAGE_DIR}/usr/share/doc/${PKG_NAME}"

# executables
install -m 0755 "${REPO_ROOT}/turborec.py"   "${STAGE_DIR}/usr/bin/turborec"
install -m 0755 "${REPO_ROOT}/turborecorder" "${STAGE_DIR}/usr/bin/turborecorder"

# desktop entry
install -m 0644 "${DESKTOP_FILE}" \
    "${STAGE_DIR}/usr/share/applications/turborec.desktop"

# scalable icon
install -m 0644 "${ASSETS_DIR}/turborec.svg" \
    "${STAGE_DIR}/usr/share/icons/hicolor/scalable/apps/turborec.svg"

# raster icon — generate the 256x256 PNG from the SVG
PNG_OUT="${STAGE_DIR}/usr/share/icons/hicolor/256x256/apps/turborec.png"
if command -v rsvg-convert >/dev/null 2>&1; then
    log "rasterizing icon with rsvg-convert"
    rsvg-convert -w 256 -h 256 "${ASSETS_DIR}/turborec.svg" -o "${PNG_OUT}"
elif command -v inkscape >/dev/null 2>&1; then
    log "rasterizing icon with inkscape"
    inkscape "${ASSETS_DIR}/turborec.svg" \
        --export-type=png --export-filename="${PNG_OUT}" \
        -w 256 -h 256 >/dev/null 2>&1
elif command -v convert >/dev/null 2>&1; then
    log "rasterizing icon with ImageMagick convert"
    convert -background none -density 384 \
        "${ASSETS_DIR}/turborec.svg" -resize 256x256 "${PNG_OUT}"
elif [ -f "${ASSETS_DIR}/turborec.png" ]; then
    log "using pre-rendered ${ASSETS_DIR}/turborec.png"
    install -m 0644 "${ASSETS_DIR}/turborec.png" "${PNG_OUT}"
else
    die "no SVG rasterizer (rsvg-convert/inkscape/convert) and no fallback PNG"
fi
chmod 0644 "${PNG_OUT}"

# documentation
install -m 0644 "${REPO_ROOT}/README.md" \
    "${STAGE_DIR}/usr/share/doc/${PKG_NAME}/README.md"

# =============================================================================
#  2. Build the control tree
# =============================================================================
log "building control metadata"

install -d -m 0755 "${CTRL_DIR}"

# control file (with computed Installed-Size appended)
installed_kib="$(du -k -s "${STAGE_DIR}" | awk '{print $1}')"
cp "${DEBIAN_DIR}/control" "${CTRL_DIR}/control"
printf 'Installed-Size: %s\n' "${installed_kib}" >> "${CTRL_DIR}/control"

# maintainer scripts (optional, but provided)
for script in postinst postrm preinst prerm; do
    if [ -f "${DEBIAN_DIR}/${script}" ]; then
        install -m 0755 "${DEBIAN_DIR}/${script}" "${CTRL_DIR}/${script}"
    fi
done

# conffiles (only if declared; this package ships none)
if [ -f "${DEBIAN_DIR}/conffiles" ]; then
    install -m 0644 "${DEBIAN_DIR}/conffiles" "${CTRL_DIR}/conffiles"
fi

# md5sums — relative paths, no leading "./", sorted for reproducibility
need md5sum
(
    cd -- "${STAGE_DIR}"
    find . -type f -print0 \
        | LC_ALL=C sort -z \
        | xargs -0 md5sum \
        | sed 's@  \./@  @'
) > "${CTRL_DIR}/md5sums"
chmod 0644 "${CTRL_DIR}/md5sums"

# =============================================================================
#  3. Assemble the .deb
# =============================================================================
mkdir -p "${DIST_DIR}"
rm -f -- "${DEB_FILE}"

# Reproducibility: fixed mtime for archive members.
SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-$(date +%s)}"
export SOURCE_DATE_EPOCH

if command -v dpkg-deb >/dev/null 2>&1; then
    log "dpkg-deb found — building with dpkg-deb"
    PKG_ROOT="${BUILD_DIR}/pkgroot"
    install -d -m 0755 "${PKG_ROOT}/DEBIAN"
    # data tree
    cp -a "${STAGE_DIR}/." "${PKG_ROOT}/"
    # control tree (DEBIAN/)
    cp -a "${CTRL_DIR}/." "${PKG_ROOT}/DEBIAN/"
    dpkg-deb --root-owner-group --build "${PKG_ROOT}" "${DEB_FILE}"
else
    log "dpkg-deb NOT found — assembling portable .deb with ar/tar/gzip/xz"
    need ar
    need xz

    # Common tar flags for deterministic, root-owned archives.
    # GNU tar: force ownership to root, strip nondeterministic metadata.
    TAR_COMMON=(
        --owner=root --group=root --numeric-owner
        --mtime="@${SOURCE_DATE_EPOCH}"
        --sort=name
        --format=gnu
    )

    # 3a. debian-binary
    printf '2.0\n' > "${BUILD_DIR}/debian-binary"

    # 3b. control.tar.gz  (members at top level: ./control, ./md5sums, ...)
    log "creating control.tar.gz"
    tar "${TAR_COMMON[@]}" -C "${CTRL_DIR}" -cf - . \
        | gzip -9 -n > "${BUILD_DIR}/control.tar.gz"

    # 3c. data.tar.xz  (the filesystem tree rooted at ./)
    log "creating data.tar.xz"
    tar "${TAR_COMMON[@]}" -C "${STAGE_DIR}" -cf - . \
        | xz -9 -e -T0 -c > "${BUILD_DIR}/data.tar.xz"

    # 3d. assemble the ar archive in the REQUIRED member order.
    #     -r adds/replaces; we add members one at a time to guarantee order.
    #     -D = deterministic (zero mtime/uid/gid, fixed mode) for reproducibility.
    log "assembling ${DEB_FILE} with ar"
    rm -f -- "${DEB_FILE}"
    ar -q -c -D "${DEB_FILE}" "${BUILD_DIR}/debian-binary"
    ar -q -D    "${DEB_FILE}" "${BUILD_DIR}/control.tar.gz"
    ar -q -D    "${DEB_FILE}" "${BUILD_DIR}/data.tar.xz"
fi

log "built: ${DEB_FILE}"

# ---- friendly summary -------------------------------------------------------
if command -v ar >/dev/null 2>&1; then
    log "ar members:"
    ar t "${DEB_FILE}" >&2
fi

printf '%s\n' "${DEB_FILE}"
