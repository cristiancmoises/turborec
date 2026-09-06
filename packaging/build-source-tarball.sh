#!/bin/sh
# Build the immutable, distribution-friendly source archive published with a
# release. Unlike the portable Unix archive, this contains the complete tracked
# source tree, including tests and packaging metadata.
set -eu

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" >/dev/null 2>&1 && pwd -P)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." >/dev/null 2>&1 && pwd -P)"
DIST_DIR="${REPO_ROOT}/dist"

log() { printf '[build-source-tarball] %s\n' "$*" >&2; }
die() { printf '[build-source-tarball] ERROR: %s\n' "$*" >&2; exit 1; }

command -v git >/dev/null 2>&1 || die "required tool not found: git"
command -v gzip >/dev/null 2>&1 || die "required tool not found: gzip"

git -C "${REPO_ROOT}" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || die "repository metadata is required"

# A source release must describe one exact commit. Refuse to silently omit
# uncommitted edits when somebody invokes the builder by hand.
git -C "${REPO_ROOT}" diff --quiet --ignore-submodules -- \
    || die "tracked working-tree changes are present; commit them first"
git -C "${REPO_ROOT}" diff --cached --quiet --ignore-submodules -- \
    || die "staged changes are present; commit them first"

PKG_VERSION="$(git -C "${REPO_ROOT}" show HEAD:turborec.py \
    | sed -n 's/^VERSION = "\(.*\)"/\1/p' | head -1)"
[ -n "${PKG_VERSION}" ] || die "could not read VERSION from HEAD:turborec.py"

TOP="turborec-${PKG_VERSION}"
OUT="${DIST_DIR}/${TOP}-source.tar.gz"
mkdir -p -- "${DIST_DIR}"
rm -f -- "${OUT}"

# git archive records the commit timestamp and sorted tree order. gzip -n
# removes compressor timestamps and names, so one commit builds identically.
git -C "${REPO_ROOT}" archive --format=tar --prefix="${TOP}/" HEAD \
    | gzip -9 -n > "${OUT}"

test -s "${OUT}" || die "archive is empty"
log "built: ${OUT}"
printf '%s\n' "${OUT}"
